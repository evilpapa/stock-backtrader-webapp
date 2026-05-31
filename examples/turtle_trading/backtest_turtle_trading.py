from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import backtrader as bt
import matplotlib.pyplot as plt
import pandas as pd

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from strategy.turtle_trading import TurtleTradingStrategy
from utils.xtdata_client import fetch_history_ohlcv, to_title_case_ohlcv

OUTPUT_DIR = Path(project_root) / "datas" / "turtle_trading" / "backtest_results"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="海龟交易策略回测")
	parser.add_argument("--symbol", default="600519")
	parser.add_argument("--start", default="2015-01-01")
	parser.add_argument("--end", default="2025-12-31")
	parser.add_argument("--entry-period", type=int, default=20)
	parser.add_argument("--exit-period", type=int, default=10)
	parser.add_argument("--atr-period", type=int, default=20)
	parser.add_argument("--max-units", type=int, default=4)
	parser.add_argument("--risk-pct", type=float, default=0.01)
	parser.add_argument("--lot-size", type=int, default=1)
	parser.add_argument("--commission", type=float, default=0.001)
	parser.add_argument("--cash", type=float, default=100000.0)
	parser.add_argument("--long-only", action="store_true")
	return parser.parse_args()


def fetch_data(args: argparse.Namespace) -> pd.DataFrame:
	df = to_title_case_ohlcv(fetch_history_ohlcv(args.symbol, args.start, args.end))
	if df.empty:
		return pd.DataFrame()
	return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def run_backtest(df: pd.DataFrame, args: argparse.Namespace) -> TurtleTradingStrategy:
	cerebro = bt.Cerebro()
	cerebro.adddata(bt.feeds.PandasData(dataname=df))
	cerebro.broker.setcash(args.cash)
	cerebro.broker.setcommission(commission=args.commission)
	cerebro.addstrategy(
		TurtleTradingStrategy,
		entry_period=args.entry_period,
		exit_period=args.exit_period,
		atr_period=args.atr_period,
		max_units=args.max_units,
		risk_pct=args.risk_pct,
		lot_size=args.lot_size,
		allow_short=not args.long_only,
	)
	results = cerebro.run()
	strategy = results[0]
	print(f"期末资金: {cerebro.broker.getvalue():.2f}")
	return strategy


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


def save_outputs(equity_df: pd.DataFrame, trades_df: pd.DataFrame, args: argparse.Namespace) -> None:
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
	ax.set_title(f"{args.symbol} Price With Signals")
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
	args = parse_args()
	args.lot_size = 100

	df = fetch_data(args)
	if df.empty:
		raise ValueError("未获取到可用数据")

	strategy = run_backtest(df, args)
	trades_df = build_trade_frame(strategy)
	equity_df = build_equity_frame(strategy)
	print_stats(equity_df, trades_df)
	save_outputs(equity_df, trades_df, args)
	print(f"结果已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
	main()
