"""
海龟交易策略回测脚本
使用:
	uv run python examples/turtle_trading/backtest_turtle_trading.py
"""

from __future__ import annotations

import argparse
import runpy
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pandas as pd

_bootstrap = runpy.run_path(str(Path(__file__).resolve().parents[1] / "bootstrap.py"))
project_root = _bootstrap["project_root"]
project_path = _bootstrap["project_path"]

from charts import configure_matplotlib_chinese_font
from examples.rotation_backtest_common import (
	prepare_price_data,
	run_strategy_backtest,
)
from strategy.turtle_trading import TurtleTradingStrategy

OUTPUT_DIR = project_path("examples", "turtle_trading", "backtest_results")
STRATEGY_NAME = "海龟交易策略"
SYMBOL = "600519"
BACKTEST_START = "2021-01-01"
BACKTEST_END = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
ENTRY_PERIOD = 20
EXIT_PERIOD = 10
ATR_PERIOD = 20
MAX_UNITS = 4
RISK_PCT = 0.01
LOT_SIZE = 1
INITIAL_CASH = 100000.0
ALLOW_SHORT = True

configure_matplotlib_chinese_font()


@dataclass(frozen=True)
class TurtleBacktestConfig:
	symbol: str = SYMBOL
	start_date: str = BACKTEST_START
	end_date: str = BACKTEST_END
	entry_period: int = ENTRY_PERIOD
	exit_period: int = EXIT_PERIOD
	atr_period: int = ATR_PERIOD
	max_units: int = MAX_UNITS
	risk_pct: float = RISK_PCT
	lot_size: int = LOT_SIZE
	initial_cash: float = INITIAL_CASH
	allow_short: bool = ALLOW_SHORT
	output_dir: Path = OUTPUT_DIR


def parse_args(argv: list[str] | None = None) -> TurtleBacktestConfig:
	parser = argparse.ArgumentParser(description="运行海龟交易策略回测")
	parser.add_argument("--symbol", default=SYMBOL, help="股票代码，例如 600519")
	parser.add_argument("--start-date", default=BACKTEST_START, help="回测开始日期 YYYY-MM-DD")
	parser.add_argument("--end-date", default=BACKTEST_END, help="回测结束日期 YYYY-MM-DD")
	parser.add_argument("--entry-period", type=int, default=ENTRY_PERIOD, help="入场通道周期")
	parser.add_argument("--exit-period", type=int, default=EXIT_PERIOD, help="离场通道周期")
	parser.add_argument("--atr-period", type=int, default=ATR_PERIOD, help="ATR 周期")
	parser.add_argument("--max-units", type=int, default=MAX_UNITS, help="最大加仓单位数")
	parser.add_argument("--risk-pct", type=float, default=RISK_PCT, help="单单位风险比例")
	parser.add_argument(
		"--lot-size",
		type=int,
		default=LOT_SIZE,
		help="交易单位取整手数。默认 1，便于小资金示例触发交易；A 股整手可设为 100。",
	)
	parser.add_argument("--initial-cash", type=float, default=INITIAL_CASH, help="初始资金")
	parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="结果输出目录")
	short_group = parser.add_mutually_exclusive_group()
	short_group.add_argument("--allow-short", dest="allow_short", action="store_true", default=ALLOW_SHORT)
	short_group.add_argument("--no-allow-short", dest="allow_short", action="store_false")
	args = parser.parse_args(argv)
	return TurtleBacktestConfig(
		symbol=args.symbol,
		start_date=args.start_date,
		end_date=args.end_date,
		entry_period=args.entry_period,
		exit_period=args.exit_period,
		atr_period=args.atr_period,
		max_units=args.max_units,
		risk_pct=args.risk_pct,
		lot_size=max(args.lot_size, 1),
		initial_cash=args.initial_cash,
		allow_short=args.allow_short,
		output_dir=args.output_dir,
	)


def fetch_data(config: TurtleBacktestConfig) -> pd.DataFrame:
	price_data = prepare_price_data([config.symbol], config.start_date, config.end_date, STRATEGY_NAME)
	return price_data.get(config.symbol, pd.DataFrame())


def run_backtest(df: pd.DataFrame, config: TurtleBacktestConfig) -> TurtleTradingStrategy:
	return run_strategy_backtest(
		{config.symbol: df},
		[config.symbol],
		[config.symbol],
		TurtleTradingStrategy,
		STRATEGY_NAME,
		config.initial_cash,
		{
			"entry_period": config.entry_period,
			"exit_period": config.exit_period,
			"atr_period": config.atr_period,
			"max_units": config.max_units,
			"risk_pct": config.risk_pct,
			"lot_size": config.lot_size,
			"allow_short": config.allow_short,
		},
	)


def build_trade_frame(strategy: TurtleTradingStrategy) -> pd.DataFrame:
	return pd.DataFrame(strategy.trade_log)


def build_equity_frame(strategy: TurtleTradingStrategy) -> pd.DataFrame:
	frame = pd.DataFrame(strategy.value_history)
	frame["date"] = pd.to_datetime(frame["date"])
	frame["returns"] = frame["value"].pct_change().fillna(0.0)
	frame["cummax"] = frame["value"].cummax()
	frame["drawdown"] = frame["value"] / frame["cummax"] - 1.0
	return frame


def print_stats(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> None:
	start_value = equity_df["value"].iloc[0]
	end_value = equity_df["value"].iloc[-1]
	total_return = end_value / start_value - 1.0
	days = max((equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days, 1)
	annual_return = (1.0 + total_return) ** (365 / days) - 1.0
	max_drawdown = equity_df["drawdown"].min()

	wins = 0
	completed_trades = 0
	for idx in range(len(trades_df) - 1):
		current = trades_df.iloc[idx]
		next_trade = trades_df.iloc[idx + 1]
		if current["action"] == "BUY" and next_trade["action"] == "SELL":
			completed_trades += 1
			if next_trade["price"] > current["price"]:
				wins += 1
		if current["action"] == "SELL" and next_trade["action"] == "BUY":
			completed_trades += 1
			if next_trade["price"] < current["price"]:
				wins += 1

	win_rate = wins / completed_trades if completed_trades else 0.0
	print(f"总收益率: {total_return * 100:.2f}%")
	print(f"年化收益率: {annual_return * 100:.2f}%")
	print(f"总交易次数: {len(trades_df)}")
	print(f"最大回撤: {max_drawdown * 100:.2f}%")
	print(f"胜率: {win_rate * 100:.2f}%")


def save_outputs(equity_df: pd.DataFrame, trades_df: pd.DataFrame, config: TurtleBacktestConfig) -> None:
	config.output_dir.mkdir(parents=True, exist_ok=True)
	equity_df.to_csv(config.output_dir / "equity_curve.csv", index=False, encoding="utf-8-sig")
	trades_df.to_csv(config.output_dir / "trade_log.csv", index=False, encoding="utf-8-sig")

	fig, ax = plt.subplots(figsize=(12, 6))
	ax.plot(equity_df["date"], equity_df["close"], label="Close", color="#1f77b4")
	if not trades_df.empty:
		buys = trades_df[trades_df["action"] == "BUY"]
		sells = trades_df[trades_df["action"] == "SELL"]
		ax.scatter(pd.to_datetime(buys["date"]), buys["price"], marker="^", color="green", label="Buy")
		ax.scatter(pd.to_datetime(sells["date"]), sells["price"], marker="v", color="red", label="Sell")
	ax.set_title(f"{config.symbol} Price With Signals")
	ax.legend()
	ax.grid(True, alpha=0.3)
	fig.tight_layout()
	fig.savefig(config.output_dir / "price_with_signals.png", dpi=200, bbox_inches="tight")
	plt.close(fig)

	fig, ax = plt.subplots(figsize=(12, 6))
	ax.plot(equity_df["date"], equity_df["value"], color="#ff7f0e")
	ax.set_title("Equity Curve")
	ax.grid(True, alpha=0.3)
	fig.tight_layout()
	fig.savefig(config.output_dir / "equity_curve.png", dpi=200, bbox_inches="tight")
	plt.close(fig)

	fig, ax = plt.subplots(figsize=(12, 4))
	ax.step(equity_df["date"], equity_df["position"], where="post", color="#9467bd")
	ax.set_title("Position State")
	ax.grid(True, alpha=0.3)
	fig.tight_layout()
	fig.savefig(config.output_dir / "position_state.png", dpi=200, bbox_inches="tight")
	plt.close(fig)


def main(argv: list[str] | None = None) -> None:
	config = parse_args(argv)
	print("=" * 60)
	print("海龟交易策略回测 (Python版本)")
	print("=" * 60)
	print(f"回测期间: {config.start_date} 至 {config.end_date}")
	print(f"标的: {config.symbol}")
	print(
		"参数: "
		f"entry={config.entry_period}, exit={config.exit_period}, atr={config.atr_period}, "
		f"max_units={config.max_units}, risk_pct={config.risk_pct}, lot_size={config.lot_size}"
	)
	print(f"初始资金: {config.initial_cash:,.0f} 元")
	print("=" * 60)

	df = fetch_data(config)
	if df.empty:
		raise ValueError("未获取到可用数据")

	strategy = run_backtest(df, config)
	trades_df = build_trade_frame(strategy)
	equity_df = build_equity_frame(strategy)
	print_stats(equity_df, trades_df)
	save_outputs(equity_df, trades_df, config)
	print(f"结果已保存到: {config.output_dir}")


if __name__ == "__main__":
	main()
