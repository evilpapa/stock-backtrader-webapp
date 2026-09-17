from datetime import datetime, timedelta


INITIAL_CASH = 100_000.0
DEFAULT_MOMENTUM_WINDOW = 20
DEFAULT_REBALANCE_DAYS = 5
DEFAULT_TOP_L = 5

STRATEGY_COLOR = "#E41A1C"
BENCHMARK_COLOR = "#377EB8"
EQUAL_WEIGHT_COLOR = "#4DAF4A"


def default_backtest_end() -> str:
	"""返回数据源可识别的昨日日期字符串。"""
	return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
