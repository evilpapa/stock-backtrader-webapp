"""非 Backtrader 研究型策略（双轮行业ETF、自由现金流、微盘择时、量稳换手率、高频46因子、指数择时）的
结果加载与可参数化回测服务层。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.datahub import DataKind, DataRequest, DuckDBRepository, create_service
from src.datahub.duckdb_frames import frame_exists, read_frame
from src.strategy.free_cash_flow import (
	FACTORS as FCF_FACTORS,
	FreeCashFlowParams,
	backtest_weights as fcf_backtest_weights,
	candidate_pool as fcf_candidate_pool,
	performance as fcf_performance,
	quantile_groups as fcf_quantile_groups,
	rebalance_dates as fcf_rebalance_dates,
	select as fcf_select,
	selection_cutoff as fcf_selection_cutoff,
)
from src.strategy.micro_cap_timing_plus import (
	MicroCapTimingParams,
	compute_signals as micro_compute_signals,
)
from src.strategy.sector_rotation_dual import (
	SectorRotationDualStrategy,
	TushareSectorRotationLoader,
	summarize as dual_summarize,
)
from src.strategy.turnover_stability import (
	ALL_FACTOR_NAMES as TURNOVER_ALL_FACTORS,
	TurnoverStabilityParams,
	backtest_weights as turnover_backtest_weights,
	evaluate_factor_monthly as turnover_evaluate_factor_monthly,
	month_end_dates as turnover_month_end_dates,
	performance as turnover_performance,
	select_equal_weight as turnover_select_equal_weight,
	yearly_factor_table as turnover_yearly_factor_table,
)
from src.strategy_evaluation import SCORE_COLUMNS, evaluate_returns, summarize_research_returns
from src.utils.datahub_client import DataHubClient
from src.utils.schemas import DataSourceParams


DEFAULT_SECTOR_ROTATION_DUAL_DIR = Path("examples") / "sector_rotation_dual"
DEFAULT_FREE_CASH_FLOW_DIR = Path("examples") / "free_cash_flow"
DEFAULT_MICRO_CAP_TIMING_DIR = Path("examples") / "micro_cap_timing_plus"
DEFAULT_TURNOVER_STABILITY_DIR = Path("examples") / "turnover_stability"
DEFAULT_INTRADAY_ROOT = Path("examples") / "intraday_factors"
DEFAULT_INDEX_TIMING_DIR = Path("data") / "index_timing_replication"


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _ensure_tushare_token(token: str = "") -> str | None:
	"""优先使用传入 token，其次环境变量，最后回退到项目 .env。"""
	cleaned = token.strip() or os.getenv("TUSHARE_TOKEN", "").strip()
	if cleaned:
		return cleaned
	env = Path(".env")
	if env.exists():
		match = re.search(r"^TUSHARE_TOKEN\s*=\s*[\"']?([^\"'\s#]+)", env.read_text(encoding="utf-8"), re.M)
		if match:
			return match.group(1)
	return None


def _normalize_date_frame(df: pd.DataFrame, candidate_cols: tuple[str, ...] = ("Date", "date", "trade_date", "Unnamed: 0")) -> pd.DataFrame:
	"""将首个日期列规范化命名为 Date（YYYY-MM-DD 字符串）。"""
	if df.empty:
		return df.copy()
	out = df.copy()
	date_col = next((col for col in candidate_cols if col in out.columns), None)
	if date_col is None:
		date_col = out.columns[0]
	if date_col != "Date":
		out = out.rename(columns={date_col: "Date"})
	parsed = pd.to_datetime(out["Date"], errors="coerce")
	if parsed.notna().any():
		out["Date"] = parsed.dt.strftime("%Y-%m-%d")
	return out


def _drawdown_frame_from_nav(nav_df: pd.DataFrame) -> pd.DataFrame:
	"""根据累计净值宽表（含 Date 列）计算各序列的动态回撤。"""
	if nav_df.empty or "Date" not in nav_df.columns:
		return pd.DataFrame()
	result = pd.DataFrame({"Date": nav_df["Date"]})
	for col in nav_df.columns:
		if col == "Date":
			continue
		series = pd.to_numeric(nav_df[col], errors="coerce")
		peak = series.cummax()
		result[col] = series / peak - 1.0
	return result


def _returns_from_nav_series(nav: pd.Series) -> pd.Series:
	series = pd.to_numeric(nav, errors="coerce").dropna()
	if series.empty:
		return pd.Series(dtype=float)
	returns = series.pct_change(fill_method=None)
	returns.iloc[0] = series.iloc[0] - 1.0
	return returns.replace([np.inf, -np.inf], np.nan).dropna()


def _restore_scores_from_nav(
	metrics: pd.DataFrame,
	nav_df: pd.DataFrame,
	*,
	name_col: str = "策略",
	periods_per_year: int = 252,
) -> pd.DataFrame:
	"""若绩效表缺少统一评分列，则从净值曲线补算策略评分。"""
	if metrics.empty or set(SCORE_COLUMNS).issubset(metrics.columns):
		return metrics
	if nav_df.empty or name_col not in metrics.columns:
		return metrics
	rows = []
	for row in metrics.to_dict("records"):
		name = str(row.get(name_col, ""))
		if name in nav_df.columns:
			ev = evaluate_returns(_returns_from_nav_series(nav_df[name]), periods_per_year)
			row.update(ev.scoring)
		else:
			row.update(evaluate_returns([], periods_per_year).scoring)
		rows.append(row)
	return pd.DataFrame(rows)


def _read_csv_safe(path: Path, **kwargs) -> pd.DataFrame:
	if not path.exists():
		return pd.DataFrame()
	try:
		return pd.read_csv(path, encoding="utf-8-sig", **kwargs)
	except pd.errors.EmptyDataError:
		return pd.DataFrame()


# ---------------------------------------------------------------------------
# 1. 双轮配置行业 ETF 策略 (SectorRotationDual)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectorRotationDualFrames:
	"""双轮配置行业 ETF 策略的结果表集合。"""

	metrics: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	weights: pd.DataFrame
	pool: pd.DataFrame
	nav_image: Path | None = None
	source_flags: dict[str, str] = field(default_factory=dict)


def load_sector_rotation_dual_results(
	output_dir: Path = DEFAULT_SECTOR_ROTATION_DUAL_DIR,
) -> SectorRotationDualFrames | None:
	"""读取双轮配置行业 ETF 策略的已保存结果。"""
	summary_path = output_dir / "summary.csv"
	weights_path = output_dir / "weights.csv"
	if not summary_path.exists() and not weights_path.exists():
		return None

	metrics = _read_csv_safe(summary_path)
	if not metrics.empty and "策略" not in metrics.columns:
		first_col = metrics.columns[0]
		metrics = metrics.rename(columns={first_col: "策略"})

	weights = _normalize_date_frame(_read_csv_safe(weights_path))
	pool = _read_csv_safe(output_dir / "pool.csv")
	nav_df = _normalize_date_frame(_read_csv_safe(output_dir / "nav.csv"))
	drawdown_df = _drawdown_frame_from_nav(nav_df)
	if not metrics.empty and not nav_df.empty:
		metrics = _restore_scores_from_nav(metrics, nav_df, name_col="策略", periods_per_year=52)

	nav_image = output_dir / "nav.png"
	return SectorRotationDualFrames(
		metrics=metrics,
		cumulative=nav_df,
		drawdown=drawdown_df,
		weights=weights,
		pool=pool,
		nav_image=nav_image if nav_image.exists() else None,
	)


def run_sector_rotation_dual_backtest(
	*,
	start_date: str = "2017-09-01",
	end_date: str | None = None,
	top_k: int = 3,
	top_n: int = 6,
	rebalance_every: int = 1,
	trend_ma_weeks: int = 25,
	gap_mean_weeks: int = 12,
	norm_weeks: int = 52,
	heat: str = "ths_etf",
	use_dtw: bool = True,
	fee_model: str = "commission",
	refresh_pool: bool = False,
	output_dir: Path = DEFAULT_SECTOR_ROTATION_DUAL_DIR,
	data_source_params: DataSourceParams | None = None,
) -> SectorRotationDualFrames:
	"""通过 DataHub 拉取行业 ETF 数据并运行双轮配置回测。"""
	end_str = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")
	token = _ensure_tushare_token(data_source_params.tushare_token if data_source_params else "")
	timeout = float(data_source_params.tushare_timeout) if data_source_params else 30.0

	output_dir.mkdir(parents=True, exist_ok=True)
	client = DataHubClient(token=token, timeout=timeout)
	try:
		loader = TushareSectorRotationLoader(client)
		pool_path = output_dir / "pool.csv"
		if refresh_pool or not pool_path.exists():
			pool = loader.build_pool(end_str, top_k_per_industry=int(top_k))
			pool.to_csv(pool_path, index=False, encoding="utf-8-sig")
		else:
			pool = pd.read_csv(pool_path)

		heat_source = None if heat == "none" else heat
		data = loader.load(pool, start_date.replace("-", ""), end_str.replace("-", ""), heat=heat_source)
	finally:
		client.close()

	strategy = SectorRotationDualStrategy(
		top_n=int(top_n),
		rebalance_every=int(rebalance_every),
		trend_ma_weeks=int(trend_ma_weeks),
		trend_std_weeks=int(trend_ma_weeks),
		gap_mean_weeks=int(gap_mean_weeks),
		norm_weeks=int(norm_weeks),
		use_dtw=bool(use_dtw),
		fee_model=fee_model,
		allow_missing_heat=heat_source is None,
	)
	res = strategy.run(data)
	table = dual_summarize(res)
	metrics = table.reset_index().rename(columns={"index": "策略"})

	idx = res.nav.index
	pos = res.pos_nav.reindex(idx)
	rev = res.rev_nav.reindex(idx)
	pos_ret = _returns_from_nav_series(pos).reindex(idx).fillna(0.0)
	rev_ret = _returns_from_nav_series(rev).reindex(idx).fillna(0.0)
	fixed_50 = (1.0 + (pos_ret + rev_ret) / 2.0).cumprod()
	nav_df = pd.DataFrame(
		{
			"Date": pd.to_datetime(idx).strftime("%Y-%m-%d"),
			"双轮配置": res.nav.values,
			"正向子策略": pos.values,
			"反向子策略": rev.values,
			"50/50 固定": fixed_50.values,
			"行业等权基准": res.benchmark_nav.reindex(idx).values,
		}
	)
	drawdown_df = _drawdown_frame_from_nav(nav_df)
	weights_df = _normalize_date_frame(res.weights.reset_index())

	table.to_csv(output_dir / "summary.csv", encoding="utf-8-sig")
	res.weights.to_csv(output_dir / "weights.csv", encoding="utf-8-sig")
	nav_df.to_csv(output_dir / "nav.csv", index=False, encoding="utf-8-sig")

	return SectorRotationDualFrames(
		metrics=metrics,
		cumulative=nav_df,
		drawdown=drawdown_df,
		weights=weights_df,
		pool=pool,
		source_flags=dict(data.source_flags),
	)


# ---------------------------------------------------------------------------
# 2. 增强型自由现金流策略 (FreeCashFlow)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FreeCashFlowFrames:
	"""增强型自由现金流策略回测结果表集合。"""

	metrics: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	yearly: pd.DataFrame
	groups: pd.DataFrame
	holdings: pd.DataFrame
	pool_size: pd.DataFrame
	official_overlap: pd.DataFrame


@dataclass(frozen=True)
class FreeCashFlowAccountFrames:
	"""自由现金流约束账户模拟结果表集合。"""

	metrics: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	yearly: pd.DataFrame
	positions: pd.DataFrame
	orders: pd.DataFrame
	industry_weights: pd.DataFrame
	latest_initial_orders: pd.DataFrame


def discover_free_cash_flow_account_dirs(base_dir: Path = DEFAULT_FREE_CASH_FLOW_DIR) -> list[Path]:
	"""发现自由现金流目录下可用的约束账户模拟子目录。"""
	if not base_dir.exists():
		return []
	dirs = [
		child
		for child in sorted(base_dir.iterdir())
		if child.is_dir() and (child / "metrics.csv").exists() and (child / "daily.csv").exists()
	]
	return dirs


def load_free_cash_flow_results(output_dir: Path = DEFAULT_FREE_CASH_FLOW_DIR) -> FreeCashFlowFrames | None:
	"""加载已保存的增强型自由现金流策略结果。"""
	metrics_path = output_dir / "performance_metrics.csv"
	cumulative_path = output_dir / "cumulative_returns.csv"
	if not metrics_path.exists() or not cumulative_path.exists():
		return None

	metrics = _read_csv_safe(metrics_path)
	if not metrics.empty and "策略" not in metrics.columns:
		metrics = metrics.rename(columns={metrics.columns[0]: "策略"})
	cumulative = _normalize_date_frame(_read_csv_safe(cumulative_path))
	drawdown = _drawdown_frame_from_nav(cumulative)
	metrics = _restore_scores_from_nav(metrics, cumulative, name_col="策略", periods_per_year=252)

	yearly = _read_csv_safe(output_dir / "yearly_returns.csv")
	if not yearly.empty and yearly.columns[0] in {"trade_date", "Unnamed: 0"}:
		yearly = yearly.rename(columns={yearly.columns[0]: "年份"})
	groups = _read_csv_safe(output_dir / "group_annual_returns.csv")
	if not groups.empty and groups.columns[0] == "Unnamed: 0":
		groups = groups.rename(columns={"Unnamed: 0": "因子"})
	holdings = _read_csv_safe(output_dir / "enhanced_holdings.csv")
	pool_size = _normalize_date_frame(_read_csv_safe(output_dir / "pool_size.csv"))
	overlap = _normalize_date_frame(_read_csv_safe(output_dir / "official_overlap.csv"))

	return FreeCashFlowFrames(
		metrics=metrics,
		cumulative=cumulative,
		drawdown=drawdown,
		yearly=yearly,
		groups=groups,
		holdings=holdings,
		pool_size=pool_size,
		official_overlap=overlap,
	)


def load_free_cash_flow_account_results(account_dir: Path) -> FreeCashFlowAccountFrames | None:
	"""加载自由现金流约束账户模拟结果目录。"""
	metrics_path = account_dir / "metrics.csv"
	daily_path = account_dir / "daily.csv"
	if not metrics_path.exists() or not daily_path.exists():
		return None

	metrics = _read_csv_safe(metrics_path)
	daily = _read_csv_safe(daily_path)
	cumulative = pd.DataFrame()
	if not daily.empty and {"date", "scenario", "nav"}.issubset(daily.columns):
		daily["date"] = pd.to_datetime(daily["date"])
		pivoted = daily.pivot_table(index="date", columns="scenario", values="nav", aggfunc="last").sort_index()
		normed = pivoted.div(pivoted.iloc[0])
		cumulative = normed.reset_index().rename(columns={"date": "Date"})
		cumulative["Date"] = pd.to_datetime(cumulative["Date"]).dt.strftime("%Y-%m-%d")
	drawdown = _drawdown_frame_from_nav(cumulative)
	if not metrics.empty and not cumulative.empty and "scenario" in metrics.columns:
		metrics = _restore_scores_from_nav(metrics, cumulative, name_col="scenario", periods_per_year=252)

	return FreeCashFlowAccountFrames(
		metrics=metrics,
		cumulative=cumulative,
		drawdown=drawdown,
		yearly=_read_csv_safe(account_dir / "yearly.csv"),
		positions=_read_csv_safe(account_dir / "positions.csv"),
		orders=_read_csv_safe(account_dir / "orders.csv"),
		industry_weights=_read_csv_safe(account_dir / "industry_weights.csv"),
		latest_initial_orders=_read_csv_safe(account_dir / "initial_orders_latest_signal.csv"),
	)


def run_free_cash_flow_backtest(
	*,
	data_start: str = "2012-10-01",
	start_date: str = "2014-01-01",
	end_date: str = "2026-10-30",
	size: int = 100,
	weight_cap: float = 0.10,
	liquidity_keep: float = 0.80,
	quality_keep: float = 0.80,
	ocf_years: int = 5,
	commission: float = FreeCashFlowParams.commission,
	output_dir: Path = DEFAULT_FREE_CASH_FLOW_DIR,
) -> FreeCashFlowFrames:
	"""基于本地缓存行情与财报重跑增强型自由现金流策略。"""
	from examples.free_cash_flow import (
		BENCHMARKS,
		DATA_DIR,
		load_financials,
		load_index,
		load_panels,
		market_snapshot,
	)

	params = FreeCashFlowParams(
		size=int(size),
		weight_cap=float(weight_cap),
		liquidity_keep=float(liquidity_keep),
		quality_keep=float(quality_keep),
		ocf_years=int(ocf_years),
		commission=float(commission),
	)
	panels = load_panels(data_start)
	fundamentals, annual = load_financials()
	basic = read_frame(DATA_DIR / "reference" / "stock_basic.duckdb").drop_duplicates("ts_code").set_index("ts_code")
	basic["list_date"] = pd.to_datetime(basic["list_date"], errors="coerce")
	members = read_frame(DATA_DIR / "reference" / "citic_member.duckdb")

	trading_days = panels["returns"].index
	rebalance_start = (pd.Timestamp(start_date) - pd.DateOffset(months=15)).strftime("%Y-%m-%d")
	dates = [d for d in fcf_rebalance_dates(trading_days, rebalance_start, end_date)]
	targets: dict[str, dict[pd.Timestamp, pd.Series]] = {k: {} for k in ("复现指数", "增强-FCF加权", "增强-等权")}
	group_targets: dict[str, dict[pd.Timestamp, pd.Series]] = {}
	holdings_log, pool_sizes = [], {}
	for day in dates:
		cutoff = fcf_selection_cutoff(trading_days, day)
		pool = fcf_candidate_pool(cutoff, market_snapshot(panels, basic, members, cutoff), fundamentals, annual, params)
		pool_sizes[day] = len(pool)
		targets["复现指数"][day] = fcf_select(pool, "fcf_yield", size=params.size, weighting="fcf", cap=params.weight_cap)
		enhanced = fcf_select(pool, "composite", size=params.size, weighting="fcf", cap=params.weight_cap)
		targets["增强-FCF加权"][day] = enhanced
		targets["增强-等权"][day] = fcf_select(pool, "composite", size=params.size, weighting="equal", cap=1.0)
		holdings_log.append(
			pd.DataFrame(
				{
					"date": day,
					"symbol": enhanced.index,
					"weight": enhanced.values,
					"industry": pool.loc[enhanced.index, "industry"].values,
				}
			)
		)
		for factor in ("fcf_yield", *FCF_FACTORS, "composite"):
			for g, idx in enumerate(fcf_quantile_groups(pool, factor), start=1):
				group_targets.setdefault(f"{factor}|G{g}", {})[day] = (
					pd.Series(1 / len(idx), index=idx) if len(idx) else pd.Series(dtype=float)
				)

	returns = panels["returns"]
	period = slice(start_date, end_date)
	strat = {name: fcf_backtest_weights(returns, t, params.commission) for name, t in targets.items()}
	daily = pd.DataFrame({name: r["return"] for name, r in strat.items()}).loc[period]
	bench_cols = {}
	for name, code in BENCHMARKS.items():
		idx_path = DATA_DIR / "reference" / f"index_{code}.duckdb"
		if frame_exists(idx_path):
			bench_cols[name] = load_index(code)
	if bench_cols:
		bench = pd.DataFrame(bench_cols).reindex(daily.index).pct_change(fill_method=None)
		bench.iloc[0] = np.nan
		daily = daily.join(bench)
		daily = daily.loc[daily.index[1]:]

	metrics_raw = pd.DataFrame({name: fcf_performance(daily[name].dropna()) for name in daily}).T
	metrics_raw["平均单边换手/季"] = pd.Series(
		{name: r["turnover"].loc[period][r["turnover"].loc[period] > 0].mean() / 2 for name, r in strat.items()}
	)
	yearly = (1 + daily).groupby(daily.index.year).prod() - 1
	group_rows: dict[str, dict[str, float]] = {}
	for key, t in group_targets.items():
		factor, g = key.split("|")
		group_rows.setdefault(factor, {})[g] = fcf_performance(
			fcf_backtest_weights(returns, t, params.commission)["return"].loc[start_date:end_date]
		)["年化收益"]
	groups = pd.DataFrame(group_rows).T
	cumulative_raw = (1 + daily.fillna(0)).cumprod()
	holdings = pd.concat(holdings_log, ignore_index=True) if holdings_log else pd.DataFrame()
	pool_series = pd.Series(pool_sizes, name="pool_size")

	output_dir.mkdir(parents=True, exist_ok=True)
	metrics_raw.to_csv(output_dir / "performance_metrics.csv", encoding="utf-8-sig")
	yearly.to_csv(output_dir / "yearly_returns.csv", encoding="utf-8-sig")
	groups.to_csv(output_dir / "group_annual_returns.csv", encoding="utf-8-sig")
	cumulative_raw.to_csv(output_dir / "cumulative_returns.csv", encoding="utf-8-sig")
	holdings.to_csv(output_dir / "enhanced_holdings.csv", index=False, encoding="utf-8-sig")
	pool_series.to_csv(output_dir / "pool_size.csv", encoding="utf-8-sig")

	reloaded = load_free_cash_flow_results(output_dir)
	assert reloaded is not None
	return reloaded


# ---------------------------------------------------------------------------
# 3. 微盘股择时增强策略 (MicroCapTimingPlus)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MicroCapTimingFrames:
	"""微盘股择时增强策略结果表集合。"""

	metrics: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	signals: pd.DataFrame
	micro_index: pd.DataFrame


def load_micro_cap_timing_results(
	output_dir: Path = DEFAULT_MICRO_CAP_TIMING_DIR,
) -> MicroCapTimingFrames | None:
	"""加载已保存的微盘股择时增强策略结果。"""
	metrics_path = output_dir / "performance_metrics.csv"
	cumulative_path = output_dir / "cumulative_returns.csv"
	if not metrics_path.exists() or not cumulative_path.exists():
		return None

	metrics = _read_csv_safe(metrics_path)
	if not metrics.empty and "策略" not in metrics.columns:
		metrics = metrics.rename(columns={metrics.columns[0]: "策略"})
	cumulative = _normalize_date_frame(_read_csv_safe(cumulative_path))
	drawdown = _drawdown_frame_from_nav(cumulative)
	metrics = _restore_scores_from_nav(metrics, cumulative, name_col="策略", periods_per_year=252)

	return MicroCapTimingFrames(
		metrics=metrics,
		cumulative=cumulative,
		drawdown=drawdown,
		signals=_normalize_date_frame(_read_csv_safe(output_dir / "signals.csv")),
		micro_index=_normalize_date_frame(_read_csv_safe(output_dir / "micro_cap_index.csv")),
	)


def run_micro_cap_timing_backtest(
	*,
	start_date: str = "2016-01-04",
	end_date: str = "2026-06-30",
	size: int = 400,
	min_listed_days: int = 60,
	ma_window: int = 15,
	bottom_hold_days: int = 20,
	top_lock_days: int = 10,
	cost: float = 0.001,
	large_code: str = "000300.SH",
	small_code: str | None = "932000.CSI",
	output_dir: Path = DEFAULT_MICRO_CAP_TIMING_DIR,
) -> MicroCapTimingFrames:
	"""基于本地全市场缓存重跑微盘股择时增强策略。"""
	from examples.micro_cap_timing_plus import build_dataset, summarize

	params = MicroCapTimingParams(
		ma_window=int(ma_window),
		bottom_hold_days=int(bottom_hold_days),
		top_lock_days=int(top_lock_days),
		cost=float(cost),
	)
	index, factors, style_gap, _ = build_dataset(
		size=int(size),
		min_listed_days=int(min_listed_days),
		large_code=large_code.strip(),
		small_code=small_code.strip() if small_code and small_code.strip() else None,
	)
	signals = micro_compute_signals(index, factors, style_gap, params)
	metrics_raw, returns_df, variants = summarize(index, signals, params, start_date, end_date)
	cumulative_raw = (1.0 + returns_df).cumprod()

	output_dir.mkdir(parents=True, exist_ok=True)
	index.to_csv(output_dir / "micro_cap_index.csv", encoding="utf-8-sig")
	signals.assign(position=variants["MA15+底部+顶部"]).to_csv(output_dir / "signals.csv", encoding="utf-8-sig")
	metrics_raw.to_csv(output_dir / "performance_metrics.csv", encoding="utf-8-sig")
	cumulative_raw.to_csv(output_dir / "cumulative_returns.csv", encoding="utf-8-sig")

	reloaded = load_micro_cap_timing_results(output_dir)
	assert reloaded is not None
	return reloaded


# ---------------------------------------------------------------------------
# 4. 量稳换手率选股策略 (TurnoverStability)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TurnoverStabilityFrames:
	"""量稳换手率选股策略（STR / SCR）结果表集合。"""

	metrics: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	factor_summary: pd.DataFrame
	decile_annual: pd.DataFrame
	group_dispersion: pd.DataFrame
	index_universe_summary: pd.DataFrame
	yearly_scr: pd.DataFrame
	yearly_str: pd.DataFrame
	yearly_pure_scr: pd.DataFrame
	param_sensitivity_is: pd.DataFrame
	param_sensitivity_oos: pd.DataFrame
	latest_top: pd.DataFrame
	metadata: dict = field(default_factory=dict)


def load_turnover_stability_results(
	output_dir: Path = DEFAULT_TURNOVER_STABILITY_DIR,
) -> TurnoverStabilityFrames | None:
	"""加载已保存的量稳换手率选股策略结果。"""
	metrics_path = output_dir / "performance_metrics.csv"
	cumulative_path = output_dir / "cumulative_returns.csv"
	if not metrics_path.exists() or not cumulative_path.exists():
		return None

	metrics = _read_csv_safe(metrics_path)
	cumulative = _normalize_date_frame(_read_csv_safe(cumulative_path))
	drawdown = _drawdown_frame_from_nav(cumulative)

	if not metrics.empty and not set(SCORE_COLUMNS).issubset(metrics.columns) and "组合" in metrics.columns:
		# 为与累计净值曲线对应的全区间行补算统一评分。
		full_labels = {label for label in metrics.get("区间", pd.Series(dtype=str)).dropna() if "全区间" in str(label)}
		rows = []
		for row in metrics.to_dict("records"):
			name = str(row.get("组合", ""))
			period = str(row.get("区间", ""))
			if name in cumulative.columns and (not full_labels or period in full_labels):
				row.update(evaluate_returns(_returns_from_nav_series(cumulative[name]), 252).scoring)
			else:
				row.update(evaluate_returns([], 252).scoring)
			rows.append(row)
		metrics = pd.DataFrame(rows)

	summary_path = output_dir / "summary.json"
	metadata = {}
	if summary_path.exists():
		try:
			metadata = json.loads(summary_path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			metadata = {}

	return TurnoverStabilityFrames(
		metrics=metrics,
		cumulative=cumulative,
		drawdown=drawdown,
		factor_summary=_read_csv_safe(output_dir / "factor_summary.csv"),
		decile_annual=_read_csv_safe(output_dir / "decile_annual_returns.csv"),
		group_dispersion=_read_csv_safe(output_dir / "group_dispersion.csv"),
		index_universe_summary=_read_csv_safe(output_dir / "index_universe_summary.csv"),
		yearly_scr=_read_csv_safe(output_dir / "yearly_scr.csv"),
		yearly_str=_read_csv_safe(output_dir / "yearly_str.csv"),
		yearly_pure_scr=_read_csv_safe(output_dir / "yearly_pure_scr.csv"),
		param_sensitivity_is=_read_csv_safe(output_dir / "param_sensitivity_is.csv"),
		param_sensitivity_oos=_read_csv_safe(output_dir / "param_sensitivity_oos.csv"),
		latest_top=_read_csv_safe(output_dir / "latest_scr_top50.csv"),
		metadata=metadata,
	)


def run_turnover_stability_backtest(
	*,
	data_start: str = "2012-10-01",
	start_date: str = "2013-01-01",
	end_date: str = "2026-10-30",
	k_window: int = 20,
	x_window: int = 40,
	min_listed_days: int = 120,
	top_fraction: float = 0.10,
	top_n: int = 50,
	include_index_universes: bool = False,
	include_param_grid: bool = False,
	output_dir: Path = DEFAULT_TURNOVER_STABILITY_DIR,
) -> TurnoverStabilityFrames:
	"""基于本地缓存重跑量稳换手率选股策略（STR / SCR）。"""
	from examples.turnover_stability import (
		IN_SAMPLE_END,
		IN_SAMPLE_START,
		OOS_END,
		OOS_START,
		index_constituents_asof,
		load_benchmark_returns,
		load_index_weights,
		load_market_panels,
		load_reference,
		run_param_sensitivity,
		run_universe_factors,
		slice_factor_summary,
	)

	params = TurnoverStabilityParams(
		k_window=int(k_window),
		x_window=int(x_window),
		min_listed_days=int(min_listed_days),
		top_fraction=float(top_fraction),
		top_n=int(top_n),
	)
	output_dir.mkdir(parents=True, exist_ok=True)
	panels = load_market_panels(data_start)
	list_date, members = load_reference()
	trading_days = panels["returns"].index
	bench_ret = load_benchmark_returns(trading_days)

	signal_start = (pd.Timestamp(start_date) - pd.DateOffset(months=1)).strftime("%Y-%m-01")
	rebalance_days = turnover_month_end_dates(trading_days, signal_start, end_date)
	all_a_factors = run_universe_factors(
		rebalance_days,
		panels,
		list_date,
		members,
		params,
		include_pure_scr=True,
	)

	periods = (
		(f"全区间({start_date[:4]}-{end_date[:4]})", start_date, end_date),
		("研报重叠(2013-2021.10)", IN_SAMPLE_START, IN_SAMPLE_END),
		("发表后样本外(2021.11-2026.10)", OOS_START, OOS_END),
	)
	all_a_evals: dict[str, dict[str, object]] = {}
	factor_rows: list[dict[str, object]] = []
	decile_ann_rows: dict[str, dict[str, float]] = {}
	dispersion_rows: dict[str, pd.Series] = {}

	for name in TURNOVER_ALL_FACTORS:
		ev = turnover_evaluate_factor_monthly(all_a_factors[name], panels["returns"], deciles=params.deciles, commission=0.0)
		all_a_evals[name] = ev
		for period_name, p_start, p_end in periods:
			factor_rows.append({"因子": name, "区间": period_name, **slice_factor_summary(ev, p_start, p_end)})
		dm_full = ev["decile_monthly"].loc[start_date:end_date]
		decile_ann_rows[name] = {
			f"G{g}": turnover_performance(dm_full[f"G{g}"].dropna(), periods=12)["年化收益"]
			for g in range(1, params.deciles + 1)
		}
		dispersion_rows[name] = ev["group_dispersion"]

	long_targets: dict[str, dict[pd.Timestamp, pd.Series]] = {
		"全A_Turn20_Top10%": {},
		"全A_STR_Top10%": {},
		"全A_SCR_Top10%": {},
		"全A_PureSCR_Top10%": {},
		"全A_STR_Top50": {},
		"全A_SCR_Top50": {},
		"全A_PureSCR_Top50": {},
	}
	for day in rebalance_days:
		for fac, label in (
			("turn20", "全A_Turn20_Top10%"),
			("str", "全A_STR_Top10%"),
			("scr", "全A_SCR_Top10%"),
			("pure_scr", "全A_PureSCR_Top10%"),
		):
			if day in all_a_factors[fac]:
				long_targets[label][day] = turnover_select_equal_weight(all_a_factors[fac][day], top_fraction=params.top_fraction)
		for fac, label in (
			("str", "全A_STR_Top50"),
			("scr", "全A_SCR_Top50"),
			("pure_scr", "全A_PureSCR_Top50"),
		):
			if day in all_a_factors[fac]:
				long_targets[label][day] = turnover_select_equal_weight(all_a_factors[fac][day], top_n=params.top_n)

	long_bt = {
		name: turnover_backtest_weights(panels["returns"], tgt, commission=params.commission)
		for name, tgt in long_targets.items()
	}
	long_daily = pd.DataFrame({name: r["return"] for name, r in long_bt.items()}).loc[start_date:end_date]
	long_daily = long_daily.join(bench_ret.reindex(long_daily.index))

	perf_rows: list[dict[str, object]] = []
	for period_name, p_start, p_end in periods:
		sub = long_daily.loc[p_start:p_end]
		for col in sub.columns:
			metrics_row = summarize_research_returns(sub[col].dropna())
			turn = np.nan
			if col in long_bt:
				t_s = long_bt[col]["turnover"].loc[p_start:p_end]
				pos = t_s[t_s > 0]
				turn = float(pos.mean() / 2.0) if not pos.empty else 0.0
			perf_rows.append({"组合": col, "区间": period_name, **metrics_row, "月均单边换手": turn})

	index_summary_rows: list[dict[str, object]] = []
	if include_index_universes:
		for idx_label, idx_code in (("沪深300", "000300.SH"), ("中证500", "000905.SH")):
			w_df = load_index_weights(idx_code)
			u_factors = run_universe_factors(
				rebalance_days,
				panels,
				list_date,
				members,
				params,
				universe_fn=lambda d, w=w_df: index_constituents_asof(w, d),
				include_pure_scr=False,
			)
			for fac in ("turn20", "str", "scr"):
				ev = turnover_evaluate_factor_monthly(u_factors[fac], panels["returns"], deciles=params.deciles, commission=0.0)
				for period_name, p_start, p_end in periods:
					index_summary_rows.append(
						{"样本空间": idx_label, "因子": fac, "区间": period_name, **slice_factor_summary(ev, p_start, p_end)}
					)

	param_is_df, param_oos_df = (
		run_param_sensitivity(rebalance_days, panels, list_date, params)
		if include_param_grid
		else (pd.DataFrame(), pd.DataFrame())
	)

	pd.DataFrame(factor_rows).to_csv(output_dir / "factor_summary.csv", index=False, encoding="utf-8-sig")
	pd.DataFrame(perf_rows).to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
	pd.DataFrame(decile_ann_rows).T.to_csv(output_dir / "decile_annual_returns.csv", encoding="utf-8-sig")
	pd.DataFrame(dispersion_rows).T.to_csv(output_dir / "group_dispersion.csv", encoding="utf-8-sig")
	turnover_yearly_factor_table(all_a_evals["str"]["decile_monthly"].loc[start_date:end_date]).to_csv(
		output_dir / "yearly_str.csv", encoding="utf-8-sig"
	)
	turnover_yearly_factor_table(all_a_evals["scr"]["decile_monthly"].loc[start_date:end_date]).to_csv(
		output_dir / "yearly_scr.csv", encoding="utf-8-sig"
	)
	turnover_yearly_factor_table(all_a_evals["pure_scr"]["decile_monthly"].loc[start_date:end_date]).to_csv(
		output_dir / "yearly_pure_scr.csv", encoding="utf-8-sig"
	)
	(1.0 + long_daily.fillna(0.0)).cumprod().to_csv(output_dir / "cumulative_returns.csv", encoding="utf-8-sig")
	if index_summary_rows:
		pd.DataFrame(index_summary_rows).to_csv(output_dir / "index_universe_summary.csv", index=False, encoding="utf-8-sig")
	if not param_is_df.empty:
		param_is_df.to_csv(output_dir / "param_sensitivity_is.csv", encoding="utf-8-sig")
		param_oos_df.to_csv(output_dir / "param_sensitivity_oos.csv", encoding="utf-8-sig")

	latest_day = max(all_a_factors["scr"])
	latest_scr = all_a_factors["scr"][latest_day].sort_values(ascending=True).head(params.top_n)
	latest_scr.rename("scr_zscore").to_csv(output_dir / "latest_scr_top50.csv", encoding="utf-8-sig")

	summary_payload = {
		"data_range": {"start": str(trading_days[0].date()), "end": str(trading_days[-1].date())},
		"rebalance_months": len(rebalance_days),
		"commission": params.commission,
		"k_window": params.k_window,
		"x_window": params.x_window,
		"latest_signal_date": str(latest_day.date()),
	}
	(output_dir / "summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

	reloaded = load_turnover_stability_results(output_dir)
	assert reloaded is not None
	return reloaded


# ---------------------------------------------------------------------------
# 5. 高频价量 46 因子中证 500 策略 (IntradayAllFactor)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntradayAllFactorFrames:
	"""高频价量 46 因子中证 500 周频回测结果表集合。"""

	result_dir: Path
	metrics: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	nav_detail: pd.DataFrame
	latest_selection: pd.DataFrame
	latest_holdings: pd.DataFrame
	trades: pd.DataFrame
	targets: pd.DataFrame
	directions: pd.DataFrame
	factor_summary: pd.DataFrame
	raw_metrics: dict = field(default_factory=dict)


def discover_intraday_result_dirs(root: Path = DEFAULT_INTRADAY_ROOT) -> list[Path]:
	"""按优先级发现高频 46 因子回测输出目录（优先含完整 metrics.json 的最新刷新目录）。"""
	if not root.exists():
		return []
	candidates: list[tuple[int, str, Path]] = []
	refresh_dirs = sorted(root.glob("refresh_*/backtest"), reverse=True)
	for path in refresh_dirs:
		if (path / "nav.csv").exists():
			priority = 0 if (path / "metrics.json").exists() else 1
			candidates.append((priority, path.parent.name, path))
	default_bt = root / "all_factor_backtest"
	if (default_bt / "nav.csv").exists():
		priority = 0 if (default_bt / "metrics.json").exists() else 2
		candidates.append((priority, "all_factor_backtest", default_bt))
	candidates.sort(key=lambda item: (item[0], item[1]))
	return [item[2] for item in candidates]


def load_intraday_all_factor_results(output_dir: Path | None = None) -> IntradayAllFactorFrames | None:
	"""加载高频 46 因子回测目录的指标、净值、持仓与选股明细。"""
	target_dir = output_dir
	if target_dir is None:
		dirs = discover_intraday_result_dirs()
		if not dirs:
			return None
		target_dir = dirs[0]

	nav_path = target_dir / "nav.csv"
	if not nav_path.exists():
		return None

	nav_detail = _normalize_date_frame(_read_csv_safe(nav_path))
	cumulative = pd.DataFrame({"Date": nav_detail["Date"]})
	if "nav" in nav_detail.columns:
		cumulative["46因子策略"] = pd.to_numeric(nav_detail["nav"], errors="coerce")
	if "benchmark_nav" in nav_detail.columns:
		cumulative["中证500基准"] = pd.to_numeric(nav_detail["benchmark_nav"], errors="coerce")
	if "relative_nav" in nav_detail.columns:
		cumulative["相对净值"] = pd.to_numeric(nav_detail["relative_nav"], errors="coerce")
	drawdown = _drawdown_frame_from_nav(cumulative[[c for c in ("Date", "46因子策略", "中证500基准") if c in cumulative.columns]])

	raw_metrics: dict = {}
	metrics_path = target_dir / "metrics.json"
	if metrics_path.exists():
		try:
			raw_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			raw_metrics = {}

	rows = []
	for label, col in (("46因子策略", "46因子策略"), ("中证500基准", "中证500基准")):
		if col not in cumulative.columns:
			continue
		row = {"策略": label} | summarize_research_returns(_returns_from_nav_series(cumulative[col]))
		if label == "46因子策略" and raw_metrics:
			row["调仓次数"] = raw_metrics.get("rebalance_count")
			row["累计佣金"] = raw_metrics.get("total_commission")
			row["最新信号日"] = raw_metrics.get("latest_signal_date")
		rows.append(row)
	metrics = pd.DataFrame(rows)

	sibling_factor_summary = target_dir.parent / "factor_research" / "factor_summary.csv"
	return IntradayAllFactorFrames(
		result_dir=target_dir,
		metrics=metrics,
		cumulative=cumulative,
		drawdown=drawdown,
		nav_detail=nav_detail,
		latest_selection=_read_csv_safe(target_dir / "latest_selection.csv"),
		latest_holdings=_read_csv_safe(target_dir / "latest_holdings.csv"),
		trades=_read_csv_safe(target_dir / "trades.csv"),
		targets=_read_csv_safe(target_dir / "targets.csv"),
		directions=_read_csv_safe(target_dir / "directions.csv"),
		factor_summary=_read_csv_safe(sibling_factor_summary),
		raw_metrics=raw_metrics,
	)


def run_intraday_all_factor_backtest(
	*,
	output_dir: Path = DEFAULT_INTRADAY_ROOT / "all_factor_backtest",
	factor_dir: Path = Path("data/intraday_factors/local_minute_factors"),
	auction_dir: Path = Path("data/intraday_factors/auction_history/daily"),
	coverage: Path = DEFAULT_INTRADAY_ROOT / "auction_history/coverage.duckdb",
	history: Path = DEFAULT_INTRADAY_ROOT / "local_minute_research/weekly_research.csv",
	snapshots: Path = Path("data/intraday_factors/csi500/snapshots.duckdb"),
	reference_dir: Path = Path("data/micro_cap_timing_plus"),
) -> IntradayAllFactorFrames:
	"""调用 46 因子周频研究回测脚本重新生成结果。"""
	from examples import intraday_all_factor_backtest

	argv = [
		"intraday_all_factor_backtest",
		"--factor-dir", str(factor_dir),
		"--auction-dir", str(auction_dir),
		"--coverage", str(coverage),
		"--history", str(history),
		"--output-dir", str(output_dir),
		"--snapshots", str(snapshots),
		"--reference-dir", str(reference_dir),
	]
	with patch.object(sys, "argv", argv):
		intraday_all_factor_backtest.main()
	reloaded = load_intraday_all_factor_results(output_dir)
	if reloaded is None:
		raise RuntimeError(f"回测完成后未在 {output_dir} 找到 nav.csv")
	return reloaded


# ---------------------------------------------------------------------------
# 6. 指数择时策略 MA / SMA / RSRS (IndexTiming)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexTimingFrames:
	"""指数择时策略（华泰 MA/SMA 与光大 RSRS）结果集合。"""

	periods: dict[str, dict[str, pd.DataFrame]]
	metadata: dict = field(default_factory=dict)


def _threshold_position(score: pd.Series, buy_above: float, sell_below: float) -> pd.Series:
	orders = pd.Series(np.nan, index=score.index)
	orders.loc[score > buy_above] = 1.0
	orders.loc[score < sell_below] = 0.0
	return orders.ffill().fillna(0.0)


def _build_index_timing_signals(
	bars: pd.DataFrame,
	*,
	ma_window: int = 20,
	fast_ma: int = 10,
	rsrs_window: int = 18,
	zscore_window: int = 600,
	slope_buy: float = 1.0,
	slope_sell: float = 0.8,
	zscore_buy: float = 0.7,
	zscore_sell: float = -0.7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
	close = bars["close"]
	ma_slow = close.rolling(ma_window).mean()
	ma_fast = close.rolling(fast_ma).mean()
	low_window = bars["low"].rolling(rsrs_window)
	beta = low_window.cov(bars["high"]).div(low_window.var().replace(0, np.nan))
	past_beta = beta.shift(1).rolling(zscore_window, min_periods=2)
	zscore = (beta - past_beta.mean()).div(past_beta.std().replace(0, np.nan))

	indicators = pd.DataFrame(
		{
			"MA": close - ma_slow,
			"SMA_Cross": ma_fast - ma_slow,
			"RSRS_slope": beta,
			"RSRS_zscore": zscore,
		}
	)
	targets = pd.DataFrame(
		{
			"MA": _threshold_position(indicators["MA"], 0.0, 0.0),
			"SMA_Cross": _threshold_position(indicators["SMA_Cross"], 0.0, 0.0),
			"RSRS_slope": _threshold_position(beta, slope_buy, slope_sell),
			"RSRS_zscore": _threshold_position(zscore, zscore_buy, zscore_sell),
			"buy_hold": 1.0,
		},
		index=bars.index,
	)
	return indicators, targets


def _backtest_index_period(bars: pd.DataFrame, targets: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
	position = targets.shift(1, fill_value=0.0).loc[start:end]
	previous_position = position.shift(1, fill_value=0.0)
	sample = bars.loc[start:end]
	execution_price = sample["open"].fillna(sample["close"])
	before_execution = (execution_price / sample["close"].shift(1) - 1.0).fillna(0.0)
	after_execution = sample["close"] / execution_price - 1.0
	returns = (
		(1.0 + previous_position.mul(before_execution, axis=0))
		* (1.0 + position.mul(after_execution, axis=0))
		- 1.0
	)
	return returns, position


def load_index_timing_results(output_dir: Path = DEFAULT_INDEX_TIMING_DIR) -> IndexTimingFrames | None:
	"""加载 data/index_timing_replication 下已生成的指数择时复现结果。"""
	summary_path = output_dir / "summary.json"
	daily_path = output_dir / "daily.duckdb"
	if not summary_path.exists() or not frame_exists(daily_path):
		return None

	summary = json.loads(summary_path.read_text(encoding="utf-8"))
	daily = read_frame(daily_path)
	periods_map: dict[str, dict[str, pd.DataFrame]] = {}

	for period_name, info in summary.get("periods", {}).items():
		strategies = info.get("strategies", {})
		metrics_rows = [{"策略": name, **vals} for name, vals in strategies.items()]
		metrics_df = pd.DataFrame(metrics_rows)

		sub = daily[daily["period"] == period_name].copy() if "period" in daily.columns else pd.DataFrame()
		nav_cols = [col for col in sub.columns if col.startswith("nav_")]
		cumulative = pd.DataFrame()
		if not sub.empty and nav_cols:
			sub = _normalize_date_frame(sub)
			cumulative = pd.DataFrame({"Date": sub["Date"]})
			for col in nav_cols:
				clean_name = col.removeprefix("nav_")
				series = pd.to_numeric(sub[col], errors="coerce")
				if series.notna().any():
					cumulative[clean_name] = series
		drawdown = _drawdown_frame_from_nav(cumulative)
		periods_map[period_name] = {
			"metrics": metrics_df,
			"cumulative": cumulative,
			"drawdown": drawdown,
			"daily": sub,
		}

	return IndexTimingFrames(periods=periods_map, metadata=summary.get("data", {}))


def run_index_timing_backtest(
	*,
	symbol: str = "000300.SH",
	start_date: str = "2020-01-01",
	end_date: str = "2025-12-31",
	ma_window: int = 20,
	fast_ma: int = 10,
	rsrs_window: int = 18,
	zscore_window: int = 600,
	slope_buy: float = 1.0,
	slope_sell: float = 0.8,
	zscore_buy: float = 0.7,
	zscore_sell: float = -0.7,
	output_dir: Path = DEFAULT_INDEX_TIMING_DIR,
	bars: pd.DataFrame | None = None,
	data_source_params: DataSourceParams | None = None,
) -> IndexTimingFrames:
	"""运行可参数化的指数择时（MA / SMA_Cross / RSRS_slope / RSRS_zscore）回测。"""
	if bars is None:
		# 预留 zscore 暖身历史，优先读取本地 DataHub DuckDB 缓存。
		warmup_start = (pd.Timestamp(start_date) - pd.DateOffset(years=4)).strftime("%Y-%m-%d")
		request = DataRequest(
			symbols=(symbol,),
			start=warmup_start,
			end=end_date,
			frequency="1d",
			adjust="none",
			fields=("ts_code", "trade_date", "open", "high", "low", "close"),
		)
		token = _ensure_tushare_token(data_source_params.tushare_token if data_source_params else "")
		if token:
			os.environ.setdefault("TUSHARE_TOKEN", token)
		service = create_service(repository=DuckDBRepository(output_dir / "cache"))
		try:
			raw = service.get_cached(DataKind.INDEX_DAILY, request, source="tushare")
			if raw is None or raw.empty:
				# 兼容复现脚本已缓存的全区间 (2002-01-01 ~ 2025-12-31)
				full_req = DataRequest(
					symbols=(symbol,),
					start="2002-01-01",
					end="2025-12-31",
					frequency="1d",
					adjust="none",
					fields=("ts_code", "trade_date", "open", "high", "low", "close"),
				)
				raw = service.get_cached(DataKind.INDEX_DAILY, full_req, source="tushare")
			if raw is None or raw.empty:
				raw = service.get(DataKind.INDEX_DAILY, request, persist=True)
		finally:
			service.close()
		if raw is None or raw.empty:
			raise RuntimeError(f"未获取到指数 {symbol} 日线行情")
		dates = pd.to_datetime(raw["trade_date"])
		bars = raw.set_index(dates.rename("date"))[["open", "high", "low", "close"]].sort_index()
		bars = bars.loc[~bars.index.duplicated(keep="last")]
		metadata = {
			"symbol": symbol,
			"source": raw.attrs.get("source", "tushare"),
			"data_start": str(bars.index[0].date()),
			"data_end": str(bars.index[-1].date()),
			"bars": len(bars),
		}
	else:
		bars = bars.sort_index()
		metadata = {
			"symbol": symbol,
			"source": "injected",
			"data_start": str(bars.index[0].date()),
			"data_end": str(bars.index[-1].date()),
			"bars": len(bars),
		}

	indicators, targets = _build_index_timing_signals(
		bars,
		ma_window=int(ma_window),
		fast_ma=int(fast_ma),
		rsrs_window=int(rsrs_window),
		zscore_window=int(zscore_window),
		slope_buy=float(slope_buy),
		slope_sell=float(slope_sell),
		zscore_buy=float(zscore_buy),
		zscore_sell=float(zscore_sell),
	)
	returns, position = _backtest_index_period(bars, targets, start_date, end_date)
	if returns.empty:
		raise ValueError(f"区间 {start_date} ~ {end_date} 无有效行情数据")

	nav = (1.0 + returns).cumprod()
	date_labels = pd.to_datetime(nav.index).strftime("%Y-%m-%d")
	cumulative = pd.DataFrame({"Date": date_labels, **{col: nav[col].values for col in nav.columns}})
	drawdown = _drawdown_frame_from_nav(cumulative)

	metric_rows = []
	for col in returns.columns:
		ev = evaluate_returns(returns[col])
		metric_rows.append(
			{"策略": col}
			| ev.metrics
			| ev.scoring
			| {
				"entries": int(position[col].diff().fillna(position[col]).gt(0).sum()),
				"exits": int(position[col].diff().lt(0).sum()),
				"invested_fraction": float(position[col].mean()),
			}
		)
	metrics_df = pd.DataFrame(metric_rows)
	daily_detail = pd.concat(
		[
			bars.reindex(returns.index),
			indicators.reindex(returns.index).add_prefix("indicator_"),
			position.add_prefix("position_"),
			nav.add_prefix("nav_"),
		],
		axis=1,
	).reset_index()
	daily_detail = _normalize_date_frame(daily_detail)

	period_key = f"custom({start_date}~{end_date})"
	return IndexTimingFrames(
		periods={
			period_key: {
				"metrics": metrics_df,
				"cumulative": cumulative,
				"drawdown": drawdown,
				"daily": daily_detail,
			}
		},
		metadata=metadata,
	)
