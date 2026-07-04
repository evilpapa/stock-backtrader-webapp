"""
行业动量轮动策略回测脚本

使用:
    uv run python examples/sector_rotation/backtest_sector_rotation.py
"""

from __future__ import annotations

import runpy
from pathlib import Path
from datetime import datetime, timedelta
from tabulate import tabulate

_bootstrap = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bootstrap.py"))
project_root = _bootstrap["project_root"]
project_path = _bootstrap["project_path"]

from charts import configure_matplotlib_chinese_font
from examples.rotation_backtest_common import (
	align_series,
	build_cumulative_frame,
	build_drawdown_frame,
	build_metrics,
	build_rebalance_detail_frame,
	build_return_series,
	build_returns_frame,
	build_selection_frequency_frame,
	build_weight_frame,
	format_metrics_for_console,
	plot_compare,
	plot_weights,
	prepare_price_data,
	run_benchmark_backtest,
	run_equal_weight_backtest,
	run_rotation_strategy_backtest,
	save_results,
)
from strategy.sector_rotation import SectorRotationStrategy
configure_matplotlib_chinese_font()

INITIAL_CASH = 100000.0
MOMENTUM_WINDOW = 20
BACKTEST_START = "2026-01-01"
BACKTEST_END = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
REBALANCE_DAYS = 5
TOP_L = 5
BENCHMARK_SYMBOL = "588000"
BENCHMARK_NAME = "科创50ETF"
STRATEGY_NAME = "行业动量轮动策略"
EQUAL_WEIGHT_NAME = "行业等权重组合"
OUTPUT_DIR = project_path("examples", "sector_rotation", "backtest_results")
DATA_CACHE_NAME = "sector_rotation"
ASSET_LABEL = "ETF"

ETF_SYMBOLS = [
	"159819", "588000", "512690", "159813",
	"159526", "515650", "159869", "159740",
	"159992", "159755", "515290", "512200",
	"159766",
]
ETF_NAMES = [
	"人工智能ETF", "科创50ETF", "军工ETF", "半导体ETF",
	"机器人ETF嘉实", "消费50ETF", "游戏ETF", "恒生科技ETF",
	"创新药ETF", "电池ETF", "银行ETF易方达", "房地产ETF",
	"旅游ETF",
]
COLORS = {
	STRATEGY_NAME: "#E41A1C",
	BENCHMARK_NAME: "#377EB8",
	EQUAL_WEIGHT_NAME: "#4DAF4A",
}


def main() -> None:
	print("=" * 60)
	print("行业动量轮动策略回测 (Python版本)")
	print("=" * 60)
	print(f"回测期间: {BACKTEST_START} 至 {BACKTEST_END}")
	print(f"行业ETF数量: {len(ETF_SYMBOLS)}")
	print(f"参数: N={MOMENTUM_WINDOW}, K={REBALANCE_DAYS}, L={TOP_L}")
	print(f"初始资金: {INITIAL_CASH:,.0f} 元")
	print("=" * 60)

	price_data = prepare_price_data(ETF_SYMBOLS, BACKTEST_START, BACKTEST_END, DATA_CACHE_NAME)
	if BENCHMARK_SYMBOL not in price_data:
		raise RuntimeError(f"缺少基准数据: {BENCHMARK_SYMBOL}")

	strategy_result = run_rotation_strategy_backtest(
		price_data,
		ETF_SYMBOLS,
		ETF_NAMES,
		BENCHMARK_NAME,
		SectorRotationStrategy,
		STRATEGY_NAME,
		INITIAL_CASH,
		MOMENTUM_WINDOW,
		REBALANCE_DAYS,
		TOP_L,
	)
	benchmark_result = run_benchmark_backtest(
		price_data,
		BENCHMARK_SYMBOL,
		BENCHMARK_NAME,
		INITIAL_CASH,
	)
	equal_result = run_equal_weight_backtest(
		price_data,
		ETF_SYMBOLS,
		ETF_NAMES,
		INITIAL_CASH,
		EQUAL_WEIGHT_NAME,
		exclude_names={BENCHMARK_NAME},
	)

	strategy_returns = build_return_series(strategy_result)
	benchmark_returns = build_return_series(benchmark_result)
	equal_returns = build_return_series(equal_result)
	strategy_returns, benchmark_returns, equal_returns = align_series(
		strategy_returns,
		benchmark_returns,
		equal_returns,
	)

	metrics_df = build_metrics(
		strategy_returns,
		benchmark_returns,
		equal_returns,
		STRATEGY_NAME,
		BENCHMARK_NAME,
		EQUAL_WEIGHT_NAME,
	)
	console_metrics = format_metrics_for_console(metrics_df)
	returns_df = build_returns_frame(
		strategy_returns,
		benchmark_returns,
		equal_returns,
		STRATEGY_NAME,
		BENCHMARK_NAME,
		EQUAL_WEIGHT_NAME,
	)
	cumulative_df = build_cumulative_frame(
		strategy_returns,
		benchmark_returns,
		equal_returns,
		STRATEGY_NAME,
		BENCHMARK_NAME,
		EQUAL_WEIGHT_NAME,
	)
	drawdown_df = build_drawdown_frame(
		strategy_returns,
		benchmark_returns,
		equal_returns,
		STRATEGY_NAME,
		BENCHMARK_NAME,
		EQUAL_WEIGHT_NAME,
	)
	weights_df = build_weight_frame(strategy_result)
	selection_frequency_df = build_selection_frequency_frame(strategy_result, ASSET_LABEL)
	rebalance_detail_df = build_rebalance_detail_frame(strategy_result, ASSET_LABEL)

	save_results(
		OUTPUT_DIR,
		metrics_df,
		returns_df,
		cumulative_df,
		drawdown_df,
		weights_df,
		selection_frequency_df,
		rebalance_detail_df,
	)
	plot_compare(STRATEGY_NAME, BENCHMARK_NAME, cumulative_df, drawdown_df, COLORS, OUTPUT_DIR, "sector_vs_benchmark.png")
	plot_compare(STRATEGY_NAME, EQUAL_WEIGHT_NAME, cumulative_df, drawdown_df, COLORS, OUTPUT_DIR, "sector_vs_equal_weight.png")
	plot_weights(weights_df, STRATEGY_NAME, OUTPUT_DIR)

	print("\n" + "=" * 60)
	print("效能指标汇总")
	print("=" * 60)
	print(tabulate(console_metrics, headers='keys', tablefmt='grid', showindex=False))
	print(f"\n结果已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
	main()
