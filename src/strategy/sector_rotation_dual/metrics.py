"""周频回测结果的绩效统计（替代 Backtrader 的 CustomAnalyzer）。"""

import numpy as np
import pandas as pd

from src.strategy_evaluation import evaluate_returns
from .strategy import DualRotationResult


def _ret(nav: pd.Series) -> pd.Series:
	ret = nav.pct_change(fill_method=None)
	if not ret.empty:
		ret.iloc[0] = nav.iloc[0] - 1
	return ret


def _stats(nav: pd.Series, ppy: int, bench: pd.Series | None = None) -> dict:
	ret = _ret(nav)
	evaluation = evaluate_returns(ret, ppy)
	metrics = evaluation.metrics
	out = {
		"总收益": metrics["total_return"],
		"年化收益": metrics["annual_return"],
		"年化波动": metrics["annual_volatility"],
		"夏普": metrics["sharpe"],
		"最大回撤": metrics["max_drawdown"],
		"卡玛": metrics["calmar"],
		"周胜率": (ret > 0).mean(),
	} | evaluation.scoring
	if bench is not None:
		ex = ret - _ret(bench)
		te = ex.std() * np.sqrt(ppy)
		out["年化超额"] = ex.mean() * ppy
		out["信息比率"] = out["年化超额"] / te if te else np.nan
	return out


def summarize(result: DualRotationResult, periods_per_year: int = 52) -> pd.DataFrame:
	"""组合 / 正向 / 反向 / 50-50 / 等权基准 的绩效对比表。"""
	idx = result.nav.index
	pos, rev = result.pos_nav.reindex(idx), result.rev_nav.reindex(idx)
	navs = {
		"双轮配置": result.nav,
		"正向子策略": pos,
		"反向子策略": rev,
		"50/50 固定": ((_ret(pos) + _ret(rev)) / 2 + 1).cumprod(),
		"行业等权基准": result.benchmark_nav.reindex(idx),
	}
	bench = navs["行业等权基准"]
	rows = {k: _stats(v, periods_per_year, None if k == "行业等权基准" else bench) for k, v in navs.items()}
	return pd.DataFrame(rows).T
