"""从 qb/small2 迁移的全市场小市值选股 Backtrader 策略。"""

from __future__ import annotations

import math

import backtrader as bt
import numpy as np
import pandas as pd

from src.utils.qmt_universe import StockUniverseSnapshot

from ._base import BaseStrategy


class SmallCapPandasData(bt.feeds.PandasData):
	"""增加 ``amount`` 行的 QMT 日线数据源。"""

	lines = ("amount",)
	params = (("amount", -1),)  # Pandas DataFrame 中成交额列的映射位置


class SmallCapStrategy(BaseStrategy):
	"""按小流通市值、反转、流动性和 K 线形态评分的全市场选股策略。

	``universe_snapshot`` 必须由 :class:`QmtUniverseClient` 在回测起点或每次
	调仓日前构建；数据源名称使用 QMT 股票代码。 ``market_factors`` 为可选的
	日期索引表，列为 ``nhnl`` 与 ``limit_up_count``，用于复刻 qb 市场风控。
	"""

	_name = "Small2"
	params = (
		("stock_num", 30),  # 最终持仓股票数量
		("pool_num", 100),  # 按流通市值筛选后的候选池规模
		("min_cap", 5.0),  # 流通市值下限（亿元）
		("max_cap", 100.0),  # 流通市值上限（亿元）
		("listing_days", 375),  # 最低上市交易日数
		("rebalance_days", 10),  # 调仓间隔（交易日）
		("vol_days", 20),  # 波动率计算窗口
		("rev_days", 12),  # 短期反转收益率计算窗口
		("amt_days", 20),  # 平均成交额计算窗口
		("min_amt", 7_000_000.0),  # 最低平均成交额（元）
		("max_price", 25.0),  # 允许买入的最高股价
		("cap_w", 0.55),  # 流通市值因子权重
		("vol_w", 0.0),  # 波动率因子权重
		("rev_w", 0.35),  # 短期反转因子权重
		("liq_w", 0.10),  # 流动性因子权重
		("shape_w", 0.10),  # K 线形态因子权重
		("shape_days", 30),  # K 线形态统计窗口
		("atr_days", 14),  # ATR 计算窗口
		("atr_limit", 0.1),  # ATR 占收盘价的最大比例
		("amount_z_days", 20),  # 成交额 Z 分数计算窗口
		("amount_z_limit", 2.0),  # 成交额异常放大 Z 分数上限
		("pos", 1.0),  # 正常市场下的总仓位比例
		("market_guard", True),  # 是否启用市场风险门控
		("guard_nhnl", -30.0),  # 触发风险门控的 NHNL 阈值
		("guard_rel", -0.010457),  # 中证1000相对沪深300收益率阈值
		("guard_limit_up", 29),  # 触发风险门控的涨停数量上限
		("guard_pos", 0.3),  # 市场风险门控触发后的总仓位比例
		("guard_days", 20),  # 相对强弱计算窗口
		("avoid_months", (1, 4)),  # 需要清仓并回避的月份
		("main_board_only", True),  # 是否仅保留沪深主板股票
		("universe_snapshot", None),  # 单个股票池快照（研究或单期回测）
		("universe_snapshots", None),  # 按调仓日期提供的股票池快照字典
		("market_factors", None),  # 含 NHNL、涨停数的日期索引市场因子表
		("zz1000_name", "000852.SH"),  # 中证1000指数数据源名称
		("hs300_name", "000300.SH"),  # 沪深300指数数据源名称
		("min_trade_value_pct", 0.01),  # 最小调仓金额占总资产比例
		("print_log", False),  # 是否输出策略运行日志
	)

	def __init__(self) -> None:
		super().__init__()
		snapshot = self.p.universe_snapshot
		self.snapshots = self._normalize_snapshots(self.p.universe_snapshots)
		if not self.snapshots and not isinstance(snapshot, StockUniverseSnapshot):
			raise ValueError("SmallCapStrategy 需要 universe_snapshot 或按调仓日提供的 universe_snapshots")
		self.snapshot = snapshot
		self.data_by_name = {data._name: data for data in self.datas}
		self._tradable_names = set(snapshot.stocks["code"]) if isinstance(snapshot, StockUniverseSnapshot) else set()
		self._avoid_month_cleared: tuple[int, int] | None = None
		self.rebalance_history: list[dict] = []
		self.market_factors = self._normalize_market_factors(self.p.market_factors)

	def next(self) -> None:
		if self._has_pending_orders():
			return
		month = (self.datas[0].datetime.date(0).year, self.datas[0].datetime.date(0).month)
		if month[1] in self.p.avoid_months:
			if self._avoid_month_cleared != month:
				self._close_all()
				self._avoid_month_cleared = month
			return
		self._avoid_month_cleared = None
		self.rebalance_counter += 1
		if self.rebalance_counter < self.p.rebalance_days:
			return
		self.rebalance_counter = 0

		self.snapshot = self._snapshot_for_date()
		self._tradable_names = set(self.snapshot.stocks["code"])
		selected, scores = self._pick()
		exposure = self._market_position() if selected else self.p.pos
		target_weights = self._target_weights(selected, exposure)
		self._rebalance(target_weights)
		self.rebalance_history.append(
			{
				"date": self.datas[0].datetime.date(0), "selected_names": selected,
				"scores": scores, "target_weights_by_name": target_weights, "exposure": exposure,
			}
		)

	def _pick(self) -> tuple[list[str], dict[str, float]]:
		codes = self.snapshot.eligible_codes(
			self.p.listing_days, self.p.min_cap, self.p.max_cap, self.p.main_board_only,
		)[: self.p.pool_num]
		rows = []
		for code in codes:
			data = self.data_by_name.get(code)
			if data is None or len(data) < self._required_bars():
				continue
			frame = self._frame(data)
			if frame.empty:
				continue
			price = frame["close"].iloc[-1]
			if price > self.p.max_price or self._limit_move(frame):
				continue
			atr = self._atr_pct(frame).iloc[-1]
			if pd.isna(atr) or atr > self.p.atr_limit or self._amount_z(frame) > self.p.amount_z_limit:
				continue
			amount = frame["amount"].tail(self.p.amt_days).mean()
			if amount < self.p.min_amt:
				continue
			shape = self._ubl(frame)
			if pd.isna(shape):
				continue
			cap = self._cap(code)
			rows.append({
				"code": code, "cap": cap,
				"ret": price / frame["close"].iloc[-self.p.rev_days - 1] - 1,
				"vol": frame["close"].pct_change().tail(self.p.vol_days).std(),
				"amt": amount, "shape": shape,
			})
		if not rows:
			return [], {}
		score = pd.DataFrame(rows).set_index("code")
		score["score"] = (
			self.p.cap_w * score["cap"].rank(pct=True)
			+ self.p.vol_w * score["vol"].rank(pct=True)
			+ self.p.rev_w * score["ret"].rank(pct=True)
			+ self.p.liq_w * (-score["amt"]).rank(pct=True)
			+ self.p.shape_w * score["shape"].rank(pct=True)
		)
		selected = score.sort_values("score").head(self.p.stock_num)
		return selected.index.tolist(), selected["score"].to_dict()

	def _required_bars(self) -> int:
		return max(self.p.vol_days, self.p.rev_days + 1, self.p.amt_days, self.p.shape_days, self.p.atr_days, self.p.amount_z_days) + 1

	def _frame(self, data: bt.feed.DataBase) -> pd.DataFrame:
		count = self._required_bars()
		close = list(data.close.get(size=count))
		open_ = list(data.open.get(size=count))
		high = list(data.high.get(size=count))
		low = list(data.low.get(size=count))
		volume = list(data.volume.get(size=count))
		amount_line = getattr(data, "amount", None)
		amount = list(amount_line.get(size=count)) if amount_line is not None else [price * volume_ for price, volume_ in zip(close, volume)]
		frame = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": amount})
		return frame if np.isfinite(frame.to_numpy(dtype=float)).all() else pd.DataFrame()

	def _cap(self, code: str) -> float:
		value = self.snapshot.stocks.loc[self.snapshot.stocks["code"] == code, "float_market_cap"]
		return float(value.iloc[0])

	@staticmethod
	def _range(frame: pd.DataFrame) -> pd.Series:
		return (frame["high"] - frame["low"]).mask(lambda value: value.eq(0))

	def _ubl(self, frame: pd.DataFrame) -> float:
		range_ = self._range(frame)
		upper = (frame["high"] - frame[["open", "close"]].max(axis=1)) / range_
		recover = (frame["close"] - frame["low"]) / range_
		return float(upper.tail(self.p.shape_days).std() + recover.tail(self.p.shape_days).mean())

	def _atr_pct(self, frame: pd.DataFrame) -> pd.Series:
		previous = frame["close"].shift(1)
		true_range = pd.concat([frame["high"] - frame["low"], (frame["high"] - previous).abs(), (frame["low"] - previous).abs()], axis=1).max(axis=1)
		return true_range.rolling(self.p.atr_days).mean() / frame["close"]

	def _amount_z(self, frame: pd.DataFrame) -> float:
		amount = frame["amount"].tail(self.p.amount_z_days)
		std = amount.std()
		return 0.0 if not math.isfinite(std) or std == 0 else float((amount.iloc[-1] - amount.mean()) / std)

	@staticmethod
	def _limit_move(frame: pd.DataFrame) -> bool:
		if len(frame) < 2:
			return True
		change = frame["close"].iloc[-1] / frame["close"].iloc[-2] - 1
		return abs(change) >= 0.095

	def _market_position(self) -> float:
		if not self.p.market_guard or self.market_factors.empty:
			return self.p.pos
		day = pd.Timestamp(self.datas[0].datetime.date(0)).normalize()
		if day not in self.market_factors.index:
			return self.p.pos
		factor = self.market_factors.loc[day]
		if factor["nhnl"] <= self.p.guard_nhnl and factor["limit_up_count"] <= self.p.guard_limit_up and self._relative_strength() <= self.p.guard_rel:
			return self.p.guard_pos
		return self.p.pos

	def _relative_strength(self) -> float:
		zz1000, hs300 = self.data_by_name.get(self.p.zz1000_name), self.data_by_name.get(self.p.hs300_name)
		if zz1000 is None or hs300 is None or len(zz1000) <= self.p.guard_days or len(hs300) <= self.p.guard_days:
			return 0.0
		return zz1000.close[0] / zz1000.close[-self.p.guard_days] - hs300.close[0] / hs300.close[-self.p.guard_days]

	def _snapshot_for_date(self) -> StockUniverseSnapshot:
		"""取当前日最近一份不晚于它的快照，避免回测读取未来股票池数据。"""
		if not self.snapshots:
			return self.snapshot
		day = pd.Timestamp(self.datas[0].datetime.date(0)).normalize()
		available = [snapshot_day for snapshot_day in self.snapshots if snapshot_day <= day]
		if not available:
			raise ValueError(f"缺少不晚于 {day.date()} 的股票池快照")
		return self.snapshots[max(available)]

	@staticmethod
	def _normalize_snapshots(value: object) -> dict[pd.Timestamp, StockUniverseSnapshot]:
		if not isinstance(value, dict):
			return {}
		return {
			pd.Timestamp(day).normalize(): snapshot
			for day, snapshot in value.items()
			if isinstance(snapshot, StockUniverseSnapshot)
		}

	@staticmethod
	def _normalize_market_factors(value: object) -> pd.DataFrame:
		if not isinstance(value, pd.DataFrame) or value.empty:
			return pd.DataFrame(columns=["nhnl", "limit_up_count"])
		frame = value.copy()
		frame.index = pd.to_datetime(frame.index).normalize()
		return frame

	def _target_weights(self, selected: list[str], exposure: float) -> dict[str, float]:
		weight = exposure / len(selected) if selected else 0.0
		return {
			data._name: weight if data._name in selected else 0.0
			for data in self.datas
			if data._name in self._tradable_names
		}

	def _rebalance(self, target_weights: dict[str, float]) -> None:
		value = self.broker.getvalue()
		if not math.isfinite(value) or value <= 0:
			return
		threshold = value * self.p.min_trade_value_pct
		for data in self.datas:
			if data._name not in self._tradable_names:
				continue
			weight = target_weights.get(data._name, 0.0)
			if weight == 0 and self.getposition(data).size:
				self._track_order(self.close(data=data))
			elif weight > 0 and math.isfinite(data.close[0]) and data.close[0] > 0:
				diff = value * weight - self.getposition(data).size * data.close[0]
				if abs(diff) > threshold:
					size = int(diff / data.close[0])
					if size > 0:
						self._track_order(self.buy(data=data, size=size))
					elif size < 0:
						self._track_order(self.sell(data=data, size=-size))

	def _close_all(self) -> None:
		for data in self.datas:
			if data._name in self._tradable_names and self.getposition(data).size:
				self._track_order(self.close(data=data))
