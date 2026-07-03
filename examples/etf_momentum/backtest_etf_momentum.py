"""
ETF动量轮动策略回测脚本

使用：
	uv run python examples/etf_momentum/backtest_etf_momentum.py
"""

from __future__ import annotations

import runpy
from datetime import datetime, timedelta
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

_bootstrap = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bootstrap.py"))
project_root = _bootstrap["project_root"]
project_path = _bootstrap["project_path"]

from charts import configure_matplotlib_chinese_font
from examples.rotation_backtest_common import (
	align_series,
	build_cumulative_frame,
	build_drawdown_frame,
	build_metrics,
	build_return_series,
	build_returns_frame,
	build_trade_log_weight_frame,
	format_metrics_for_console,
	plot_compare,
	plot_weights,
	prepare_price_data,
	run_benchmark_backtest,
	run_equal_weight_backtest,
	run_strategy_backtest,
	save_results,
)

configure_matplotlib_chinese_font()

INITIAL_CASH = 100000.0
MOMENTUM_WINDOW = 10
REBALANCE_DAYS = 20
BACKTEST_START = "2025-01-01"
BACKTEST_END = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
BENCHMARK_SYMBOL = "510300"
BENCHMARK_NAME = "沪深300ETF"
STRATEGY_NAME = "动量策略"
EQUAL_WEIGHT_NAME = "等权重组合"
OUTPUT_DIR = project_path("examples", "etf_momentum", "backtest_results")
DATA_CACHE_NAME = "ETF动量轮动策略"

ETF_SYMBOLS = ["513100", "510300", "518880"]
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]
COLORS = {
	STRATEGY_NAME: "#E41A1C",
	BENCHMARK_NAME: "#377EB8",
	EQUAL_WEIGHT_NAME: "#4DAF4A",
}


class EtfMomentumStrategy(bt.Strategy):
	"""ETF动量轮动策略。"""

	params = (
		("momentum_window", 20),
		("rebalance_days", 1),
		("printlog", False),
	)

	def __init__(self):
		self.returns = []
		self.momentum = []
		self.volatility = []

		for data in self.datas:
			ret = bt.indicators.PctChange(data.close, period=1)
			self.returns.append(ret)
			self.momentum.append(
				bt.indicators.SimpleMovingAverage(ret, period=self.params.momentum_window)
			)
			self.volatility.append(
				bt.indicators.StandardDeviation(ret, period=self.params.momentum_window)
			)

		self.rebalance_counter = 0
		self.trade_log = []

	def next(self):
		self.rebalance_counter += 1
		if self.rebalance_counter < self.params.rebalance_days:
			return

		self.rebalance_counter = 0

		if len(self.datas[0]) < self.params.momentum_window:
			return

		adj_momentum_values = []
		for index in range(len(self.datas)):
			if len(self.momentum[index]) > 0 and len(self.volatility[index]) > 0:
				momentum = self.momentum[index][0]
				volatility = self.volatility[index][0]
				adj_momentum_values.append(momentum / volatility if volatility > 1e-8 else 0.0)
			else:
				adj_momentum_values.append(0.0)

		positive_indices = [index for index, value in enumerate(adj_momentum_values) if value > 0]
		target_weights = np.zeros(len(self.datas))

		if positive_indices:
			positive_momentum = np.array([adj_momentum_values[index] for index in positive_indices])
			total_momentum = np.sum(positive_momentum)
			if total_momentum > 0:
				normalized_weights = positive_momentum / total_momentum
				for index, weight in zip(positive_indices, normalized_weights):
					target_weights[index] = weight

		self._rebalance_portfolio(target_weights)
		self.trade_log.append(
			{"date": self.datas[0].datetime.date(0), "weights": target_weights.copy()}
		)

	def _rebalance_portfolio(self, target_weights: pd.Series | np.ndarray) -> None:
		total_value = self.broker.getvalue()

		for index, data in enumerate(self.datas):
			target_weight = target_weights[index]
			target_value = total_value * target_weight
			current_position = self.getposition(data).size
			current_price = data.close[0]
			current_value = current_position * current_price
			diff_value = target_value - current_value
			threshold = total_value * 0.01

			if abs(diff_value) > threshold:
				size = int(diff_value / current_price)
				if size > 0:
					self.buy(data=data, size=size)
				elif size < 0:
					self.sell(data=data, size=-size)


def main() -> None:
	print("=" * 60)
	print("ETF动量轮动策略回测 (Python版本)")
	print("=" * 60)
	print(f"回测期间: {BACKTEST_START} 至 {BACKTEST_END}")
	print(f"ETF标的: {', '.join(ETF_NAMES)}")
	print(f"参数: N={MOMENTUM_WINDOW}, K={REBALANCE_DAYS}")
	print(f"初始资金: {INITIAL_CASH:,.0f} 元")
	print("=" * 60)

	price_data = prepare_price_data(ETF_SYMBOLS, BACKTEST_START, BACKTEST_END, DATA_CACHE_NAME)
	if BENCHMARK_SYMBOL not in price_data:
		raise RuntimeError(f"缺少基准数据: {BENCHMARK_SYMBOL}")
	available_assets = [
		(symbol, name)
		for symbol, name in zip(ETF_SYMBOLS, ETF_NAMES)
		if symbol in price_data
	]
	available_symbols = [symbol for symbol, _ in available_assets]
	available_names = [name for _, name in available_assets]

	strategy_result = run_strategy_backtest(
		price_data,
		available_symbols,
		available_names,
		EtfMomentumStrategy,
		STRATEGY_NAME,
		INITIAL_CASH,
		{
			"momentum_window": MOMENTUM_WINDOW,
			"rebalance_days": REBALANCE_DAYS,
		},
	)
	benchmark_result = run_benchmark_backtest(
		price_data,
		BENCHMARK_SYMBOL,
		BENCHMARK_NAME,
		INITIAL_CASH,
	)
	equal_result = run_equal_weight_backtest(
		price_data,
		available_symbols,
		available_names,
		INITIAL_CASH,
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
	weights_df = build_trade_log_weight_frame(strategy_result.trade_log, available_names)

	save_results(
		OUTPUT_DIR,
		metrics_df,
		returns_df,
		cumulative_df,
		drawdown_df,
		weights_df,
	)
	plot_compare(STRATEGY_NAME, BENCHMARK_NAME, cumulative_df, drawdown_df, COLORS, OUTPUT_DIR, "momentum_vs_benchmark.png")
	plot_compare(STRATEGY_NAME, EQUAL_WEIGHT_NAME, cumulative_df, drawdown_df, COLORS, OUTPUT_DIR, "momentum_vs_equal_weight.png")
	plot_weights(weights_df, STRATEGY_NAME, OUTPUT_DIR)

	print("\n" + "=" * 60)
	print("效能指标汇总")
	print("=" * 60)
	print(console_metrics.to_string(index=False))
	print(f"\n结果已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
	main()
