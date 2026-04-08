"""
共享的风险调整动量轮动基类。
"""

import backtrader as bt
import numpy as np

from .base import BaseStrategy


class RotationStrategyBase(BaseStrategy):
	params = (
		("momentum_window", 20),
		("rebalance_days", 5),
		("top_l", 5),
		("benchmark_index", None),
		("min_trade_value_pct", 0.01),
		("printlog", False),
	)

	def __init__(self):
		super().__init__()
		self.order = None
		self.rebalance_counter = 0
		self.dataclose = [data.close for data in self.datas]
		self.returns = []
		self.momentum = []
		self.volatility = []
		self.rebalance_history = []

		for data in self.datas:
			return_series = bt.indicators.PctChange(data.close, period=1)
			self.returns.append(return_series)
			self.momentum.append(
				bt.indicators.SimpleMovingAverage(return_series, period=self.params.momentum_window)
			)
			self.volatility.append(
				bt.indicators.StandardDeviation(return_series, period=self.params.momentum_window)
			)

	def next(self):
		self.rebalance_counter += 1
		if self.rebalance_counter < self.params.rebalance_days:
			return
		self.rebalance_counter = 0

		if len(self.datas[0]) < self.params.momentum_window:
			return

		target_weights, selected_indices, adj_momentum_by_name, momentum_by_name = self._build_target_weights()
		self._rebalance_portfolio(target_weights)
		self._record_rebalance(
			target_weights,
			selected_indices,
			adj_momentum_by_name,
			momentum_by_name,
		)

	def _build_target_weights(self) -> tuple[np.ndarray, list[int], dict[str, float], dict[str, float]]:
		tradable_indices = self._get_tradable_indices()
		target_weights = np.zeros(len(self.datas))
		candidates: list[tuple[int, float]] = []
		adj_momentum_by_name: dict[str, float] = {}
		momentum_by_name: dict[str, float] = {}

		for index in tradable_indices:
			momentum_value = self.momentum[index][0]
			volatility_value = self.volatility[index][0]
			if np.isnan(momentum_value) or np.isnan(volatility_value) or momentum_value <= 0:
				continue

			adj_momentum = momentum_value / volatility_value if volatility_value > 1e-8 else 0.0
			data_name = self.datas[index]._name
			momentum_by_name[data_name] = float(momentum_value)
			adj_momentum_by_name[data_name] = float(adj_momentum)
			if adj_momentum > 0:
				candidates.append((index, float(adj_momentum)))

		candidates.sort(key=lambda item: item[1], reverse=True)
		selected = candidates[: self.params.top_l]
		total_adj_momentum = sum(score for _, score in selected)

		if total_adj_momentum <= 0:
			return target_weights, [], adj_momentum_by_name, momentum_by_name

		selected_indices = []
		for index, score in selected:
			target_weights[index] = score / total_adj_momentum
			selected_indices.append(index)

		return target_weights, selected_indices, adj_momentum_by_name, momentum_by_name

	def _get_tradable_indices(self) -> list[int]:
		benchmark_index = self.params.benchmark_index
		return [
			index
			for index in range(len(self.datas))
			if benchmark_index is None or index != benchmark_index
		]

	def _rebalance_portfolio(self, target_weights: np.ndarray) -> None:
		total_value = self.broker.getvalue()
		threshold = total_value * self.params.min_trade_value_pct

		for index, data in enumerate(self.datas):
			target_value = total_value * target_weights[index]
			current_position = self.getposition(data).size
			current_price = data.close[0]
			current_value = current_position * current_price
			diff_value = target_value - current_value

			if abs(diff_value) <= threshold or current_price <= 0:
				continue

			size = int(diff_value / current_price)
			if size > 0:
				self.buy(data=data, size=size)
			elif size < 0:
				self.sell(data=data, size=-size)

	def _record_rebalance(
		self,
		target_weights: np.ndarray,
		selected_indices: list[int],
		adj_momentum_by_name: dict[str, float],
		momentum_by_name: dict[str, float],
	) -> None:
		target_weights_by_name = {
			data._name: float(target_weights[index]) for index, data in enumerate(self.datas)
		}
		selected_names = [self.datas[index]._name for index in selected_indices]
		selected_weights = [target_weights_by_name[name] for name in selected_names]

		self.rebalance_history.append(
			{
				"date": self.datas[0].datetime.date(0),
				"selected_names": selected_names,
				"target_weights": selected_weights,
				"target_weights_by_name": target_weights_by_name,
				"adj_momentum_by_name": adj_momentum_by_name,
				"momentum_by_name": momentum_by_name,
			}
		)
