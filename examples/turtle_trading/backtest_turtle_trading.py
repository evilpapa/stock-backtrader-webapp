"""
海龟交易策略回测脚本
使用:
	uv run python examples/turtle_trading/backtest_turtle_trading.py
"""

from __future__ import annotations

import runpy
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
LOT_SIZE = 100
INITIAL_CASH = 100000.0
ALLOW_SHORT = True

configure_matplotlib_chinese_font()


def fetch_data() -> pd.DataFrame:
	price_data = prepare_price_data([SYMBOL], BACKTEST_START, BACKTEST_END, STRATEGY_NAME)
	return price_data.get(SYMBOL, pd.DataFrame())


def run_backtest(df: pd.DataFrame) -> TurtleTradingStrategy:
	return run_strategy_backtest(
		{SYMBOL: df},
		[SYMBOL],
		[SYMBOL],
		TurtleTradingStrategy,
		STRATEGY_NAME,
		INITIAL_CASH,
		{
			"entry_period": ENTRY_PERIOD,
			"exit_period": EXIT_PERIOD,
			"atr_period": ATR_PERIOD,
			"max_units": MAX_UNITS,
			"risk_pct": RISK_PCT,
			"lot_size": LOT_SIZE,
			"allow_short": ALLOW_SHORT,
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


def save_outputs(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> None:
	OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
	equity_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False, encoding="utf-8-sig")
	trades_df.to_csv(OUTPUT_DIR / "trade_log.csv", index=False, encoding="utf-8-sig")

	fig, ax = plt.subplots(figsize=(12, 6))
	ax.plot(equity_df["date"], equity_df["close"], label="Close", color="#1f77b4")
	if not trades_df.empty:
		buys = trades_df[trades_df["action"] == "BUY"]
		sells = trades_df[trades_df["action"] == "SELL"]
		ax.scatter(pd.to_datetime(buys["date"]), buys["price"], marker="^", color="green", label="Buy")
		ax.scatter(pd.to_datetime(sells["date"]), sells["price"], marker="v", color="red", label="Sell")
	ax.set_title(f"{SYMBOL} Price With Signals")
	ax.legend()
	ax.grid(True, alpha=0.3)
	fig.tight_layout()
	fig.savefig(OUTPUT_DIR / "price_with_signals.png", dpi=200, bbox_inches="tight")
	plt.close(fig)

	fig, ax = plt.subplots(figsize=(12, 6))
	ax.plot(equity_df["date"], equity_df["value"], color="#ff7f0e")
	ax.set_title("Equity Curve")
	ax.grid(True, alpha=0.3)
	fig.tight_layout()
	fig.savefig(OUTPUT_DIR / "equity_curve.png", dpi=200, bbox_inches="tight")
	plt.close(fig)

	fig, ax = plt.subplots(figsize=(12, 4))
	ax.step(equity_df["date"], equity_df["position"], where="post", color="#9467bd")
	ax.set_title("Position State")
	ax.grid(True, alpha=0.3)
	fig.tight_layout()
	fig.savefig(OUTPUT_DIR / "position_state.png", dpi=200, bbox_inches="tight")
	plt.close(fig)


def main() -> None:
	print("=" * 60)
	print("海龟交易策略回测 (Python版本)")
	print("=" * 60)
	print(f"回测期间: {BACKTEST_START} 至 {BACKTEST_END}")
	print(f"标的: {SYMBOL}")
	print(f"参数: entry={ENTRY_PERIOD}, exit={EXIT_PERIOD}, atr={ATR_PERIOD}, max_units={MAX_UNITS}")
	print(f"初始资金: {INITIAL_CASH:,.0f} 元")
	print("=" * 60)

	df = fetch_data()
	if df.empty:
		raise ValueError("未获取到可用数据")

	strategy = run_backtest(df)
	trades_df = build_trade_frame(strategy)
	equity_df = build_equity_frame(strategy)
	print_stats(equity_df, trades_df)
	save_outputs(equity_df, trades_df)
	print(f"结果已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
	main()
