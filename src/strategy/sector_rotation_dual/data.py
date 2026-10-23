"""
双轮配置行业 ETF 策略的数据容器与 mock 数据。

字段定义见 docs/sector_rotation_dual/data.md。真实数据由 tushare_loader 构造，
测试使用 make_mock_data。
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class SectorRotationData:
	"""策略所需的全部输入，所有宽表 index=交易日，columns=ETF 代码。"""

	open: pd.DataFrame  # ETF 开盘价（调仓成交价，前复权）
	close: pd.DataFrame  # ETF 收盘价（因子计算，前复权）
	shares: pd.DataFrame  # ETF 日度总份额（净申赎因子）
	index_heat: pd.DataFrame | None  # 跟踪指数日度总热度（成分股热度中位数）；Tushare 无法提供时为 None
	industry: pd.Series  # ETF -> 中信一级行业
	history_close: pd.DataFrame | None = None  # DTW 历史库（指数净值，起点 2015）；None 则用 close
	source_flags: dict[str, str] = field(default_factory=dict)  # 字段 -> 数据来源/可得性标识

	@property
	def heat_available(self) -> bool:
		return self.index_heat is not None

	def __post_init__(self):
		cols = list(self.close.columns)
		for name in ("open", "shares", "index_heat"):
			df = getattr(self, name)
			if df is None:
				continue
			if list(df.columns) != cols or not df.index.equals(self.close.index):
				raise ValueError(f"{name} 与 close 的 index/columns 不一致")
		missing = set(cols) - set(self.industry.index)
		if missing:
			raise ValueError(f"缺少行业映射: {sorted(missing)}")


def aggregate_index_heat(stock_heat: pd.DataFrame, constituents: dict[str, list[str]]) -> pd.DataFrame:
	"""指数热度 = 成分股当日总热度的中位数。stock_heat: 日期 x 股票。"""
	return pd.DataFrame(
		{idx: stock_heat.reindex(columns=members).median(axis=1) for idx, members in constituents.items()}
	)


def make_mock_data(
	n_etf: int = 12,
	n_industry: int = 4,
	n_days: int = 900,
	start: str = "2018-01-01",
	seed: int = 0,
) -> SectorRotationData:
	"""生成带行业共同因子、份额与热度的 mock 数据（仅用于开发与测试）。"""
	rng = np.random.default_rng(seed)
	dates = pd.bdate_range(start, periods=n_days)
	codes = [f"MOCK{i:02d}.SH" for i in range(n_etf)]
	ind_names = [f"ind{i % n_industry}" for i in range(n_etf)]
	industry = pd.Series(ind_names, index=codes)

	market = rng.normal(0.0003, 0.008, n_days)
	ind_factor = {k: rng.normal(0, 0.008, n_days) for k in sorted(set(ind_names))}
	rets = np.column_stack(
		[market + ind_factor[ind_names[i]] + rng.normal(0, 0.007, n_days) for i in range(n_etf)]
	)
	close = pd.DataFrame(10 * np.cumprod(1 + rets, axis=0), index=dates, columns=codes)
	open_ = close.shift(1).fillna(close.iloc[0]) * (1 + rng.normal(0, 0.002, close.shape))
	shares = pd.DataFrame(
		1e8 * np.cumprod(1 + rng.normal(0, 0.02, (n_days, n_etf)), axis=0), index=dates, columns=codes
	)
	heat = pd.DataFrame(
		1e4 * np.exp(rng.normal(0, 0.2, (n_days, n_etf)).cumsum(axis=0) * 0.05 + rng.normal(0, 0.1, (n_days, n_etf))),
		index=dates,
		columns=codes,
	)
	return SectorRotationData(open_, close, shares, heat, industry, source_flags={"all": "MOCK"})
