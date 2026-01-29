import backtrader as bt

# ==================== 基准策略: 买入持有 ====================
class JustBuyHoldStrategy(bt.Strategy):
	"""买入持有策略"""
	def __init__(self):
		self.bought = False

	def next(self):
		if not self.bought:
			# 使用所有资金买入
			cash = self.broker.getcash()
			size = int(cash / self.datas[0].close[0])
			self.buy(size=size)
			self.bought = True
