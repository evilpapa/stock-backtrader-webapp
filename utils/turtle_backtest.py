from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from examples.turtle_trading.backtest_turtle_trading import (
	STRATEGY_NAME,
	TurtleBacktestConfig,
	build_equity_frame,
	build_trade_frame,
	save_outputs,
)
from examples.rotation_backtest_common import prepare_price_data, run_strategy_backtest
from strategy.turtle_trading import TurtleTradingStrategy


DEFAULT_OUTPUT_DIR = Path("examples") / "turtle_trading" / "backtest_results"
DEFAULT_SYMBOL = "600519"
DEFAULT_START_DATE = "2021-01-01"
DEFAULT_ENTRY_PERIOD = 20
DEFAULT_EXIT_PERIOD = 10
DEFAULT_ATR_PERIOD = 20
DEFAULT_MAX_UNITS = 4
DEFAULT_RISK_PCT = 0.01
DEFAULT_LOT_SIZE = 1
DEFAULT_INITIAL_CASH = 100000.0
DEFAULT_ALLOW_SHORT = True


@dataclass(frozen=True)
class TurtleFrames:
	equity: pd.DataFrame
	trades: pd.DataFrame


def load_turtle_results(output_dir: Path = DEFAULT_OUTPUT_DIR) -> TurtleFrames | None:
	equity_path = output_dir / "equity_curve.csv"
	trades_path = output_dir / "trade_log.csv"
	if not equity_path.exists() or not trades_path.exists():
		return None
	return TurtleFrames(
		equity=pd.read_csv(equity_path, encoding="utf-8-sig"),
		trades=pd.read_csv(trades_path, encoding="utf-8-sig"),
	)


def run_turtle_backtest(
	symbol: str,
	start_date: str,
	end_date: str,
	entry_period: int,
	exit_period: int,
	atr_period: int,
	max_units: int,
	risk_pct: float,
	lot_size: int,
	initial_cash: float,
	allow_short: bool,
	output_dir: Path = DEFAULT_OUTPUT_DIR,
	price_data: dict[str, pd.DataFrame] | None = None,
) -> TurtleFrames:
	config = TurtleBacktestConfig(
		symbol=symbol,
		start_date=start_date,
		end_date=end_date,
		entry_period=entry_period,
		exit_period=exit_period,
		atr_period=atr_period,
		max_units=max_units,
		risk_pct=risk_pct,
		lot_size=max(lot_size, 1),
		initial_cash=initial_cash,
		allow_short=allow_short,
		output_dir=output_dir,
	)
	price_data = price_data or prepare_price_data([symbol], start_date, end_date, STRATEGY_NAME)
	df = price_data.get(symbol, pd.DataFrame())
	if df.empty:
		raise ValueError("未获取到可用数据")

	strategy = run_strategy_backtest(
		{symbol: df},
		[symbol],
		[symbol],
		TurtleTradingStrategy,
		STRATEGY_NAME,
		initial_cash,
		{
			"entry_period": entry_period,
			"exit_period": exit_period,
			"atr_period": atr_period,
			"max_units": max_units,
			"risk_pct": risk_pct,
			"lot_size": max(lot_size, 1),
			"allow_short": allow_short,
		},
	)
	equity = build_equity_frame(strategy)
	trades = build_trade_frame(strategy)
	save_outputs(equity, trades, config)
	return TurtleFrames(equity=equity, trades=trades)
