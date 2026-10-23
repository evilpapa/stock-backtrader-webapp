"""
关注热度的 Tushare 可得替代构造（报告用 iFinD『总热度』，Tushare 无同口径数据）。

所有函数返回 日期 x ETF 宽表，可直接作为 SectorRotationData.index_heat；
下游 attention_heat_ratio 再取 5 日均值 / 250 日均值。
"""

import numpy as np
import pandas as pd


def _map_to_etf(index_heat: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
	"""指数宽表 -> ETF 宽表（同指数的 ETF 取同值）。"""
	out = index_heat.reindex(columns=pool["index_code"].values)
	out.columns = pool["etf"].values
	return out


def turnover_heat(turnover: pd.DataFrame, constituents: dict[str, list[str]], pool: pd.DataFrame) -> pd.DataFrame:
	"""
	[PROXY] 成分股日换手率中位数。保留报告“成分股热度取中位数”的结构，
	以全市场、全历史可得的换手率替代总热度（点击量）。
	"""
	cols = {c: turnover.reindex(columns=m).median(axis=1) for c, m in constituents.items()}
	return _map_to_etf(pd.DataFrame(cols), pool)


def _zero_fill_covered(df: pd.DataFrame, first: pd.Timestamp) -> pd.DataFrame:
	"""榜单覆盖期（>= first）内缺失记 0，覆盖期前保持 NaN。"""
	out = df.copy()
	covered = out.index >= first
	out.loc[covered] = out.loc[covered].fillna(0.0)
	return out


def hot_list_heat(
	hot: pd.DataFrame,
	constituents: dict[str, list[str]],
	pool: pd.DataFrame,
	days: pd.DatetimeIndex,
	value: str = "hot",
	top_n: int = 100,
) -> pd.DataFrame:
	"""
	[PARTIAL] 热榜个股 -> 指数热度：当日成分股中上榜者的热度之和，未上榜计 0。
	value='hot'（ths_hot 热度值）或 'rank'（取 top_n+1-rank，用于 dc_hot 等无 hot 的榜）。
	注意：榜单仅 Top100/200，宽指数/小指数口径不可比，且无榜单日期（早于起点）全为 0。
	"""
	h = hot.copy()
	h["trade_date"] = pd.to_datetime(h["trade_date"])
	h["v"] = h["hot"] if value == "hot" else (top_n + 1 - h["rank"])
	piv = h.pivot_table(index="trade_date", columns="ts_code", values="v", aggfunc="sum").reindex(days)
	cols = {c: piv.reindex(columns=m).sum(axis=1, min_count=1) for c, m in constituents.items()}
	out = pd.DataFrame(cols, index=days)
	# 榜单覆盖期内未上榜记 0，覆盖期前保持 NaN
	return _map_to_etf(_zero_fill_covered(out, pd.to_datetime(hot["trade_date"]).min()), pool)


def etf_hot_list_heat(
	hot_etf: pd.DataFrame, pool: pd.DataFrame, days: pd.DatetimeIndex, value: str = "hot", top_n: int = 100
) -> pd.DataFrame:
	"""[PARTIAL] ETF 自身热榜（ths_hot market=ETF）：上榜取热度，未上榜计 0。"""
	h = hot_etf.copy()
	h["trade_date"] = pd.to_datetime(h["trade_date"])
	h["v"] = h["hot"] if value == "hot" else (top_n + 1 - h["rank"])
	piv = h.pivot_table(index="trade_date", columns="ts_code", values="v", aggfunc="sum").reindex(days)
	piv = piv.reindex(columns=pool["etf"].values)
	return _zero_fill_covered(piv, h["trade_date"].min())


def board_industry_map(members: dict[str, list[str]], stock_l1: pd.Series) -> pd.DataFrame:
	"""板块 -> 中信一级行业占比（按成分股数；未映射的成分股计入分母）。返回 板块 x 行业。"""
	rows = {}
	for b, stocks in members.items():
		cnt = pd.Series(stocks).map(stock_l1).value_counts()
		rows[b] = cnt / max(len(stocks), 1)
	return pd.DataFrame(rows).T.fillna(0.0)


def board_industry_heat(hot: pd.DataFrame, bmap: pd.DataFrame, pool: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
	"""
	[PARTIAL] 行业/概念板块热榜 -> 中信一级行业热度：
	行业热度_t = Σ_板块 热度_{板块,t} × 板块成分股中该行业占比；未上榜计 0，同行业 ETF 同值。
	板块榜仅 Top20，且概念板块与行业板块混合，行业占比为静态（当前成分）。
	"""
	h = hot.copy()
	h["trade_date"] = pd.to_datetime(h["trade_date"])
	piv = h.pivot_table(index="trade_date", columns="ts_code", values="hot", aggfunc="sum").reindex(days)
	piv = piv.reindex(columns=bmap.index).fillna(0.0)
	ind = piv.to_numpy() @ bmap.to_numpy()
	ind_heat = pd.DataFrame(ind, index=days, columns=bmap.columns)
	out = pd.DataFrame(
		{etf: ind_heat[i] if i in ind_heat else np.nan for etf, i in zip(pool["etf"], pool["industry"])}, index=days
	)
	out.loc[out.index < h["trade_date"].min()] = np.nan  # 榜单覆盖期前为缺失，覆盖期内未上榜为 0
	return out


def rank_ic(factor: pd.DataFrame, close: pd.DataFrame, horizon: int = 5, step: int = 5) -> pd.Series:
	"""逐期截面 Spearman RankIC：factor_t 与 t→t+horizon 收益（每 step 日取一期）。"""
	fwd = close.shift(-horizon) / close - 1
	ics = {}
	for d in factor.index[::step]:
		a, b = factor.loc[d], fwd.loc[d]
		ok = a.notna() & b.notna()
		if ok.sum() >= 8 and a[ok].nunique() > 1:
			ics[d] = a[ok].rank().corr(b[ok].rank())
	return pd.Series(ics, dtype=float)


def ic_summary(ic: pd.Series) -> dict[str, float]:
	n = len(ic)
	return {
		"n": n,
		"IC均值": ic.mean() if n else np.nan,
		"t值": ic.mean() / ic.std() * np.sqrt(n) if n > 2 and ic.std() > 0 else np.nan,
	}
