import backtrader as bt

from ._base import BaseStrategy


class MaStrategy(BaseStrategy):
	"""单均线择时策略：收盘价上穿均线买入，下穿均线卖出。"""

	_name = "Ma"
	params = (
		("maperiod", 15),
		("print_log", False),
	)

	def __init__(self) -> None:
		"""初始化收盘价引用、订单状态和简单移动均线指标。"""
		super().__init__()
		# 保存主数据源收盘价引用，便于在逐根推进时读取当前价格。
		self.data_closes = self.datas[0].close

		# 添加简单移动平均线指标。
		self.sma = bt.indicators.SMA(self.datas[0], period=self.params.maperiod)

	def next(self) -> None:
		"""按收盘价与均线的相对位置生成买卖信号。"""
		# 记录当前收盘价，便于调试或回测日志追踪。
		self.log(f"Close, {self.data_closes[0]:.2f}")

		# 已有挂单时等待订单完成，避免重复提交。
		if self._order:
			return

		# 空仓时等待收盘价站上均线；持仓时等待收盘价跌破均线。
		if not self.position:
			if self.data_closes[0] > self.sma[0]:
				self.log(f"BUY CREATE, {self.data_closes[0]:.2f}")
				# 保存新建订单引用，后续由订单回调清空。
				self._order = self.buy()
		else:
			if self.data_closes[0] < self.sma[0]:
				self.log(f"SELL CREATE, {self.data_closes[0]:.2f}")
				# 保存新建订单引用，后续由订单回调清空。
				self._order = self.sell()
