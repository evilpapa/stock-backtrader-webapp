from datetime import date, datetime

from src._constants import (
	BENCHMARK_COLOR,
	DEFAULT_MOMENTUM_WINDOW,
	DEFAULT_REBALANCE_DAYS,
	DEFAULT_TOP_L,
	EQUAL_WEIGHT_COLOR,
	INITIAL_CASH,
	STRATEGY_COLOR,
	default_backtest_end,
)


def test_initial_cash_default_is_stable():
	"""验证共享初始资金默认值保持稳定。"""
	assert INITIAL_CASH == 100_000.0


def test_shared_backtest_defaults_are_stable():
	"""验证回测窗口、调仓频率和图表颜色的共享默认值。"""
	assert DEFAULT_MOMENTUM_WINDOW == 20
	assert DEFAULT_REBALANCE_DAYS == 5
	assert DEFAULT_TOP_L == 5
	assert (STRATEGY_COLOR, BENCHMARK_COLOR, EQUAL_WEIGHT_COLOR) == (
		"#E41A1C",
		"#377EB8",
		"#4DAF4A",
	)


def test_default_backtest_end_is_a_past_iso_date():
	"""验证默认回测结束日是可解析且不晚于当天的 ISO 日期。"""
	assert datetime.strptime(default_backtest_end(), "%Y-%m-%d").date() <= date.today()
