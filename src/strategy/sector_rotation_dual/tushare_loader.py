"""
Tushare 数据加载：构造 ETF 池并生成 SectorRotationData。

接口映射（均为 Tushare Pro）：
- ETF 池：etf_basic + etf_share_size + fund_daily + index_weight + ci_index_member
- 价格：fund_daily（未复权）× fund_adj（复权因子）
- 份额：etf_share_size.total_share（万份）
- DTW 历史库：index_daily（跟踪指数），2015 年前缺失以 ci_daily（中信一级行业指数）收益回填
- 关注热度：**Tushare 无法提供论文口径**（见 HEAT_FLAG），index_heat 返回 None 或由调用方传入
"""

import hashlib
import pickle
import time
from pathlib import Path
from typing import Protocol

import pandas as pd

from src.utils.datahub_client import DataHubClient

from .data import SectorRotationData

HEAT_FLAG = (
	"UNAVAILABLE(tushare): 论文用 iFinD 个股『总热度』(K线+分时+搜索点击)；Tushare 仅有 ths_hot/dc_hot "
	"每日 Top100/200 热榜(约 2024 年起，口径为 App 热度)，无法构造 250 日基线与成分股中位数"
)
SOURCE_FLAGS = {
	"open/close": "tushare: fund_daily × fund_adj",
	"shares": "tushare: etf_share_size.total_share",
	"industry": "tushare(近似): index_weight × ci_index_member，成分股>50% 规则；当前成分回填，非 PIT",
	"history_close": "tushare: index_daily；2015 年前缺失以 ci_daily 行业指数回填",
	"pool": "tushare(近似): 定量规则可复现；定性『每赛道选最大指数』以『每行业规模前 K』近似，非报告原表 62 指数",
	"index_heat": HEAT_FLAG,
}


class _DataQueryClient(Protocol):
	"""Loader 所需的最小统一查询接口，避免依赖任何 SDK 客户端类型。"""

	def query(self, api_name: str, **kwargs: object) -> pd.DataFrame: ...


class TushareSectorRotationLoader:
	FRESH_DAYS = 10  # 查询日期距今不足 N 天视为“近期”，不缓存

	@classmethod
	def _recent(cls, kw: dict) -> bool:
		for k in ("trade_date", "end_date"):
			v = kw.get(k)
			if v and (pd.Timestamp.today() - pd.Timestamp(v)).days < cls.FRESH_DAYS:
				return True
		return False

	def __init__(
		self,
		client: _DataQueryClient | None = None,
		cache_dir: str | Path = "data/sector_rotation_dual",
		sleep: float = 0.12,
		retries: int = 10,
	):
		self.client = client or DataHubClient()
		self.cache_dir = Path(cache_dir)
		self.sleep = sleep
		self.retries = retries

	# ---------- 基础调用（带磁盘缓存与重试）----------
	def _call(self, name: str, cache: bool = True, **kw) -> pd.DataFrame:
		key = hashlib.md5(f"{name}{sorted(kw.items())}".encode()).hexdigest()
		path = self.cache_dir / f"{name}_{key}.pkl"
		# 查询触及近期（单日 trade_date 或区间 end_date）不走缓存：
		# 热榜 22:30 才终版、份额次日 8:30 才入库、行情区间末端可能尚未入库，缓存会固化半成品
		fresh = self._recent(kw)
		if cache and not fresh and path.exists():
			return pickle.loads(path.read_bytes())
		for i in range(self.retries):
			try:
				# DataHubClient 和迁移期兼容客户端都提供统一 query；
				# Loader 不再感知第三方 Pro 对象。
				df = self.client.query(name, **kw)
				break
			except Exception:
				if i == self.retries - 1:
					raise
				time.sleep(min(5 * 2**i, 60))  # 网络断开/限流时指数退避
		time.sleep(self.sleep)
		df = pd.DataFrame() if df is None else df
		if cache and not fresh:
			self.cache_dir.mkdir(parents=True, exist_ok=True)
			path.write_bytes(pickle.dumps(df))
		return df

	def _call_range(self, name: str, start: str, end: str, **kw) -> pd.DataFrame:
		"""
		区间查询拆成“历史段（缓存）+ 近期段（不缓存）”：每周只重取近期增量。
		历史边界取 (今天-FRESH_DAYS-5 天) 所在月份的月初前一日，按月才变动，缓存按月失效。
		"""
		bound = (pd.Timestamp.today() - pd.Timedelta(days=self.FRESH_DAYS + 5)).replace(day=1) - pd.Timedelta(days=1)
		b = bound.strftime("%Y%m%d")
		if pd.Timestamp(end) <= bound:
			return self._call(name, start_date=start, end_date=end, **kw)
		parts = []
		if pd.Timestamp(start) <= bound:
			parts.append(self._call(name, start_date=start, end_date=b, **kw))
		tail_start = max(pd.Timestamp(start), bound + pd.Timedelta(days=1)).strftime("%Y%m%d")
		parts.append(self._call(name, start_date=tail_start, end_date=end, **kw))
		parts = [x for x in parts if not x.empty]
		if not parts:
			return pd.DataFrame()
		df = pd.concat(parts, ignore_index=True)
		return df.drop_duplicates("trade_date") if "trade_date" in df else df

	def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
		"""交易日历（以沪深300指数日线为准）。"""
		df = self._call_range("index_daily", start, end, ts_code="000300.SH")
		return pd.DatetimeIndex(sorted(pd.to_datetime(df["trade_date"])))

	def last_completed_week_end(self, today: str | pd.Timestamp | None = None) -> pd.Timestamp:
		"""
		最近一个**已结束周**的最后一个交易日：该周最后一个开市日 < today（含节假日调休）。
		周五当天（数据未终版）不算已结束；周末/周一早盘运行得到上周最后交易日。
		"""
		today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
		cal = self._call(
			"trade_cal", cache=False, exchange="SSE",
			start_date=(today - pd.Timedelta(days=21)).strftime("%Y%m%d"),
			end_date=(today + pd.Timedelta(days=7)).strftime("%Y%m%d"),
		)
		# DataHub 标准交易日历字段为 trade_date；旧磁盘缓存可能仍保留
		# Tushare 原始字段 cal_date，因此在边界处兼容读取，业务逻辑只依赖
		# 统一后的交易日期语义。
		date_column = "trade_date" if "trade_date" in cal.columns else "cal_date"
		opened = pd.Series(pd.to_datetime(cal[cal["is_open"] == 1][date_column])).sort_values()
		last_open = opened.groupby(opened.dt.to_period("W-SUN")).last()
		done = last_open[last_open < today]
		if done.empty:
			raise ValueError("trade_cal 无已结束周的交易日")
		return done.iloc[-1]

	# ---------- ETF 池 ----------
	def build_pool(
		self,
		asof: str,
		min_index_size_wan: float = 15000.0,  # 1.5 亿元
		min_avg_amount_qian: float = 10000.0,  # 1000 万元（Tushare amount 单位千元）
		amount_days: int = 20,
		top_k_per_industry: int = 3,
		industry_share: float = 0.5,
	) -> pd.DataFrame:
		"""
		定量规则：同一指数的 ETF 规模、成交额合计过阈值；指数成分股中某一中信一级行业权重>50%。
		定性规则（每赛道选最大指数）无法自动化，以“每行业规模前 K 个指数”近似。
		返回列：etf, index_code, industry, index_size_wan。
		"""
		end = pd.Timestamp(asof)
		cal = self.calendar((end - pd.Timedelta(days=60)).strftime("%Y%m%d"), end.strftime("%Y%m%d"))
		days = list(cal[-amount_days:])
		basic = self._call("etf_basic", list_status="L")
		basic = basic[basic["index_code"].notna() & (basic["index_code"] != "")]
		if "etf_type" in basic:
			basic = basic[basic["etf_type"] != "QDII"]  # 取值为 纯境内/QDII

		size = pd.DataFrame()
		for d in reversed(days):  # 最新交易日份额可能尚未入库，向前回退
			size = self._call("etf_share_size", trade_date=d.strftime("%Y%m%d"))
			if not size.empty:
				break
		size = size.set_index("ts_code")["total_size"]
		amt = pd.concat(
			[self._call("fund_daily", trade_date=d.strftime("%Y%m%d")).set_index("ts_code")["amount"] for d in days],
			axis=1,
		).mean(axis=1)

		df = basic.assign(size=basic["ts_code"].map(size), amount=basic["ts_code"].map(amt)).dropna(subset=["size"])
		idx = df.groupby("index_code").agg(size=("size", "sum"), amount=("amount", "sum"))
		idx = idx[(idx["size"] >= min_index_size_wan) & (idx["amount"] >= min_avg_amount_qian)]

		members = self._call("ci_index_member", is_new="Y").drop_duplicates("ts_code").set_index("ts_code")["l1_name"]
		start_w = (end - pd.Timedelta(days=45)).strftime("%Y%m%d")
		rows = []
		for code, r in idx.iterrows():
			w = self._call("index_weight", index_code=code, start_date=start_w, end_date=end.strftime("%Y%m%d"))
			if w.empty:
				continue
			w = w[w["trade_date"] == w["trade_date"].max()]
			share = w.assign(ind=w["con_code"].map(members)).groupby("ind")["weight"].sum() / w["weight"].sum()
			if share.empty or share.max() <= industry_share:
				continue
			rep = df[df["index_code"] == code].sort_values("size", ascending=False)["ts_code"].iloc[0]
			rows.append({"etf": rep, "index_code": code, "industry": share.idxmax(), "index_size_wan": r["size"]})
		pool = pd.DataFrame(rows, columns=["etf", "index_code", "industry", "index_size_wan"])
		if pool.empty:
			raise ValueError(f"ETF 池为空（asof={asof}）：请检查 Tushare 权限或放宽过滤阈值")
		pool = (
			pool.sort_values("index_size_wan", ascending=False)
			.groupby("industry", group_keys=False)
			.head(top_k_per_industry)
			.sort_values(["industry", "index_size_wan"], ascending=[True, False])
			.drop_duplicates("etf")
			.reset_index(drop=True)
		)
		return pool

	# ---------- 行情/份额/历史库 ----------
	def load(
		self,
		pool: pd.DataFrame,
		start: str,
		end: str,
		hist_start: str = "20150101",
		index_heat: pd.DataFrame | None = None,
		heat: str | None = None,
	) -> SectorRotationData:
		"""pool 需含 etf/index_code/industry 列（build_pool 的输出，或自定义）。"""
		cal = self.calendar(hist_start, end)
		start_ts = pd.Timestamp(start)
		days = cal[cal >= start_ts]
		open_, close, shares, hist = {}, {}, {}, {}
		ci_codes = self._ci_l1_codes()

		for _, r in pool.iterrows():
			etf = r["etf"]
			px = self._call_range("fund_daily", hist_start, end, ts_code=etf)
			adj = self._call_range("fund_adj", hist_start, end, ts_code=etf)
			sh = self._call_range("etf_share_size", hist_start, end, ts_code=etf)
			if px.empty:
				continue
			px = px.assign(date=pd.to_datetime(px["trade_date"])).set_index("date").sort_index()
			f = (
				adj.assign(date=pd.to_datetime(adj["trade_date"])).set_index("date")["adj_factor"].sort_index()
				if not adj.empty
				else pd.Series(1.0, index=px.index)
			)
			f = f.reindex(px.index.union(f.index)).ffill().bfill().reindex(px.index)
			f = f / f.iloc[-1]  # 前复权
			open_[etf] = (px["open"] * f).reindex(days)
			close[etf] = (px["close"] * f).reindex(days)
			if not sh.empty:
				s = sh.assign(date=pd.to_datetime(sh["trade_date"])).set_index("date")["total_share"].sort_index()
				shares[etf] = (s * 1e4).reindex(cal).ffill().reindex(days)
			else:
				shares[etf] = pd.Series(float("nan"), index=days)
			hist[etf] = self._history_nav(r["index_code"], ci_codes.get(r["industry"]), cal, hist_start, end)

		cols = list(close)
		industry = pool.set_index("etf")["industry"].reindex(cols)
		data = SectorRotationData(
			open=pd.DataFrame(open_)[cols],
			close=pd.DataFrame(close)[cols],
			shares=pd.DataFrame(shares)[cols],
			index_heat=index_heat.reindex(index=days, columns=cols) if index_heat is not None else None,
			industry=industry,
			history_close=pd.DataFrame(hist)[cols],
			source_flags=dict(SOURCE_FLAGS),
		)
		if index_heat is not None:
			data.source_flags["index_heat"] = "EXTERNAL: 调用方传入"
		elif heat is not None:
			data.index_heat = self.build_heat(heat, pool, data.close.index, end)[list(data.close.columns)]
			data.source_flags["index_heat"] = self.HEAT_KINDS[heat]
		return data

	HEAT_KINDS = {
		"ths_etf": "PARTIAL(tushare ths_hot ETF榜): ETF 热度，约 2023-08 起，仅 Top100，未上榜计 0",
		"ths_stock": "PARTIAL(tushare ths_hot 热股榜): 成分股上榜热度之和，约 2023-08 起，仅 Top100",
		"ths_board": "PARTIAL(tushare ths_hot 行业/概念板块榜→中信一级行业): 板块热度按成分股行业占比分摊，约 2023-08 起，仅 Top20",
		"etf_amount": "PROXY(tushare fund_daily): ETF 成交额，非点击量",
		"index_amount": "PROXY(tushare index_daily): 跟踪指数成交额，非点击量",
	}

	def build_heat(self, kind: str, pool: pd.DataFrame, days: pd.DatetimeIndex, end: str) -> pd.DataFrame:
		"""按 kind 构造 index_heat 宽表（日期 x ETF）。kind 见 HEAT_KINDS。"""
		from . import heat as H

		if kind not in self.HEAT_KINDS:
			raise ValueError(f"未知热度来源 {kind}，可选 {list(self.HEAT_KINDS)}")
		if kind in ("etf_amount", "index_amount"):
			etf_amt, idx_amt = self.amount_panels(pool, "20150101", end)
			return (etf_amt if kind == "etf_amount" else idx_amt).reindex(index=days, columns=pool["etf"].values)
		if kind == "ths_board":
			hot = pd.concat(
				[self.hot_rank("ths_hot", mk, "20230801", end) for mk in ("行业板块", "概念板块")], ignore_index=True
			)
			bmap = H.board_industry_map(self.board_members(hot["ts_code"].unique()), self._ci_stock_l1())
			return H.board_industry_heat(hot, bmap, pool, days)
		if kind == "ths_etf":
			return H.etf_hot_list_heat(self.hot_rank("ths_hot", "ETF", "20230801", end), pool, days)
		return H.hot_list_heat(
			self.hot_rank("ths_hot", "热股", "20230801", end), self.constituents(pool, end), pool, days
		)

	def board_members(self, boards) -> dict[str, list[str]]:
		"""同花顺板块（ths_member）成分股，按板块缓存。"""
		out = {}
		for b in boards:
			m = self._call("ths_member", ts_code=b)
			if not m.empty:
				out[b] = list(m["con_code"])
		return out

	def _ci_stock_l1(self) -> pd.Series:
		"""股票 -> 中信一级行业名（当前成分，非 PIT）。"""
		m = self._call("ci_index_member", is_new="Y").drop_duplicates("ts_code")
		return m.set_index("ts_code")["l1_name"]

	def _ci_l1_codes(self) -> dict[str, str]:
		m = self._call("ci_index_member", is_new="Y")
		return dict(m.drop_duplicates("l1_name")[["l1_name", "l1_code"]].itertuples(index=False))

	def _history_nav(self, index_code: str, ci_code: str | None, cal: pd.DatetimeIndex, start: str, end: str) -> pd.Series:
		"""指数净值；指数上市前以中信一级行业指数回填（按首个重叠日缩放衔接）。"""
		idx = self._call_range("index_daily", start, end, ts_code=index_code)
		s = (
			idx.assign(date=pd.to_datetime(idx["trade_date"])).set_index("date")["close"].sort_index()
			if not idx.empty
			else pd.Series(dtype=float)
		)
		if ci_code and (s.empty or s.index[0] > cal[0]):
			ci = self._call_range("ci_daily", start, end, ts_code=ci_code)
			if not ci.empty:
				c = ci.assign(date=pd.to_datetime(ci["trade_date"])).set_index("date")["close"].sort_index()
				if s.empty:
					s = c
				else:
					first = s.index[0]
					s = pd.concat([c[c.index < first] * s.iloc[0] / c.loc[first], s]) if first in c.index else s
		return s.reindex(cal).ffill()

	# ---------- 热度相关原始数据 ----------
	def trading_days(self, start: str, end: str) -> list[pd.Timestamp]:
		return list(self.calendar(start, end))

	def daily_turnover(self, start: str, end: str, field: str = "turnover_rate_f") -> pd.DataFrame:
		"""全市场个股日换手率宽表（日期 x 股票），daily_basic 按交易日逐日拉取并缓存。"""
		frames = {}
		for d in self.trading_days(start, end):
			df = self._call("daily_basic", trade_date=d.strftime("%Y%m%d"), fields=f"ts_code,trade_date,{field}")
			if not df.empty:
				frames[d] = df.set_index("ts_code")[field]
		return pd.DataFrame(frames).T.sort_index()

	def hot_rank(self, api: str, market: str, start: str, end: str) -> pd.DataFrame:
		"""
		同花顺/东财热榜长表 [trade_date, ts_code, hot, rank]。api: ths_hot | dc_hot。
		ths_hot 取 is_new=Y（22:30 终版）；dc_hot 的 hot 字段为空，仅有 rank。
		"""
		out = []
		for d in self.trading_days(start, end):
			kw = {"trade_date": d.strftime("%Y%m%d"), "market": market}
			if api == "ths_hot":
				kw["is_new"] = "Y"
			df = self._call(api, **kw)
			if not df.empty:
				out.append(df[[c for c in ("trade_date", "ts_code", "hot", "rank") if c in df]])
		if not out:
			return pd.DataFrame(columns=["trade_date", "ts_code", "hot", "rank"])
		res = pd.concat([o.dropna(axis=1, how="all") for o in out], ignore_index=True)
		res["trade_date"] = res["trade_date"].astype(str).str.strip()  # 个别行带尾随空格
		return res

	def constituents(self, pool: pd.DataFrame, asof: str) -> dict[str, list[str]]:
		"""池内各跟踪指数的最新成分股（静态，非 PIT）。"""
		end = pd.Timestamp(asof)
		start = (end - pd.Timedelta(days=45)).strftime("%Y%m%d")
		out = {}
		for code in pool["index_code"].unique():
			w = self._call("index_weight", index_code=code, start_date=start, end_date=end.strftime("%Y%m%d"))
			if not w.empty:
				out[code] = list(w[w["trade_date"] == w["trade_date"].max()]["con_code"])
		return out

	def amount_panels(self, pool: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
		"""
		[PROXY] 成交额宽表（千元）：(ETF 自身 fund_daily.amount, 跟踪指数 index_daily.amount)，
		均为 日期 x ETF，可全历史获取，作为“关注度/交易活跃度”替代。
		"""
		cal = self.calendar(start, end)
		etf_amt, idx_amt = {}, {}
		for _, r in pool.iterrows():
			px = self._call_range("fund_daily", start, end, ts_code=r["etf"])
			if not px.empty:
				etf_amt[r["etf"]] = px.assign(d=pd.to_datetime(px["trade_date"])).set_index("d")["amount"].sort_index().reindex(cal)
			ix = self._call_range("index_daily", start, end, ts_code=r["index_code"])
			if not ix.empty:
				idx_amt[r["etf"]] = ix.assign(d=pd.to_datetime(ix["trade_date"])).set_index("d")["amount"].sort_index().reindex(cal)
		return pd.DataFrame(etf_amt), pd.DataFrame(idx_amt)
