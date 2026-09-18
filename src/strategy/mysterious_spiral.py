"""神秘螺旋：RPS60 与 TD Sequential 月度轮动策略。"""

from __future__ import annotations

import backtrader as bt
import numpy as np

from ._base import BaseStrategy


class MysteriousSpiralStrategy(BaseStrategy):
	"""以上月末 RPS60 和 TD 买入 Setup 信号在月初开盘等权调仓。"""

	_name = "MysteriousSpiral"
	params = (
		("rps_window", 60),  # RPS 相对强弱收益率计算窗口
		("td_lookback", 15),  # 回看 TD 买入 Setup 的交易日数
		("td_bonus", 25.0),  # 出现 TD 买入 Setup 时增加的排名分数
		("top_n", 2),  # 月度等权持仓数量
		("require_perfected_setup", True),  # 是否要求 TD Setup 满足 perfection 条件
		("min_trade_value_pct", 0.001),  # 最小调仓金额占总资产比例
		("print_log", False),  # 是否输出策略运行日志
	)

	def __init__(self) -> None:
		super().__init__()
		self.rebalance_history: list[dict[str, object]] = []
		self.trade_log: list[dict[str, object]] = []
		self._last_rebalance_month: tuple[int, int] | None = None

	def next_open(self) -> None:
		"""月首交易日开盘，根据前一个交易日收盘信号调仓。"""
		if self._has_pending_orders() or not self._has_enough_history():
			return
		today = self.datas[0].datetime.date(0)
		previous_day = self.datas[0].datetime.date(-1)
		month = (today.year, today.month)
		if (today.year, today.month) == (previous_day.year, previous_day.month) or self._last_rebalance_month == month:
			return

		scores, rps_by_name, td_by_name = self._build_scores(signal_offset=-1)
		selected = sorted(scores, key=scores.__getitem__, reverse=True)[: self.p.top_n]
		target_weights = {
			data._name: (1.0 / len(selected) if selected and data._name in selected else 0.0)
			for data in self.datas
		}
		self._rebalance(target_weights)
		self.rebalance_history.append(
			{
				"signal_date": previous_day.isoformat(), "execution_date": today.isoformat(),
				"selected_names": selected, "scores": scores, "rps_60": rps_by_name,
				"td_bear_recent": td_by_name, "target_weights": target_weights,
			}
		)
		self._last_rebalance_month = month

	def notify_order(self, order: bt.Order) -> None:
		"""记录成交订单，并让基类维护订单生命周期状态。"""
		super().notify_order(order)
		if order.status == order.Completed:
			self.trade_log.append(
				{"date": self.datas[0].datetime.date(0).isoformat(), "symbol": order.data._name,
				 "action": "BUY" if order.isbuy() else "SELL", "price": float(order.executed.price),
				 "size": int(order.executed.size), "value": float(order.executed.value),
				 "commission": float(order.executed.comm)}
			)

	def _has_enough_history(self) -> bool:
		minimum_bars = max(self.p.rps_window + 1, self.p.td_lookback + 13) + 1
		return all(len(data) >= minimum_bars for data in self.datas)

	def _build_scores(self, signal_offset: int) -> tuple[dict[str, float], dict[str, float], dict[str, bool]]:
		returns = {data._name: self._return_over_window(data, signal_offset, self.p.rps_window) for data in self.datas}
		valid_returns = {name: value for name, value in returns.items() if np.isfinite(value)}
		if not valid_returns:
			return {}, {}, {}
		population = list(valid_returns.values())
		rps_by_name = {
			name: 100.0 * sum(value <= current for value in population) / len(population)
			for name, current in valid_returns.items()
		}
		td_by_name = {data._name: self._has_recent_bear_setup(data, signal_offset) for data in self.datas}
		scores = {name: rps_by_name[name] + (self.p.td_bonus if td_by_name[name] else 0.0) for name in valid_returns}
		return scores, rps_by_name, td_by_name

	@staticmethod
	def _return_over_window(data: bt.LineSeries, end: int, window: int) -> float:
		end_close, start_close = float(data.close[end]), float(data.close[end - window])
		return end_close / start_close - 1.0 if end_close > 0 and start_close > 0 else float("nan")

	def _has_recent_bear_setup(self, data: bt.LineSeries, end: int) -> bool:
		return any(self._is_bear_setup_complete(data, end - days_ago) for days_ago in range(self.p.td_lookback))

	def _is_bear_setup_complete(self, data: bt.LineSeries, end: int) -> bool:
		if any(float(data.close[end - step]) >= float(data.close[end - step - 4]) for step in range(9)):
			return False
		if not self.p.require_perfected_setup:
			return True
		return min(float(data.low[end - 1]), float(data.low[end])) < min(float(data.low[end - 3]), float(data.low[end - 2]))

	def _rebalance(self, target_weights: dict[str, float]) -> None:
		portfolio_value = self.broker.getvalue()
		minimum_change = portfolio_value * self.p.min_trade_value_pct
		for data in self.datas:
			current_value = self.getposition(data).size * data.open[0]
			if target_weights[data._name] == 0.0 and abs(current_value) >= minimum_change:
				self._track_order(self.order_target_percent(data=data, target=0.0))
		for data in self.datas:
			target_value = portfolio_value * target_weights[data._name]
			current_value = self.getposition(data).size * data.open[0]
			if target_weights[data._name] > 0.0 and abs(target_value - current_value) >= minimum_change:
				self._track_order(self.order_target_percent(data=data, target=target_weights[data._name]))
