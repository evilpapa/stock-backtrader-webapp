"""
双轮配置行业 ETF 策略（招商证券 2026-09-15）。

周频：每周最后一个交易日计算因子与权重，次周首个交易日开盘价调仓，
双边千一手续费。正向/反向子策略各持 6 只等权，配置层输出权重 w / 1-w。
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import allocation as alloc
from . import factors as fct
from src.constants import INITIAL_CASH
from src.utils.commission import ChinaStockCommission

from .data import SectorRotationData
from .dtw import dtw_score


@dataclass
class DualRotationResult:
	nav: pd.Series  # 组合净值（费后）
	benchmark_nav: pd.Series  # 行业 ETF 等权基准
	pos_nav: pd.Series  # 正向子策略净值（费后）
	rev_nav: pd.Series  # 反向子策略净值（费后）
	weights: pd.DataFrame  # 每个信号日：w、tz25、g12、d_pos、score、dtw_valid
	holdings: dict[pd.Timestamp, dict[str, list[str]]] = field(default_factory=dict)
	heat_used: bool = True  # False 表示反向因子退化为仅净申赎（偏离报告）


@dataclass
class SectorRotationDualStrategy:
	"""参数默认值严格取自报告。"""

	top_n: int = 6
	mom_windows: tuple[int, int] = (20, 60)
	bias_windows: tuple[int, int] = (5, 20)
	bias_drop_pct: float = 0.10
	trend_ma_weeks: int = 25
	trend_std_weeks: int = 25
	gap_mean_weeks: int = 12
	norm_weeks: int = 52  # G12 / D_pos 标准化窗口；报告正文 52 周、公式处写 25W，见 review.md
	sigmoid_scale: float = 10.0
	w_min: float = 0.2
	w_max: float = 0.8
	fee_model: str = "commission"  # commission=按 src/utils/commission.py（项目约定）；flat=报告的双边千一
	fee: float = 0.001  # 仅 fee_model="flat" 时使用
	initial_cash: float = INITIAL_CASH  # commission 模型的最低佣金依赖资金规模
	dtw_band: int = 2
	dtw_horizon: int = 5
	dtw_top_k: int = 5
	dtw_std_mult: float = 3.0  # 20 日相似度阈值 = 过去 5 年均值 + k·σ
	use_dtw: bool = True
	rebalance_every: int = 1  # 周；报告另测双周
	allow_missing_heat: bool = False  # 热度缺失时是否显式允许退化为仅净申赎（偏离报告）
	shares_lag: int = 0  # 份额滞后交易日数；报告未滞后，若 T 日份额盘后才披露应设 1

	# ---------- 信号 ----------
	def _signals(self, data: SectorRotationData, include_last: bool = False) -> dict:
		"""
		计算每个信号日（周内最后交易日）的篮子与配置权重。
		include_last=False（回测）：剔除没有次一交易日的信号日；True（实盘）：保留最后一个信号日。
		配置层只用截至信号日收盘已知的信息（信号日收盘到收盘的“信号收益”），无前视。
		"""
		if not data.heat_available and not self.allow_missing_heat:
			raise ValueError(
				"缺少 index_heat（关注热度）：Tushare 无法提供；传入外部热度，或显式设置 allow_missing_heat=True"
			)
		close = data.close
		mom = fct.momentum_score(close, self.mom_windows)
		mask = fct.bias_filter_mask(close, self.bias_windows, self.bias_drop_pct)
		rev = fct.reverse_score(data.shares.shift(self.shares_lag), close, data.index_heat, data.industry)

		days = close.index
		last_of_week = pd.Series(days, index=days).groupby(days.to_period("W-SUN")).last().tolist()
		sig_days = [
			d for d in last_of_week[:: self.rebalance_every] if include_last or days.get_loc(d) + 1 < len(days)
		]
		n = len(sig_days)
		pos_b = {d: fct.select_positive(mom.loc[d], mask.loc[d], self.top_n) for d in sig_days}
		rev_b = {d: fct.select_reverse(rev.loc[d], self.top_n) for d in sig_days}

		# --- 信号收益（无摩擦，close S_{k-1} -> close S_k，仅供配置层）---
		sig_pos, sig_rev, sig_mkt = [np.nan], [np.nan], [np.nan]
		for k in range(1, n):
			r = close.loc[sig_days[k]] / close.loc[sig_days[k - 1]] - 1
			sig_pos.append(r[pos_b[sig_days[k - 1]]].mean() if pos_b[sig_days[k - 1]] else 0.0)
			sig_rev.append(r[rev_b[sig_days[k - 1]]].mean() if rev_b[sig_days[k - 1]] else 0.0)
			sig_mkt.append(r.mean())
		idx = pd.Index(sig_days)
		sig_pos, sig_rev = pd.Series(sig_pos, idx), pd.Series(sig_rev, idx)
		market_nav = (1 + pd.Series(sig_mkt, idx).fillna(0)).cumprod()

		# --- 三信号 -> 权重 ---
		tz = alloc.trend_state_tz(market_nav, self.trend_ma_weeks, self.trend_std_weeks)
		tz.iloc[: self.trend_ma_weeks] = np.nan  # 前 25 周均线不完整
		g = alloc.style_rebalance_g(sig_pos, sig_rev, self.gap_mean_weeks, self.norm_weeks)
		hist = data.history_close if data.history_close is not None else close
		dtw_cor = self._dtw_cor(hist, sig_days, pos_b, rev_b) if self.use_dtw else pd.Series(np.nan, idx)
		d_pos = alloc.dtw_position(dtw_cor, self.norm_weeks)
		score = alloc.combine_score(tz, g, d_pos)
		w = alloc.score_to_weight(score, self.sigmoid_scale, self.w_min, self.w_max)
		heat_active = (
			fct.attention_heat_ratio(data.index_heat).notna().mean(axis=1).reindex(idx).fillna(0.0)
			if data.heat_available
			else pd.Series(0.0, idx)
		)
		weights = pd.DataFrame(
			{
				"w": w, "tz25": tz, "g12": g, "d_pos": d_pos, "score": score,
				"dtw_valid": d_pos.notna(), "heat_active": heat_active,  # heat_active=当日有热度的 ETF 占比
			}
		)
		return {"sig_days": sig_days, "pos_b": pos_b, "rev_b": rev_b, "w": w, "weights": weights}

	def latest_target(self, data: SectorRotationData) -> dict:
		"""
		实盘：以 data 的最后一个交易日为信号日，返回下一交易日开盘应持有的目标权重。
		调用方须保证最后一个交易日是该周最后一个交易日。
		"""
		s = self._signals(data, include_last=True)
		d = s["sig_days"][-1]
		if d != data.close.index[-1]:
			raise ValueError("最后一个信号日不是数据末日，数据未覆盖到周末")
		w = float(s["w"].iloc[-1])
		pos, rev = s["pos_b"][d], s["rev_b"][d]
		target = self._combine({c: 1 / len(pos) for c in pos}, {c: 1 / len(rev) for c in rev}, w)
		return {
			"signal_date": d, "w": w, "pos": pos, "rev": rev, "target": target,
			"signals": s["weights"].iloc[-1].to_dict(),
		}

	# ---------- 回测 ----------
	def run(self, data: SectorRotationData) -> DualRotationResult:
		"""
		时序：S_k=第 k 个信号日；E_k=S_k 次一交易日，开盘价调仓；
		第 k 期收益 = open(E_k) -> open(E_{k+1})。
		"""
		sg = self._signals(data, include_last=False)
		open_ = data.open
		days = data.close.index
		sig_days, pos_b, rev_b, w, weights = sg["sig_days"], sg["pos_b"], sg["rev_b"], sg["w"], sg["weights"]
		exec_days = [days[days.get_loc(d) + 1] for d in sig_days]
		n = len(sig_days)

		# --- 执行：第 k 期（k=0..n-2）---
		pos_net, rev_net, port, bench = {}, {}, {}, {}
		prev_p, prev_r, prev_c = {}, {}, {}
		v_p = v_r = v_c = self.initial_cash  # 各净值曲线的当前市值（用于最低佣金）
		for k in range(n - 1):
			e0, e1 = exec_days[k], exec_days[k + 1]
			r = open_.loc[e1] / open_.loc[e0] - 1
			p, q, wk = pos_b[sig_days[k]], rev_b[sig_days[k]], float(w.iloc[k])
			cur_p = {c: 1 / len(p) for c in p}
			cur_r = {c: 1 / len(q) for c in q}
			cur_c = self._combine(cur_p, cur_r, wk)
			rp = r[p].mean() if p else 0.0
			rr = r[q].mean() if q else 0.0
			pos_net[e1] = rp - self._fee_ratio(prev_p, cur_p, v_p)
			rev_net[e1] = rr - self._fee_ratio(prev_r, cur_r, v_r)
			port[e1] = wk * rp + (1 - wk) * rr - self._fee_ratio(prev_c, cur_c, v_c)
			v_p, v_r, v_c = v_p * (1 + pos_net[e1]), v_r * (1 + rev_net[e1]), v_c * (1 + port[e1])
			bench[e1] = r.mean()
			prev_p, prev_r, prev_c = cur_p, cur_r, cur_c

		def nav(d: dict) -> pd.Series:
			return (1 + pd.Series(d)).cumprod()

		holdings = {d: {"pos": pos_b[d], "rev": rev_b[d]} for d in sig_days}
		return DualRotationResult(
			nav(port), nav(bench), nav(pos_net), nav(rev_net), weights, holdings, heat_used=data.heat_available
		)

	@staticmethod
	def _combine(pos: dict[str, float], rev: dict[str, float], w: float) -> dict[str, float]:
		"""合并两个子策略的目标权重（同一 ETF 重叠时相加）。"""
		out: dict[str, float] = {}
		for c, x in pos.items():
			out[c] = out.get(c, 0.0) + w * x
		for c, x in rev.items():
			out[c] = out.get(c, 0.0) + (1 - w) * x
		return out

	def _fee_ratio(self, prev: dict[str, float], cur: dict[str, float], value: float) -> float:
		"""
		本次调仓手续费 / 组合市值。
		commission：逐笔订单 max(成交额×费率, 最低佣金)，费率与最低佣金取自 ChinaStockCommission（买卖同价）；
		flat：Σ|Δ权重| × fee（报告口径）。
		"""
		if self.fee_model == "flat":
			return self._turnover(prev, cur) * self.fee
		if self.fee_model != "commission":
			raise ValueError(f"未知 fee_model: {self.fee_model}")
		comm = ChinaStockCommission()
		total = 0.0
		for c in set(prev) | set(cur):
			amount = abs(cur.get(c, 0.0) - prev.get(c, 0.0)) * value
			if amount > 1e-9:
				total += max(amount * comm.p.commission, comm.p.min_comm)
		return total / value

	@staticmethod
	def _turnover(prev: dict[str, float], cur: dict[str, float]) -> float:
		"""双边换手 = Σ|Δ权重|（买入+卖出）。"""
		keys = set(prev) | set(cur)
		return float(sum(abs(cur.get(c, 0.0) - prev.get(c, 0.0)) for c in keys))

	def _dtw_cor(self, hist: pd.DataFrame, sig_days, pos_b, rev_b) -> pd.Series:
		"""
		每个信号日：各篮子 ETF 的 DTW 得分取均值（无样本者不进分母）；
		DTW_cor = 正向篮子均值 - 反向篮子均值；任一篮子整体无样本 -> NaN（弃权）。
		"""
		navs = {c: hist[c].to_numpy(float) for c in hist.columns}
		out = {}
		for d in sig_days:
			t = hist.index.get_loc(d)
			cache: dict[str, float] = {}

			def basket_mean(codes):
				vals = []
				for c in codes:
					if c not in cache:
						cache[c] = dtw_score(
							navs[c], t, band=self.dtw_band, horizon=self.dtw_horizon, top_k=self.dtw_top_k,
							std_mult=self.dtw_std_mult,
						)
					if not np.isnan(cache[c]):
						vals.append(cache[c])
				return float(np.mean(vals)) if vals else np.nan

			p, r = basket_mean(pos_b[d]), basket_mean(rev_b[d])
			out[d] = np.nan if np.isnan(p) or np.isnan(r) else p - r
		return pd.Series(out)
