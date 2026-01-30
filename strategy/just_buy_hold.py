import backtrader as bt

# ==================== 基准策略: 买入持有 ====================
class JustBuyHoldStrategy(bt.Strategy):
	"""买入持有策略"""

	def __init__(self):
		self.order = None  # 跟踪订单状态
		self.bought = False

	def notify_order(self, order):
		"""订单状态通知"""
		if order.status in [order.Completed]:
			if order.isbuy():
				self.log(f'买入执行, 价格: {order.executed.price:.2f}, '
						 f'数量: {order.executed.size:.2f}, '
						 f'手续费: {order.executed.comm:.2f}')
				self.bought = True
		elif order.status in [order.Canceled, order.Margin, order.Rejected]:
			self.log(f'订单被取消/拒绝: {order.status}')

		self.order = None

	def next(self):
		# 避免重复下单
		if self.order:
			return

		# 只在未买入时执行
		if not self.bought:
			# 获取当前可用资金
			cash = self.broker.getcash()
			price = self.datas[0].close[0]

			# 计算可买入数量（预留1%资金用于手续费）
			size = int((cash * 0.99) / price)

			if size > 0:
				self.order = self.buy(size=size)
				self.log(f'提交买单, 价格: {price:.2f}, 数量: {size}')
			else:
				self.log(f'资金不足，无法买入 (现金: {cash:.2f}, 价格: {price:.2f})')

	def log(self, txt, dt=None):
		"""日志函数"""
		dt = dt or self.datas[0].datetime.date(0)
		print(f'{dt.isoformat()} {txt}')
