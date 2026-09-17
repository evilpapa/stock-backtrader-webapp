"""
共享的风险调整动量轮动基类。
"""

import backtrader as bt
import numpy as np

from ._base import BaseStrategy


class RotationStrategyBase(BaseStrategy):
	"""风险调整动量轮动策略的公共实现。"""

	params = (
		("momentum_window", 20),
		("rebalance_days", 5),
		("top_l", 5),
		("benchmark_index", None),
		("min_trade_value_pct", 0.01),
		("print_log", False),
	)

	def __init__(self):
		"""为所有数据源初始化收益率、动量、波动率和调仓记录。"""
		super().__init__()
		self.data_closes = [data.close for data in self.datas]
		self.returns = []
		self.momentum = []
		self.volatility = []
		self.rebalance_history = []

		# 每个数据源独立计算收益率、平均收益率和波动率。
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
		"""按设定频率计算目标权重，并执行一次组合再平衡。"""
		self._rebalance_counter += 1
		if self._rebalance_counter < self.params.rebalance_days:
			return
		self._rebalance_counter = 0

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
		"""筛选正动量标的，并按风险调整动量归一化为目标权重。"""
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

			# 用波动率惩罚原始动量，波动率过低时避免除零。
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
		"""返回可交易数据源索引，排除可选的基准指数。"""
		benchmark_index = self.params.benchmark_index
		return [
			index
			for index in range(len(self.datas))
			if benchmark_index is None or index != benchmark_index
		]

	def _rebalance_portfolio(self, target_weights: np.ndarray) -> None:
		"""根据目标权重买入或卖出，使组合接近目标配置。"""
		total_value = self.broker.getvalue()
		threshold = total_value * self.params.min_trade_value_pct

		for index, data in enumerate(self.datas):
			# 用当前市值和目标市值差计算调整股数，小额偏差不交易。
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
		"""记录本次调仓日期、入选标的、目标权重和动量数据。"""
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
