from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from examples.turtle_trading import (
	STRATEGY_NAME,
	TurtleBacktestConfig,
	build_equity_frame,
	build_trade_frame,
	build_turtle_metrics,
	save_outputs,
)
from examples.backtest_common import prepare_price_data, read_result_detail, run_strategy_backtest
from src.strategy_evaluation import SCORE_COLUMNS
from src.strategy import TurtleTradingStrategy
from src.utils.schemas import DataSourceParams


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
	"""海龟策略回测生成的权益、交易和绩效结果表。"""

	equity: pd.DataFrame
	trades: pd.DataFrame
	metrics: pd.DataFrame


def load_turtle_results(output_dir: Path = DEFAULT_OUTPUT_DIR) -> TurtleFrames | None:
	"""从输出目录加载海龟策略结果；缺少核心结果文件时返回空。"""
	equity_path = output_dir / "equity_curve.csv"
	trades_path = output_dir / "trade_log.csv"
	metrics_path = output_dir / "performance_metrics.csv"
	if not equity_path.exists() or not trades_path.exists():
		return None
	equity = pd.read_csv(equity_path, encoding="utf-8-sig")
	metrics = pd.read_csv(metrics_path, encoding="utf-8-sig") if metrics_path.exists() else pd.DataFrame()
	if not set(SCORE_COLUMNS).issubset(metrics.columns):
		metrics = build_turtle_metrics(equity)
	return TurtleFrames(
		equity=equity,
		trades=read_result_detail(trades_path),
		metrics=metrics,
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
	data_source_params: DataSourceParams | None = None,
) -> TurtleFrames:
	"""运行海龟交易策略回测，生成权益曲线、交易记录和绩效表。"""
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
	price_data = price_data or prepare_price_data([symbol], start_date, end_date, STRATEGY_NAME, data_source_params)
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
	metrics = build_turtle_metrics(equity)
	save_outputs(equity, trades, config)
	metrics.to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
	return TurtleFrames(equity=equity, trades=trades, metrics=metrics)
