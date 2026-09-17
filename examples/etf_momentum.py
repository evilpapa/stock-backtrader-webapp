"""ETF 动量策略回测。

运行：``uv run python examples/etf_momentum.py``
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.backtest_common import format_metrics_for_console, plot_compare, plot_weights
from src.charts import configure_matplotlib_chinese_font
from src._constants import (
	BENCHMARK_COLOR, DEFAULT_MOMENTUM_WINDOW, DEFAULT_REBALANCE_DAYS,
	EQUAL_WEIGHT_COLOR, INITIAL_CASH, STRATEGY_COLOR, default_backtest_end,
)
from src.utils.etf_momentum_backtest import (
	BENCHMARK_NAME, DEFAULT_ASSETS, DEFAULT_OUTPUT_DIR, EQUAL_WEIGHT_NAME,
	STRATEGY_NAME, run_etf_momentum_backtest,
)
from src.utils.schemas import DataSourceParams


def parse_data_source_params(argv: Sequence[str] | None = None) -> DataSourceParams:
	parser = argparse.ArgumentParser(description="运行 ETF 动量策略回测")
	parser.add_argument("--bigqmt-account-id", default=os.getenv("BIGQMT_ACCOUNT_ID", ""))
	parser.add_argument("--bigqmt-timeout", type=float, default=float(os.getenv("BIGQMT_RPC_TIMEOUT_SECONDS", "10")))
	args = parser.parse_args(argv)
	return DataSourceParams(bigqmt_account_id=args.bigqmt_account_id, bigqmt_timeout=args.bigqmt_timeout)


def main() -> None:
	configure_matplotlib_chinese_font()
	frames = run_etf_momentum_backtest(
		DEFAULT_ASSETS, "510300", BENCHMARK_NAME, "2025-01-01", default_backtest_end(),
		INITIAL_CASH, DEFAULT_MOMENTUM_WINDOW, DEFAULT_REBALANCE_DAYS,
		DEFAULT_OUTPUT_DIR, data_source_params=parse_data_source_params(),
	)
	colors = {STRATEGY_NAME: STRATEGY_COLOR, BENCHMARK_NAME: BENCHMARK_COLOR, EQUAL_WEIGHT_NAME: EQUAL_WEIGHT_COLOR}
	plot_compare(
		STRATEGY_NAME, BENCHMARK_NAME, frames.cumulative, frames.drawdown,
		colors, DEFAULT_OUTPUT_DIR, "momentum_vs_benchmark.png",
	)
	plot_compare(
		STRATEGY_NAME, EQUAL_WEIGHT_NAME, frames.cumulative, frames.drawdown,
		colors, DEFAULT_OUTPUT_DIR, "momentum_vs_equal_weight.png",
	)
	plot_weights(frames.weights, STRATEGY_NAME, DEFAULT_OUTPUT_DIR)
	print(tabulate(format_metrics_for_console(frames.metrics), headers="keys", tablefmt="grid", showindex=False))
	print(f"结果已保存到: {DEFAULT_OUTPUT_DIR}")


if __name__ == "__main__":
	main()
