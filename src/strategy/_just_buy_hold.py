"""
基准策略: 买入持有 (Just Buy and Hold)
------------------------------
"""

from ._base import BaseStrategy

class JustBuyHoldStrategy(BaseStrategy):
	"""买入持有策略"""

	_name = "JustBuyHold"
	params = (
		("print_log", False),
	)

	def __init__(self):
		"""初始化订单引用和是否已买入的状态。"""
		super().__init__()

	def notify_order(self, order):
		"""处理买入订单通知，并在成交后标记已建仓。"""
		if order.status in [order.Completed]:
			if order.isbuy():
				self.log(f'买入执行, 价格: {order.executed.price:.2f}, '
						 f'数量: {order.executed.size:.2f}, '
						 f'手续费: {order.executed.comm:.2f}')
				self._bought = True
		elif order.status in [order.Canceled, order.Margin, order.Rejected]:
			self.log(f'订单被取消/拒绝: {order.status}')

		self._order = None

	def next(self):
		"""在尚未持仓时使用大部分现金一次性买入。"""
		# 避免重复下单
		if self._order:
			return

		# 只在未买入时执行
		if not self._bought:
			# 获取当前可用资金
			cash = self.broker.getcash()
			price = self.datas[0].close[0]

			# 计算可买入数量（预留1%资金用于手续费）
			size = int((cash * 0.99) / price)

			if size > 0:
				self._order = self.buy(size=size)
				self.log(f'提交买单, 价格: {price:.2f}, 数量: {size}')
			else:
				self.log(f'资金不足，无法买入 (现金: {cash:.2f}, 价格: {price:.2f})')

	def log(self, txt, dt=None, do_print=False):
		"""日志函数"""
		if self.params.print_log or do_print:
			dt = dt or self.datas[0].datetime.date(0)
			print(f'{dt.isoformat()} {txt}')
