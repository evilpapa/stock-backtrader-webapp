import backtrader as bt
import numpy as np

# ==================== 回测分析器 ====================
class CustomAnalyzer(bt.Analyzer):
	"""自定义分析器，记录每日收益率"""

	def __init__(self):
		self.returns = []
		self.dates = []
		self.values = []

	def next(self):
		self.dates.append(self.datas[0].datetime.date(0))
		self.values.append(self.strategy.broker.getvalue())

	def stop(self):
		# 计算收益率
		values_array = np.array(self.values)
		returns_array = np.diff(values_array) / values_array[:-1]

		self.returns = returns_array
		self.dates = self.dates[1:]  # 去掉第一个日期

