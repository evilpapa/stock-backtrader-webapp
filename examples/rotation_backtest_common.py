from __future__ import annotations

import os
from pathlib import Path

import backtrader as bt
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec

from strategy.analyzer import CustomAnalyzer
from strategy.equal_weight import EqualWeightStrategy
from strategy.just_buy_hold import JustBuyHoldStrategy
from strategy.performance_calculator import PerformanceCalculator
from utils.fetch_data import fetch_etf_data


def prepare_price_data(symbols: list[str], start_date: str, end_date: str, strategy_name: str) -> dict[str, pd.DataFrame]:
	raw = fetch_etf_data(symbols, start_date, end_date, strategy_name=strategy_name)
	prepared: dict[str, pd.DataFrame] = {}

	for symbol, frame in raw.items():
		df = frame.copy()
		if isinstance(df.columns, pd.MultiIndex):
			df = df.xs(symbol, level=1, axis=1)

		required = ["Open", "High", "Low", "Close", "Volume"]
		if not all(column in df.columns for column in required):
			print(f"  ✗ 跳过 {symbol}: 缺少必要列")
			continue

		df = df[required].dropna().sort_index()
		if df.empty:
			print(f"  ✗ 跳过 {symbol}: 清洗后无可用数据")
			continue
		prepared[symbol] = df

	return prepared


def build_cerebro(initial_cash: float, commission: float) -> bt.Cerebro:
	cerebro = bt.Cerebro()
	cerebro.broker.setcash(initial_cash)
	cerebro.broker.setcommission(commission=commission)
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")
	return cerebro


def run_rotation_strategy_backtest(
	price_data: dict[str, pd.DataFrame],
	symbols: list[str],
	names: list[str],
	benchmark_name: str,
	strategy_cls,
	strategy_display_name: str,
	initial_cash: float,
	commission: float,
	momentum_window: int,
	rebalance_days: int,
	top_l: int,
):
	print(f"\n==> 运行{strategy_display_name}回测...")
	cerebro = build_cerebro(initial_cash, commission)

	for symbol, name in zip(symbols, names):
		data = price_data.get(symbol)
		if data is None:
			continue
		cerebro.adddata(bt.feeds.PandasData(dataname=data), name=name)
		print(f"  ✓ 已添加数据: {name}")

	benchmark_index = next(
		(index for index, data in enumerate(cerebro.datas) if data._name == benchmark_name),
		None,
	)
	cerebro.addstrategy(
		strategy_cls,
		momentum_window=momentum_window,
		rebalance_days=rebalance_days,
		top_l=top_l,
		benchmark_index=benchmark_index,
	)
	print(f"  初始资金: {cerebro.broker.getvalue():.2f}")
	result = cerebro.run()[0]
	print(f"  期末资金: {cerebro.broker.getvalue():.2f}")
	return result


def run_benchmark_backtest(
	price_data: dict[str, pd.DataFrame],
	benchmark_symbol: str,
	benchmark_name: str,
	initial_cash: float,
	commission: float,
):
	print(f"\n==> 运行基准策略回测: {benchmark_name}")
	cerebro = build_cerebro(initial_cash, commission)
	data = price_data[benchmark_symbol]
	cerebro.adddata(bt.feeds.PandasData(dataname=data), name=benchmark_name)
	cerebro.addstrategy(JustBuyHoldStrategy)
	print(f"  初始资金: {cerebro.broker.getvalue():.2f}")
	result = cerebro.run()[0]
	print(f"  期末资金: {cerebro.broker.getvalue():.2f}")
	return result


def run_equal_weight_backtest(
	price_data: dict[str, pd.DataFrame],
	symbols: list[str],
	names: list[str],
	initial_cash: float,
	commission: float,
	equal_weight_name: str,
	exclude_names: set[str] | None = None,
):
	print(f"\n==> 运行{equal_weight_name}回测")
	cerebro = build_cerebro(initial_cash, commission)
	data_count = 0
	exclude_names = exclude_names or set()

	for symbol, name in zip(symbols, names):
		data = price_data.get(symbol)
		if data is None or name in exclude_names:
			continue
		cerebro.adddata(bt.feeds.PandasData(dataname=data), name=name)
		data_count += 1
		print(f"  ✓ 已添加数据: {name}")

	if data_count == 0:
		raise RuntimeError(f"{equal_weight_name}回测缺少可用数据")

	cerebro.addstrategy(EqualWeightStrategy)
	print(f"  初始资金: {cerebro.broker.getvalue():.2f}")
	result = cerebro.run()[0]
	print(f"  期末资金: {cerebro.broker.getvalue():.2f}")
	return result


def build_return_series(result) -> pd.Series:
	dates = pd.to_datetime(result.analyzers.custom.dates)
	returns = pd.Series(result.analyzers.custom.returns, index=dates, dtype=float)
	return returns.replace([np.inf, -np.inf], np.nan).dropna()


def align_series(*series: pd.Series) -> list[pd.Series]:
	common_index = series[0].index
	for current in series[1:]:
		common_index = common_index.intersection(current.index)
	return [current.reindex(common_index).dropna() for current in series]


def build_metrics(
	strategy_returns: pd.Series,
	benchmark_returns: pd.Series,
	equal_returns: pd.Series,
	strategy_name: str,
	benchmark_name: str,
	equal_weight_name: str,
) -> pd.DataFrame:
	calc = PerformanceCalculator()
	rows = []
	for name, returns in [
		(strategy_name, strategy_returns),
		(benchmark_name, benchmark_returns),
		(equal_weight_name, equal_returns),
	]:
		rows.append(
			{
				"策略": name,
				"年化收益率": calc.annualized_return(returns),
				"年化波动率": calc.annualized_volatility(returns),
				"夏普比率": calc.sharpe_ratio(returns),
				"最大回撤": calc.max_drawdown(returns),
				"卡尔马比率": calc.calmar_ratio(returns),
				"索提诺比率": calc.sortino_ratio(returns),
				"胜率": calc.win_rate(returns),
				"正收益天数": int((returns > 0).sum()),
				"总交易天数": int(len(returns)),
			}
		)

	return pd.DataFrame(rows)


def format_metrics_for_console(metrics_df: pd.DataFrame) -> pd.DataFrame:
	formatted = metrics_df.copy()
	for column in ["年化收益率", "年化波动率", "最大回撤", "胜率"]:
		formatted[column] = formatted[column].map(lambda value: f"{value * 100:.2f}%")
	for column in ["夏普比率", "卡尔马比率", "索提诺比率"]:
		formatted[column] = formatted[column].map(lambda value: f"{value:.3f}")
	return formatted


def build_weight_frame(strategy_result) -> pd.DataFrame:
	rows = []
	for snapshot in strategy_result.rebalance_history:
		row = {"Date": snapshot["date"]}
		row.update(snapshot["target_weights_by_name"])
		row["权重合计"] = sum(snapshot["target_weights_by_name"].values())
		rows.append(row)
	return pd.DataFrame(rows)


def build_rebalance_detail_frame(strategy_result, asset_label: str) -> pd.DataFrame:
	rows = []
	for snapshot in strategy_result.rebalance_history:
		selected_set = set(snapshot["selected_names"])
		all_names = set(snapshot["target_weights_by_name"])
		for name in sorted(all_names):
			rows.append(
				{
					"Date": snapshot["date"],
					asset_label: name,
					"Selected": name in selected_set,
					"Weight": snapshot["target_weights_by_name"].get(name, 0.0),
					"Momentum": snapshot["momentum_by_name"].get(name, np.nan),
					"AdjMomentum": snapshot["adj_momentum_by_name"].get(name, np.nan),
				}
			)
	return pd.DataFrame(rows)


def build_selection_frequency_frame(strategy_result, asset_label: str) -> pd.DataFrame:
	counts: dict[str, int] = {}
	for snapshot in strategy_result.rebalance_history:
		for name in snapshot["selected_names"]:
			counts[name] = counts.get(name, 0) + 1
	rows = [{asset_label: name, "SelectedCount": count} for name, count in counts.items()]
	frame = pd.DataFrame(rows)
	if frame.empty:
		return frame
	return frame.sort_values(["SelectedCount", asset_label], ascending=[False, True]).reset_index(drop=True)


def build_returns_frame(
	strategy_returns: pd.Series,
	benchmark_returns: pd.Series,
	equal_returns: pd.Series,
	strategy_name: str,
	benchmark_name: str,
	equal_weight_name: str,
) -> pd.DataFrame:
	return pd.DataFrame(
		{
			"Date": strategy_returns.index,
			strategy_name: strategy_returns.values,
			benchmark_name: benchmark_returns.values,
			equal_weight_name: equal_returns.values,
		}
	)


def build_cumulative_frame(
	strategy_returns: pd.Series,
	benchmark_returns: pd.Series,
	equal_returns: pd.Series,
	strategy_name: str,
	benchmark_name: str,
	equal_weight_name: str,
) -> pd.DataFrame:
	return pd.DataFrame(
		{
			"Date": strategy_returns.index,
			strategy_name: (1 + strategy_returns).cumprod().values,
			benchmark_name: (1 + benchmark_returns).cumprod().values,
			equal_weight_name: (1 + equal_returns).cumprod().values,
		}
	)


def build_drawdown_frame(
	strategy_returns: pd.Series,
	benchmark_returns: pd.Series,
	equal_returns: pd.Series,
	strategy_name: str,
	benchmark_name: str,
	equal_weight_name: str,
) -> pd.DataFrame:
	calc = PerformanceCalculator()
	return pd.DataFrame(
		{
			"Date": strategy_returns.index,
			strategy_name: calc.calc_drawdown(strategy_returns).values,
			benchmark_name: calc.calc_drawdown(benchmark_returns).values,
			equal_weight_name: calc.calc_drawdown(equal_returns).values,
		}
	)


def plot_compare(
	left_name: str,
	right_name: str,
	cumulative_df: pd.DataFrame,
	drawdown_df: pd.DataFrame,
	colors: dict[str, str],
	output_dir: Path,
	filename: str,
) -> None:
	fig = plt.figure(figsize=(12, 8))
	grid = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

	ax_top = fig.add_subplot(grid[0])
	ax_top.plot(cumulative_df["Date"], cumulative_df[left_name], label=left_name, color=colors[left_name], linewidth=2)
	ax_top.plot(cumulative_df["Date"], cumulative_df[right_name], label=right_name, color=colors[right_name], linewidth=2)
	ax_top.set_ylabel("累计净值")
	ax_top.set_title(f"{left_name} vs {right_name}")
	ax_top.legend(loc="upper left")
	ax_top.grid(alpha=0.3)
	ax_top.set_xticklabels([])

	ax_bottom = fig.add_subplot(grid[1])
	ax_bottom.fill_between(drawdown_df["Date"], drawdown_df[left_name], 0, color=colors[left_name], alpha=0.3)
	ax_bottom.fill_between(drawdown_df["Date"], drawdown_df[right_name], 0, color=colors[right_name], alpha=0.3)
	ax_bottom.set_xlabel("日期")
	ax_bottom.set_ylabel("回撤")
	ax_bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
	ax_bottom.grid(alpha=0.3)

	plt.tight_layout()
	plt.savefig(output_dir / filename, dpi=250, bbox_inches="tight")
	plt.close(fig)


def plot_weights(weights_df: pd.DataFrame, strategy_name: str, output_dir: Path) -> None:
	if weights_df.empty:
		return
	plot_df = weights_df.copy()
	plot_df["Date"] = pd.to_datetime(plot_df["Date"])
	plot_df = plot_df.set_index("Date").drop(columns=["权重合计"], errors="ignore")
	plot_df = plot_df.loc[:, (plot_df.sum(axis=0) > 0)]
	if plot_df.empty:
		return
	fig, ax = plt.subplots(figsize=(14, 7))
	ax.stackplot(plot_df.index, plot_df.T.values, labels=plot_df.columns, alpha=0.8)
	ax.set_title(f"{strategy_name}每日权重分配")
	ax.set_xlabel("日期")
	ax.set_ylabel("权重")
	ax.grid(alpha=0.25)
	ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
	ax.legend(loc="upper left", ncol=2, fontsize=9)
	plt.tight_layout()
	plt.savefig(output_dir / "daily_weights_plot.png", dpi=250, bbox_inches="tight")
	plt.close(fig)


def save_results(
	output_dir: Path,
	metrics_df: pd.DataFrame,
	returns_df: pd.DataFrame,
	cumulative_df: pd.DataFrame,
	drawdown_df: pd.DataFrame,
	weights_df: pd.DataFrame,
	selection_frequency_df: pd.DataFrame,
	rebalance_detail_df: pd.DataFrame,
) -> None:
	os.makedirs(output_dir, exist_ok=True)
	metrics_df.to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
	returns_df.to_csv(output_dir / "daily_returns.csv", index=False, encoding="utf-8-sig")
	cumulative_df.to_csv(output_dir / "cumulative_returns.csv", index=False, encoding="utf-8-sig")
	drawdown_df.to_csv(output_dir / "drawdowns.csv", index=False, encoding="utf-8-sig")
	weights_df.to_csv(output_dir / "daily_weights.csv", index=False, encoding="utf-8-sig")
	selection_frequency_df.to_csv(output_dir / "selection_frequency.csv", index=False, encoding="utf-8-sig")
	rebalance_detail_df.to_csv(output_dir / "rebalance_details.csv", index=False, encoding="utf-8-sig")
