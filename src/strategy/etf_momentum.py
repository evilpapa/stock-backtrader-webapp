"""
ETF动量轮动策略 (Python版本)
基于风险调整动量的多资产轮动策略

原始策略来源: strategy/etf_momentum/strategy.r
R包到Python包的映射:
- quantmod → QMT 数据服务和 QMT 数据客户端 (金融数据获取)
- PerformanceAnalytics → 外部性能指标库和自定义计算 (绩效分析)
- dplyr/tidyr → pandas (数据处理)
- ggplot2/patchwork → matplotlib (绘图)

策略逻辑:
1. 计算每个ETF的20日动量（平均收益率）
2. 计算20日波动率（标准差）
3. 计算风险调整动量 = 动量 / 波动率
4. 只选择风险调整动量 > 0 的ETF
5. 按风险调整动量大小分配权重（归一化）
"""

import backtrader as bt
import numpy as np
import pandas as pd

from ._base import BaseStrategy

class EtfMomentumStrategy(BaseStrategy):
	"""
	ETF动量轮动策略

	基于风险调整动量的多资产轮动策略，适用于多ETF回测。
	策略会根据每个ETF的风险调整动量动态分配权重。

	参数:
	- momentum_window: 动量计算窗口（默认20天）
	- rebalance_days: 再平衡频率（默认每日）
	- print_log: 是否打印日志
	"""

	_name = "EtfMomentum"
	params = (
		("momentum_window", 5),  # 动量计算窗口
		("rebalance_days", 1),  # 再平衡频率（天）
		("print_log", False),  # 是否输出策略运行日志
	)

	def __init__(self):
		"""初始化每个 ETF 的收益率、动量、波动率和调仓状态。"""
		super().__init__()

		# 用于存储每个数据源的指标
		self.returns = []
		self.momentum = []  # 动量（平均收益率）
		self.volatility = []  # 波动率（收益率标准差）
		self.adj_momentum = []  # 风险调整动量

		# 订单追踪
		self.rebalance_history = []

		# 追踪所有数据源
		self.dataclose = [d.close for d in self.datas]

		# 为每个数据源计算收益率
		for data in self.datas:
			# 计算日收益率
			ret = bt.indicators.PctChange(data.close, period=1)
			self.returns.append(ret)

		# 原示例未单独遍历收益率列表，这里沿用当前缩进结构。
			# 计算滚动平均收益率（动量）
			self.momentum.append(
				bt.indicators.SimpleMovingAverage(ret, period=self.p.momentum_window)
			)
			# 计算滚动标准差（波动率）
			self.volatility.append(
				bt.indicators.StandardDeviation(ret, period=self.p.momentum_window)
			)

		self.log("ETF动量策略初始化完成", do_print=True)
		self.log(f"参数: 动量窗口={self.p.momentum_window}, "
				 f"再平衡频率={self.p.rebalance_days}天", do_print=True)

	def next(self):
		"""每个交易日检查是否需要再平衡，并计算目标 ETF 权重。"""
		if self._has_pending_orders():
			return
		if any(len(data) < self.p.momentum_window for data in self.datas):
			return

		# 检查是否到达再平衡日
		self.rebalance_counter += 1
		if self.rebalance_counter < self.p.rebalance_days:
			return

		# 重置计数器
		self.rebalance_counter = 0

		# 检查是否有足够的数据

		# 计算所有标的的风险调整动量
		adj_momentum_values = []
		for i in range(len(self.datas)):
			if len(self.momentum[i]) > 0 and len(self.volatility[i]) > 0:
				momentum = self.momentum[i][0]
				volatility = self.volatility[i][0]

				if np.isnan(momentum) or np.isnan(volatility):
					adj_momentum_values.append(0.0)
					continue

				# 计算风险调整动量 = 动量 / 波动率，避免除以零
				adj_momentum_values.append(momentum / volatility if volatility > 1e-8 else 0.0)
			else:
				adj_momentum_values.append(0.0)

		# 筛选风险调整动量大于零的标的
		positive_indices = [i for i, v in enumerate(adj_momentum_values) if v > 0]

		# 计算目标权重
		target_weights = np.zeros(len(self.datas))

		if positive_indices:
			# 获取正的风险调整动量值
			positive_momentum = np.array([adj_momentum_values[i] for i in positive_indices])

			# 归一化权重
			total_momentum = np.sum(positive_momentum)
			if total_momentum > 0:
				normalized_weights = positive_momentum / total_momentum

				# 分配权重
				for i, weight in zip(positive_indices, normalized_weights):
					target_weights[i] = weight

		# 执行再平衡
		self._rebalance_portfolio(target_weights)
		self.rebalance_history.append(
			{"date": self.datas[0].datetime.date(0), "weights": target_weights.copy()}
		)

		# 记录权重信息
		if self.p.print_log:
			weight_info = ", ".join([f"ETF{i}: {w:.2%}" for i, w in enumerate(target_weights)])
			self.log(f"再平衡权重: {weight_info}")

	def _rebalance_portfolio(self, target_weights: pd.Series | np.ndarray) -> None:
		"""
		根据目标权重调整持仓

		参数:
			target_weights: 每个ETF的目标权重数组
		"""
		total_value = self.broker.getvalue()
		if not np.isfinite(total_value) or total_value <= 0:
			return

		for i, data in enumerate(self.datas):
			target_weight = target_weights[i]
			target_value = total_value * target_weight

			# 计算当前持仓价值
			current_position = self.getposition(data).size
			current_price = data.close[0]
			if not np.isfinite(current_price) or current_price <= 0:
				continue
			current_value = current_position * current_price

			# 计算需要调整的价值
			diff_value = target_value - current_value

			# 如果差异超过阈值，则进行调整
			threshold = total_value * 0.01  # 1%的阈值

			if abs(diff_value) > threshold:
				# 计算需要买入或卖出的股数
				size = int(diff_value / current_price)

				if size > 0:
					self.log(f"ETF{i} 买入: {size}股 @ {current_price:.2f}")
					self._track_order(self.buy(data=data, size=size))
				elif size < 0:
					self.log(f"ETF{i} 卖出: {-size}股 @ {current_price:.2f}")
					self._track_order(self.sell(data=data, size=-size))

	def notify_order(self, order):
		"""复用基类的订单状态机和成交记录。"""
		super().notify_order(order)

	def stop(self):
		"""策略结束时输出关键参数和期末资产。"""
		self.log(
			f"(ETF动量策略 动量窗口={self.p.momentum_window}) "
			f"期末价值 {self.broker.getvalue():.2f}",
			do_print=True
		)
