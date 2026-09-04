"""神秘螺旋：RPS60 + TD Sequential 月度轮动示例。

本实现复现 ``docs/mysterious-spiral/神秘螺旋策略.txt`` 中的回测口径：

* 钨业五股票池；
* 以 RPS60 为基础分，近 15 个交易日完成 TD 买入 Setup（低九转）加 25 分；
* 每月第一个交易日开盘，依据上月末已知的收盘数据选前两名并等权；
* 使用项目统一的 A 股佣金模型。

运行前请按项目的 Big QMT 配置准备行情服务：

    .venv\\Scripts\\python.exe examples\\mysterious_spiral.py

这是一份研究/回测示例，不构成投资建议。
"""

from __future__ import annotations

import backtrader as bt
import numpy as np
import pandas as pd

from bootstrap import project_path
from backtest_common import (
	add_named_price_data,
	build_return_series,
	prepare_price_data,
)
from strategy.analyzer import CustomAnalyzer
from strategy.performance_calculator import PerformanceCalculator


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


class MysteriousSpiralCommission(bt.CommInfoBase):
	"""说明文件指定的双边佣金 0.03%、卖出印花税 0.1%。"""

	params = (
		("stocklike", True),
		("commtype", bt.CommInfoBase.COMM_PERC),
		("percabs", True),
		("commission", 0.0003),
		("stamp_tax", 0.001),
	)

	def _getcommission(self, size: float, price: float, pseudoexec: bool) -> float:
		turnover = abs(size) * price
		commission = turnover * self.p.commission
		return commission + (turnover * self.p.stamp_tax if size < 0 else 0.0)


class MysteriousSpiralStrategy(bt.Strategy):
	"""用上月末信号在本月首个交易日开盘调仓的 RPS/TD 策略。"""

	params = (
		("rps_window", 60),
		("td_lookback", 15),
		("td_bonus", 25.0),
		("top_n", 2),
		("require_perfected_setup", True),
		("min_trade_value_pct", 0.001),
		("printlog", False),
	)

	def __init__(self) -> None:
		self.rebalance_history: list[dict[str, object]] = []
		self.trade_log: list[dict[str, object]] = []
		self._last_rebalance_month: tuple[int, int] | None = None

	def next_open(self) -> None:
		"""在月初开盘时，用前一交易日收盘后的完整信号进行调仓。"""
		if not self._has_enough_history():
			return

		today = self.datas[0].datetime.date(0)
		previous_day = self.datas[0].datetime.date(-1)
		month = (today.year, today.month)
		if (today.year, today.month) == (previous_day.year, previous_day.month):
			return
		if self._last_rebalance_month == month:
			return

		scores, rps_by_name, td_by_name = self._build_scores(signal_offset=-1)
		selected = sorted(scores, key=scores.__getitem__, reverse=True)[: self.p.top_n]
		target_weights = {
			data._name: (1.0 / len(selected) if data._name in selected else 0.0)
			for data in self.datas
		}
		self._rebalance(target_weights)
		self.rebalance_history.append(
			{
				"signal_date": previous_day.isoformat(),
				"execution_date": today.isoformat(),
				"selected_names": selected,
				"scores": scores,
				"rps_60": rps_by_name,
				"td_bear_recent": td_by_name,
				"target_weights": target_weights,
			}
		)
		self._last_rebalance_month = month

	def notify_order(self, order: bt.Order) -> None:
		if order.status != order.Completed:
			return
		self.trade_log.append(
			{
				"date": self.datas[0].datetime.date(0).isoformat(),
				"symbol": order.data._name,
				"action": "BUY" if order.isbuy() else "SELL",
				"price": float(order.executed.price),
				"size": int(order.executed.size),
				"value": float(order.executed.value),
				"commission": float(order.executed.comm),
			}
		)

	def _has_enough_history(self) -> bool:
		# TD Setup 需要当前及前 12 根 K 线（9 根比较各自再向前 4 根），
		# RPS60 还需要用于计算 60 日收益的起点。
		minimum_bars = max(self.p.rps_window + 1, self.p.td_lookback + 13) + 1
		return all(len(data) >= minimum_bars for data in self.datas)

	def _build_scores(
		self, signal_offset: int
	) -> tuple[dict[str, float], dict[str, float], dict[str, bool]]:
		returns = {
			data._name: self._return_over_window(data, signal_offset, self.p.rps_window)
			for data in self.datas
		}
		valid_returns = {name: value for name, value in returns.items() if np.isfinite(value)}
		if not valid_returns:
			return {}, {}, {}

		# RPS 是股票池内收益率的横截面百分位；同分时使用 <=，与常见 RPS
		# 的分位数定义一致，最高分为 100。
		population = list(valid_returns.values())
		rps_by_name = {
			name: 100.0 * sum(value <= current for value in population) / len(population)
			for name, current in valid_returns.items()
		}
		td_by_name = {
			data._name: self._has_recent_bear_setup(data, signal_offset)
			for data in self.datas
		}
		scores = {
			name: rps_by_name[name] + (self.p.td_bonus if td_by_name[name] else 0.0)
			for name in valid_returns
		}
		return scores, rps_by_name, td_by_name

	@staticmethod
	def _return_over_window(data: bt.LineSeries, end: int, window: int) -> float:
		end_close = float(data.close[end])
		start_close = float(data.close[end - window])
		if end_close <= 0 or start_close <= 0:
			return float("nan")
		return end_close / start_close - 1.0

	def _has_recent_bear_setup(self, data: bt.LineSeries, end: int) -> bool:
		return any(
			self._is_bear_setup_complete(data, end - days_ago)
			for days_ago in range(self.p.td_lookback)
		)

	def _is_bear_setup_complete(self, data: bt.LineSeries, end: int) -> bool:
		"""判断 ``end`` 是否为 TD 买入 Setup（低九转）的第 9 根。

		低九转要求连续九根收盘价低于各自四根 K 线前的收盘价。默认还
		启用 TD 的 perfection 验证：第 8 或第 9 根的最低价须低于第 6、7
		根的最低价；不需要该过滤时可设置 ``require_perfected_setup=False``。
		"""
		if any(float(data.close[end - step]) >= float(data.close[end - step - 4]) for step in range(9)):
			return False
		if not self.p.require_perfected_setup:
			return True
		setup_day_8_or_9_low = min(float(data.low[end - 1]), float(data.low[end]))
		setup_day_6_and_7_low = min(float(data.low[end - 3]), float(data.low[end - 2]))
		return setup_day_8_or_9_low < setup_day_6_and_7_low

	def _rebalance(self, target_weights: dict[str, float]) -> None:
		portfolio_value = self.broker.getvalue()
		minimum_change = portfolio_value * self.p.min_trade_value_pct
		# 先卖出不在组合中的标的，释放现金后再建立/增加入选标的仓位。
		for data in self.datas:
			current_value = self.getposition(data).size * data.open[0]
			if target_weights[data._name] == 0.0 and abs(current_value) >= minimum_change:
				self.order_target_percent(data=data, target=0.0)
		for data in self.datas:
			target_value = portfolio_value * target_weights[data._name]
			current_value = self.getposition(data).size * data.open[0]
			if target_weights[data._name] > 0.0 and abs(target_value - current_value) >= minimum_change:
				self.order_target_percent(data=data, target=target_weights[data._name])


def run_backtest() -> MysteriousSpiralStrategy:
	"""拉取 QMT 日线，执行回测，并将调仓和成交明细写入 examples 输出目录。"""
	symbols, names = list(UNIVERSE), list(UNIVERSE.values())
	price_data = prepare_price_data(symbols, START_DATE, END_DATE, "神秘螺旋")
	if len(price_data) < 2:
		raise RuntimeError("至少需要两只标的的完整行情才能运行神秘螺旋回测")

	# cheat_on_open 使 next_open 中基于上一交易日收盘得到的信号在当日开盘成交。
	cerebro = bt.Cerebro(cheat_on_open=True)
	cerebro.broker.setcash(INITIAL_CASH)
	cerebro.broker.addcommissioninfo(MysteriousSpiralCommission())
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")
	add_named_price_data(cerebro, price_data, symbols, names)
	cerebro.addstrategy(MysteriousSpiralStrategy)
	result = cerebro.run()[0]

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

	output_dir = project_path("examples", "mysterious_spiral_results")
	output_dir.mkdir(exist_ok=True)
	metrics.to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
	pd.DataFrame(result.rebalance_history).to_json(
		output_dir / "rebalance_history.json", orient="records", force_ascii=False, indent=2
	)
	pd.DataFrame(result.trade_log).to_csv(output_dir / "trade_log.csv", index=False, encoding="utf-8-sig")
	return result


if __name__ == "__main__":
	run_backtest()
