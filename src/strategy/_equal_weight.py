from ._base import BaseStrategy

# ==================== 基准策略: 等权持有 ====================
class EqualWeightStrategy(BaseStrategy):
	"""等权重组合策略"""

	_name = "EqualWeight"
	params = (
		("print_log", False),  # 是否输出策略运行日志
	)

	def __init__(self):
		"""初始化一次性买入标记。"""
		super().__init__()

	def next(self):
		"""首个可交易日按等权方式买入所有数据源。"""
		if self.bought or self._has_pending_orders():
			return
		# 预留现金缓冲，避免次日成交价或佣金导致后续等权订单被拒绝。
		target_weight = 0.99 / len(self.datas)
		for data in self.datas:
			if data.close[0] > 0:
				self._track_order(self.order_target_percent(data=data, target=target_weight))
		self.bought = True
