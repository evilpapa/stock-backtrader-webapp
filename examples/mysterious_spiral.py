"""神秘螺旋：RPS60 + TD Sequential 月度轮动示例。

本实现复现 ``docs/mysterious-spiral/神秘螺旋策略.txt`` 中的回测口径：

* 钨业五股票池；
* 以 RPS60 为基础分，近 15 个交易日完成 TD 买入 Setup（低九转）加 25 分；
* 每月第一个交易日开盘，依据上月末已知的收盘数据选前两名并等权；
* 使用项目统一的 A 股佣金模型。

运行前请按项目的 Big QMT 配置准备行情服务：

    uv run python examples/mysterious_spiral.py

这是一份研究/回测示例，不构成投资建议。
"""

from __future__ import annotations

import pandas as pd

from bootstrap import project_path
from backtest_common import (
	add_named_price_data,
	build_cerebro,
	build_return_series,
	prepare_price_data,
)
from src.strategy import MysteriousSpiralStrategy, PerformanceCalculator


UNIVERSE = {
	"600549.SH": "厦门钨业",
	"002378.SZ": "章源钨业",
	"000657.SZ": "中钨高新",
	"002997.SZ": "瑞华泰",
	"688779.SH": "中国稀土",
}
START_DATE = "2020-01-01"
END_DATE = "2024-12-31"
INITIAL_CASH = 1_000_000


def run_backtest() -> MysteriousSpiralStrategy:
	"""拉取 QMT 日线，执行回测，并将调仓和成交明细写入 examples 输出目录。"""
	symbols, names = list(UNIVERSE), list(UNIVERSE.values())
	price_data = prepare_price_data(symbols, START_DATE, END_DATE, "神秘螺旋")
	if len(price_data) < 2:
		raise RuntimeError("至少需要两只标的的完整行情才能运行神秘螺旋回测")

	# 开盘成交模式使月初调仓信号可以在当日开盘价执行。
	cerebro = build_cerebro(INITIAL_CASH)
	cerebro.broker.set_coo(True)
	add_named_price_data(cerebro, price_data, symbols, names)
	cerebro.addstrategy(MysteriousSpiralStrategy)
	result = cerebro.run(cheat_on_open=True)[0]

	returns = build_return_series(result)
	calculator = PerformanceCalculator()
	metrics = pd.DataFrame(
		[
			{
				"年化收益率": calculator.annualized_return(returns),
				"夏普比率": calculator.sharpe_ratio(returns),
				"最大回撤": calculator.max_drawdown(returns),
				"总交易日": len(returns),
				"成交笔数": len(result.trade_log),
			}
		]
	)
	print("\n神秘螺旋回测结果")
	print(metrics.to_string(index=False, formatters={"年化收益率": "{:.2%}".format, "最大回撤": "{:.2%}".format}))

	output_dir = project_path("examples", "mysterious-spiral")
	output_dir.mkdir(exist_ok=True)
	metrics.to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
	pd.DataFrame(result.rebalance_history).to_json(
		output_dir / "rebalance_history.json", orient="records", force_ascii=False, indent=2
	)
	pd.DataFrame(result.trade_log).to_csv(output_dir / "trade_log.csv", index=False, encoding="utf-8-sig")
	return result


if __name__ == "__main__":
	run_backtest()
