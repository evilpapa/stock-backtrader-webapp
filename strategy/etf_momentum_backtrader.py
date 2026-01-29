import backtrader as bt
import numpy as np


# ==================== Backtrader策略 ====================
class EtfMomentumSBacktrader(bt.Strategy):
	"""ETF动量轮动策略"""

	params = (
		("momentum_window", 20),
		("printlog", False),
	)

	def __init__(self):
		# 为每个数据源计算收益率和指标
		self.returns = []
		self.momentum = []
		self.volatility = []

		for data in self.datas:
			ret = bt.indicators.PctChange(data.close, period=1)
			self.returns.append(ret)

			momentum = bt.indicators.SimpleMovingAverage(
				ret, period=self.params.momentum_window
			)
			self.momentum.append(momentum)

			volatility = bt.indicators.StandardDeviation(
				ret, period=self.params.momentum_window
			)
			self.volatility.append(volatility)

		self.rebalance_counter = 0
		self.trade_log = []  # 用于记录交易日志

	def next(self):
		"""每个交易日执行"""
		# 每日再平衡
		self.rebalance_counter += 1
		if self.rebalance_counter < 1:  # 每日
			return

		self.rebalance_counter = 0

		# 检查数据充足性
		if len(self.datas[0]) < self.params.momentum_window:
			return

		# 计算风险调整动量
		adj_momentum_values = []
		for i in range(len(self.datas)):
			if len(self.momentum[i]) > 0 and len(self.volatility[i]) > 0:
				mom = self.momentum[i][0]
				vol = self.volatility[i][0]
				adj_mom = mom / vol if vol > 1e-8 else 0.0
				adj_momentum_values.append(adj_mom)
			else:
				adj_momentum_values.append(0.0)

		# 筛选正动量ETF并计算权重
		positive_indices = [i for i, v in enumerate(adj_momentum_values) if v > 0]
		target_weights = np.zeros(len(self.datas))

		if len(positive_indices) > 0:
			positive_momentum = np.array([adj_momentum_values[i] for i in positive_indices])
			total_momentum = np.sum(positive_momentum)

			if total_momentum > 0:
				normalized_weights = positive_momentum / total_momentum
				for idx, weight in zip(positive_indices, normalized_weights):
					target_weights[idx] = weight

		# 执行再平衡
		self._rebalance_portfolio(target_weights)

		# 记录权重
		self.trade_log.append({
			'date': self.datas[0].datetime.date(0),
			'weights': target_weights.copy()
		})

	def _rebalance_portfolio(self, target_weights):
		"""根据目标权重调整持仓"""
		total_value = self.broker.getvalue()

		for i, data in enumerate(self.datas):
			target_weight = target_weights[i]
			target_value = total_value * target_weight

			current_position = self.getposition(data).size
			current_price = data.close[0]
			current_value = current_position * current_price

			diff_value = target_value - current_value
			threshold = total_value * 0.01

			if abs(diff_value) > threshold:
				size = int(diff_value / current_price)
				if size > 0:
					self.buy(data=data, size=size)
				elif size < 0:
					self.sell(data=data, size=-size)
