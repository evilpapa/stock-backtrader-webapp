"""配置层（报告第三章）：TZ25、G12、DTW 三信号 -> 正向子策略权重 w。"""

import numpy as np
import pandas as pd


def trend_state_tz(market_nav: pd.Series, ma_window: int = 25, std_window: int = 25) -> pd.Series:
	"""
	信号一 TZ25（周频）：行业等权净值相对 25 周均线的乖离率 / 过去 25 周乖离率标准差。
	"""
	bias = market_nav / market_nav.rolling(ma_window).mean() - 1
	return bias / bias.rolling(std_window).std().replace(0, np.nan)


def style_rebalance_g(
	ret_pos: pd.Series, ret_rev: pd.Series, mean_window: int = 12, norm_window: int = 52
) -> pd.Series:
	"""
	信号二 G12（周频）：Gap = 反向周收益 - 正向周收益；Gap_m = Gap 的 12 周均值；
	G12 = (Gap_m - Gap_m 滚动均值) / Gap_m 滚动标准差。
	"""
	gap_m = (ret_rev - ret_pos).rolling(mean_window).mean()
	return (gap_m - gap_m.rolling(norm_window).mean()) / gap_m.rolling(norm_window).std().replace(0, np.nan)


def dtw_position(dtw_cor: pd.Series, norm_window: int = 52) -> pd.Series:
	"""信号三 D_pos：DTW_cor（正向篮子预期收益-反向篮子预期收益）52 周滚动 z-score。
	弃权周 DTW_cor 为 NaN，滚动统计自动跳过。"""
	r = dtw_cor.rolling(norm_window, min_periods=max(8, norm_window // 4))
	return (dtw_cor - r.mean()) / r.std().replace(0, np.nan)


def combine_score(tz: pd.Series, g: pd.Series, d_pos: pd.Series) -> pd.Series:
	"""score = [TZ25 + G12 + D_pos·v] / (2+v)；v 为 DTW 有效标志（D_pos 非空）。"""
	v = d_pos.notna().astype(float)
	score = (tz + g + d_pos.fillna(0.0) * v) / (2 + v)
	return score.where(tz.notna() & g.notna())


def score_to_weight(score: pd.Series, scale: float = 10.0, lo: float = 0.2, hi: float = 0.8) -> pd.Series:
	"""w = clip(sigmoid(S·score), lo, hi)；信号未就绪（NaN）时取中性 0.5。"""
	w = (1 / (1 + np.exp(-scale * score))).clip(lo, hi)
	return w.fillna(0.5)
