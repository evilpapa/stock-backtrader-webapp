from ._base import BaseStrategy

# ==================== 基准策略: 等权持有 ====================
class EqualWeightStrategy(BaseStrategy):
	"""等权重组合策略"""

	_name = "EqualWeight"
	params = (
		("print_log", False),
	)

	def __init__(self):
		"""初始化一次性买入标记。"""
		super().__init__()

	def next(self):
		"""首个可交易日按等权方式买入所有数据源。"""
		if not self._bought:
			# 初始买入：等权重分配
			total_value = self.broker.getvalue()
			for data in self.datas:
				target_value = total_value / len(self.datas)
				size = int(target_value / data.close[0])
				self.buy(data=data, size=size)
			self._bought = True
