from .base import BaseStrategy

# ==================== 基准策略: 等权持有 ====================
class EqualWeightStrategy(BaseStrategy):
	"""等权重组合策略"""

	_name = "EqualWeight"
	params = (
		("printlog", False),
	)

	def __init__(self):
		self.rebalance_counter = 0
		self.bought = False

	def next(self):
		if not self.bought:
			# 初始买入：等权重分配
			total_value = self.broker.getvalue()
			for data in self.datas:
				target_value = total_value / len(self.datas)
				size = int(target_value / data.close[0])
				self.buy(data=data, size=size)
			self.bought = True
