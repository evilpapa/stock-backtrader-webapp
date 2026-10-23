"""
子策略因子（报告第二章）。所有函数输入宽表(日期 x ETF)，输出同形状宽表，
仅使用 t 日及以前的数据（无前视）。
"""

import numpy as np
import pandas as pd


def cs_zscore(df: pd.DataFrame) -> pd.DataFrame:
	"""逐日截面 z-score。"""
	std = df.std(axis=1).replace(0, np.nan)
	return df.sub(df.mean(axis=1), axis=0).div(std, axis=0)


def sharpe(close: pd.DataFrame, window: int) -> pd.DataFrame:
	"""窗口夏普 = 日收益均值 / 日收益标准差（不年化，截面标准化后无影响）。"""
	ret = close.pct_change(fill_method=None)
	return ret.rolling(window).mean() / ret.rolling(window).std().replace(0, np.nan)


def bias(close: pd.DataFrame, window: int) -> pd.DataFrame:
	"""乖离率 = close / MA(window) - 1。"""
	return close / close.rolling(window).mean() - 1


def momentum_score(close: pd.DataFrame, windows: tuple[int, int] = (20, 60)) -> pd.DataFrame:
	"""风险调整动量：20/60 日夏普截面标准化后等权相加。"""
	return sum(cs_zscore(sharpe(close, w)) for w in windows)


def bias_filter_mask(close: pd.DataFrame, windows: tuple[int, int] = (5, 20), drop_pct: float = 0.10) -> pd.DataFrame:
	"""True=被剔除：任一乖离率（5/20 日）位于截面最高 drop_pct 者。"""
	mask = pd.DataFrame(False, index=close.index, columns=close.columns)
	for w in windows:
		b = bias(close, w)
		thresh = b.quantile(1 - drop_pct, axis=1)
		mask |= b.ge(thresh, axis=0) & b.notna()
	return mask


def net_flow_percentile(
	shares: pd.DataFrame,
	close: pd.DataFrame,
	industry: pd.Series,
	flow_window: int = 5,
	pct_window: int = 120,
) -> pd.DataFrame:
	"""
	ETF 净申赎分位数因子：
	1) 日净申购额 = Δ份额 × 价格，按中信一级行业汇总；
	2) 近 flow_window 日合计，在过去 pct_window 日中的滚动分位；
	3) 映射回 ETF（同行业得分相同）。
	"""
	flow = shares.diff() * close
	ind_flow = flow.T.groupby(industry.reindex(flow.columns)).sum(min_count=1).T
	roll = ind_flow.rolling(flow_window).sum()
	# 当日值在过去 pct_window 日（含当日）内的排名分位 (0,1]
	pct = roll.rolling(pct_window).apply(lambda x: (x <= x[-1]).mean(), raw=True)
	out = pct[industry.reindex(shares.columns).values]
	out.columns = shares.columns
	return out


def attention_heat_ratio(index_heat: pd.DataFrame, short: int = 5, long: int = 250) -> pd.DataFrame:
	"""关注过热：近 5 日平均热度 / 过去 250 日平均热度。"""
	ratio = index_heat.rolling(short).mean() / index_heat.rolling(long).mean()
	return ratio.replace([np.inf, -np.inf], np.nan)


def reverse_score(
	shares: pd.DataFrame, close: pd.DataFrame, index_heat: pd.DataFrame | None, industry: pd.Series
) -> pd.DataFrame:
	"""反向复合因子：两因子逐日截面 z-score 后等权平均；得分越低越“冷门”。
	index_heat 为 None 时退化为仅净申赎（偏离报告，调用方须显式允许）。"""
	flow = net_flow_percentile(shares, close, industry)
	if index_heat is None:
		return cs_zscore(flow)
	zf, zh = cs_zscore(flow), cs_zscore(attention_heat_ratio(index_heat))
	# 热度覆盖不到的单元格（如热榜起点之前）逐格退化为仅净申赎，不让整行得分变 NaN
	n = zf.notna().astype(int) + zh.notna().astype(int)
	return (zf.fillna(0) + zh.fillna(0)) / n.replace(0, np.nan)


def select_positive(score: pd.Series, mask: pd.Series, n: int) -> list[str]:
	"""正向篮子：剔除乖离过热后取得分最高的 n 只。"""
	s = score[~mask.reindex(score.index).fillna(False)].dropna()
	return list(s.nlargest(n).index)


def select_reverse(score: pd.Series, n: int) -> list[str]:
	"""反向篮子：取复合得分最低的 n 只。"""
	return list(score.dropna().nsmallest(n).index)
