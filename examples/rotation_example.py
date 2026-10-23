"""轮动策略示例的共享命令行入口。"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from tabulate import tabulate

from examples.backtest_common import format_metrics_for_console, plot_compare, plot_weights
from src.charts import configure_matplotlib_chinese_font
from src.constants import (
	BENCHMARK_COLOR,
	DEFAULT_MOMENTUM_WINDOW,
	DEFAULT_REBALANCE_DAYS,
	DEFAULT_TOP_L,
	EQUAL_WEIGHT_COLOR,
	INITIAL_CASH,
	STRATEGY_COLOR,
	default_backtest_end,
)
from src.risk import RiskConfig
from src.risk.cli import add_risk_arguments, risk_config_from_args
from src.utils.rotation_backtest import ROTATION_SPECS, run_rotation_backtest


def parse_risk_config(argv: Sequence[str] | None = None) -> RiskConfig:
	"""解析风控相关命令行参数，忽略其他脚本参数。"""
	parser = argparse.ArgumentParser(add_help=False, description="轮动策略风控参数")
	add_risk_arguments(parser)
	args, _ = parser.parse_known_args(argv)
	return risk_config_from_args(args)


def main(key: str, filename_prefix: str) -> None:
	"""运行指定的轮动策略示例并输出图表和汇总。"""
	spec = replace(ROTATION_SPECS[key], output_dir=Path(__file__).parent / f"{filename_prefix}_rotation")
	end_date = default_backtest_end()
	risk_config = parse_risk_config()
	configure_matplotlib_chinese_font()
	print(f"\n{'=' * 60}\n{spec.strategy_name}回测\n{'=' * 60}")
	print(f"回测期间: {spec.default_start_date} 至 {end_date}")
	total_assets = len(spec.assets) + (spec.benchmark_symbol not in {asset["symbol"] for asset in spec.assets})
	print(f"标的数量: {total_assets}（含基准），参数: N={DEFAULT_MOMENTUM_WINDOW}, K={DEFAULT_REBALANCE_DAYS}, L={DEFAULT_TOP_L}")

	frames = run_rotation_backtest(
		spec, spec.assets, spec.benchmark_symbol, spec.benchmark_name,
		spec.default_start_date, end_date, INITIAL_CASH,
		DEFAULT_MOMENTUM_WINDOW, DEFAULT_REBALANCE_DAYS, DEFAULT_TOP_L,
		risk_config=risk_config,
	)
	colors = {
		spec.strategy_name: STRATEGY_COLOR,
		spec.benchmark_name: BENCHMARK_COLOR,
		spec.equal_weight_name: EQUAL_WEIGHT_COLOR,
	}
	plot_compare(
		spec.strategy_name, spec.benchmark_name, frames.cumulative, frames.drawdown,
		colors, spec.output_dir, f"{filename_prefix}_vs_benchmark.png",
	)
	plot_compare(
		spec.strategy_name, spec.equal_weight_name, frames.cumulative, frames.drawdown,
		colors, spec.output_dir, f"{filename_prefix}_vs_equal_weight.png",
	)
	plot_weights(frames.weights, spec.strategy_name, spec.output_dir)
	print(tabulate(format_metrics_for_console(frames.metrics), headers="keys", tablefmt="grid", showindex=False))
	if frames.risk_summary is not None and not frames.risk_summary.empty:
		print("\n风控统计:")
		print(
			tabulate(
				frames.risk_summary.values.tolist(),
				headers=list(frames.risk_summary.columns),
				tablefmt="grid",
				showindex=False,
			)
		)
	print(f"\n结果已保存到: {spec.output_dir}")
