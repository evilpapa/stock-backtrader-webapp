from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from examples.rotation_backtest_common import (
	align_series,
	build_cumulative_frame,
	build_drawdown_frame,
	build_metrics,
	build_return_series,
	build_returns_frame,
	prepare_price_data,
	run_benchmark_backtest,
	run_equal_weight_backtest,
	run_strategy_backtest,
	save_results,
)
from strategy.etf_momentum import EtfMomentumStrategy


STRATEGY_NAME = "动量策略"
BENCHMARK_NAME = "沪深300ETF"
EQUAL_WEIGHT_NAME = "等权重组合"
DATA_CACHE_NAME = "ETF动量轮动策略"
DEFAULT_OUTPUT_DIR = Path("examples") / "etf_momentum" / "backtest_results"

DEFAULT_ASSETS = [
	{"symbol": "513100", "name": "纳指ETF"},
	{"symbol": "510300", "name": "沪深300ETF"},
	{"symbol": "518880", "name": "黄金ETF"},
	{"symbol": "515000", "name": "科技ETF华宝"},
]


@dataclass(frozen=True)
class EtfMomentumFrames:
	metrics: pd.DataFrame
	returns: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	weights: pd.DataFrame


RESULT_FILES = {
	"metrics": "performance_metrics.csv",
	"returns": "daily_returns.csv",
	"cumulative": "cumulative_returns.csv",
	"drawdown": "drawdowns.csv",
	"weights": "daily_weights.csv",
}


def normalize_assets(assets: pd.DataFrame) -> list[dict[str, str]]:
	normalized = []
	for _, row in assets.iterrows():
		symbol = str(row.get("symbol", "")).strip()
		name = str(row.get("name", "")).strip()
		if symbol and name:
			normalized.append({"symbol": symbol, "name": name})
	return normalized


def load_etf_momentum_results(output_dir: Path = DEFAULT_OUTPUT_DIR) -> EtfMomentumFrames | None:
	if not all((output_dir / filename).exists() for filename in RESULT_FILES.values()):
		return None
	return EtfMomentumFrames(
		metrics=pd.read_csv(output_dir / RESULT_FILES["metrics"], encoding="utf-8-sig"),
		returns=pd.read_csv(output_dir / RESULT_FILES["returns"], encoding="utf-8-sig"),
		cumulative=pd.read_csv(output_dir / RESULT_FILES["cumulative"], encoding="utf-8-sig"),
		drawdown=pd.read_csv(output_dir / RESULT_FILES["drawdown"], encoding="utf-8-sig"),
		weights=pd.read_csv(output_dir / RESULT_FILES["weights"], encoding="utf-8-sig"),
	)


def build_etf_momentum_weight_frame(rebalance_history: list[dict], names: list[str]) -> pd.DataFrame:
	rows = []
	for snapshot in rebalance_history:
		weights = snapshot.get("target_weights", snapshot.get("weights"))
		if weights is None:
			continue
		row = {"Date": snapshot["date"]}
		for index, name in enumerate(names):
			row[name] = float(weights[index]) if index < len(weights) else 0.0
		row["权重合计"] = sum(row[name] for name in names)
		rows.append(row)
	return pd.DataFrame(rows)


def run_etf_momentum_backtest(
	assets: list[dict[str, str]],
	benchmark_symbol: str,
	benchmark_name: str,
	start_date: str,
	end_date: str,
	initial_cash: float,
	momentum_window: int,
	rebalance_days: int,
	output_dir: Path = DEFAULT_OUTPUT_DIR,
	price_data: dict[str, pd.DataFrame] | None = None,
) -> EtfMomentumFrames:
	symbols = [asset["symbol"] for asset in assets]
	names = [asset["name"] for asset in assets]
	if not symbols:
		raise ValueError("ETF Momentum 至少需要一个可交易 ETF 标的")
	if benchmark_symbol not in symbols:
		raise ValueError("基准标的必须包含在 ETF 标的列表中")

	price_data = price_data or prepare_price_data(symbols, start_date, end_date, DATA_CACHE_NAME)
	if benchmark_symbol not in price_data:
		raise RuntimeError(f"缺少基准数据: {benchmark_symbol}")

	available_assets = [
		(asset["symbol"], asset["name"])
		for asset in assets
		if asset["symbol"] in price_data
	]
	if not available_assets:
		raise RuntimeError("ETF Momentum 回测缺少可用 ETF 数据")

	available_symbols = [symbol for symbol, _ in available_assets]
	available_names = [name for _, name in available_assets]
	strategy_result = run_strategy_backtest(
		price_data,
		available_symbols,
		available_names,
		EtfMomentumStrategy,
		STRATEGY_NAME,
		initial_cash,
		{
			"momentum_window": momentum_window,
			"rebalance_days": rebalance_days,
		},
	)
	benchmark_result = run_benchmark_backtest(
		price_data,
		benchmark_symbol,
		benchmark_name,
		initial_cash,
	)
	equal_result = run_equal_weight_backtest(
		price_data,
		available_symbols,
		available_names,
		initial_cash,
		EQUAL_WEIGHT_NAME,
	)

	strategy_returns = build_return_series(strategy_result)
	benchmark_returns = build_return_series(benchmark_result)
	equal_returns = build_return_series(equal_result)
	strategy_returns, benchmark_returns, equal_returns = align_series(
		strategy_returns,
		benchmark_returns,
		equal_returns,
	)

	frames = EtfMomentumFrames(
		metrics=build_metrics(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			STRATEGY_NAME,
			benchmark_name,
			EQUAL_WEIGHT_NAME,
		),
		returns=build_returns_frame(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			STRATEGY_NAME,
			benchmark_name,
			EQUAL_WEIGHT_NAME,
		),
		cumulative=build_cumulative_frame(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			STRATEGY_NAME,
			benchmark_name,
			EQUAL_WEIGHT_NAME,
		),
		drawdown=build_drawdown_frame(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			STRATEGY_NAME,
			benchmark_name,
			EQUAL_WEIGHT_NAME,
		),
		weights=build_etf_momentum_weight_frame(strategy_result.rebalance_history, available_names),
	)
	save_results(
		output_dir,
		frames.metrics,
		frames.returns,
		frames.cumulative,
		frames.drawdown,
		frames.weights,
	)
	return frames
