"""DTW 形态相似性（报告 3.3）：Sakoe-Chiba 带约束 DTW + 历史相似阶段前瞻收益。"""

import numpy as np


def dtw_distance_batch(query: np.ndarray, cands: np.ndarray, band: int = 2) -> np.ndarray:
	"""
	query: (L,)；cands: (N, L)。返回 query 与每个候选的带约束 DTW 距离 (N,)。
	弯曲路径限制在对角线 ±band 以内，对 N 个候选向量化。
	"""
	L = len(query)
	n = cands.shape[0]
	# dp[i][j] 仅在 |i-j|<=band 内有效，其余保持 inf
	dp = np.full((L + 1, L + 1, n), np.inf)
	dp[0, 0] = 0.0
	for i in range(1, L + 1):
		for j in range(max(1, i - band), min(L, i + band) + 1):
			cost = (query[i - 1] - cands[:, j - 1]) ** 2
			dp[i, j] = cost + np.minimum(np.minimum(dp[i - 1, j], dp[i, j - 1]), dp[i - 1, j - 1])
	return np.sqrt(dp[L, L])


def _norm_windows(series: np.ndarray, length: int) -> np.ndarray:
	"""所有以 length 为长度的滑动窗口，除以窗口首值（标准化净值）。形状 (T-length+1, length)。"""
	w = np.lib.stride_tricks.sliding_window_view(series, length)
	return w / w[:, :1]


def dtw_score(
	nav: np.ndarray,
	t: int,
	short: int = 20,
	long: int = 60,
	band: int = 2,
	horizon: int = 5,
	top_k: int = 5,
	sim_lookback: int = 1250,
	std_mult: float = 3.0,
) -> float:
	"""
	单只 ETF 在位置 t（含）的 DTW 预期收益得分；无相似样本返回 NaN。
	nav: 含历史库的净值序列（起点即历史库起点）。步骤：
	1) 20/60 日标准化净值与各历史阶段比较，距离 -> 相似度 1/(1+d)；
	2) 60 日相似度低于过去 5 年均值者剔除；20 日相似度高于过去 5 年均值+3σ 者保留；
	3) 按 20 日相似度取 Top5，其未来 horizon 日收益均值即得分。
	历史阶段需满足终点 e <= t-horizon，避免前视。
	"""
	if t < long - 1:
		return np.nan
	last_e = t - horizon  # 最晚的历史阶段终点
	first_e = long - 1
	if last_e < first_e:
		return np.nan
	ends = np.arange(first_e, last_e + 1)

	def sims(length: int) -> np.ndarray:
		q = nav[t - length + 1 : t + 1]
		q = q / q[0]
		wins = _norm_windows(nav, length)  # 窗口终点 e 对应行 e-length+1
		c = wins[ends - length + 1]
		return 1.0 / (1.0 + dtw_distance_batch(q, c, band))

	s_long, s_short = sims(long), sims(short)
	lb = slice(max(0, len(ends) - sim_lookback), None)
	keep = s_long >= s_long[lb].mean()
	keep &= s_short > s_short[lb].mean() + std_mult * s_short[lb].std()
	idx = np.flatnonzero(keep)
	if idx.size == 0:
		return np.nan
	top = idx[np.argsort(-s_short[idx])[:top_k]]
	e = ends[top]
	return float(np.mean(nav[e + horizon] / nav[e] - 1))
