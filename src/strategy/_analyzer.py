import backtrader as bt
import numpy as np

# ==================== 回测分析器 ====================
class CustomAnalyzer(bt.Analyzer):
	"""自定义分析器，记录每日收益率"""

	def __init__(self):
		"""初始化每日日期、账户价值和收益率缓存。"""
		self.returns = []
		self.dates = []
		self.values = []

	def next(self):
		"""在每个交易日记录当前账户总价值。"""
		self.dates.append(self.datas[0].datetime.date(0))
		self.values.append(self.strategy.broker.getvalue())

	def stop(self):
		"""回测结束时根据账户价值序列计算每日收益率。"""
		values_array = np.array(self.values)
		returns_array = np.diff(values_array) / values_array[:-1]

		self.returns = returns_array
		self.dates = self.dates[1:]  # 去掉第一个日期

