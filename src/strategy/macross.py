import backtrader as bt

from ._base import BaseStrategy


class MaCrossStrategy(BaseStrategy):
	"""双均线交叉策略：快线上穿慢线买入，下穿卖出。"""

	_name = "MaCross"
	params = (
		("print_log", False),
		("fast_length", 10),
		("slow_length", 50)
	)

	def __init__(self) -> None:
		"""初始化收盘价引用、订单状态和快慢均线交叉指标。"""
		super().__init__()
		# 保存主数据源收盘价引用，便于记录和下单定价参考。
		self.data_closes = self.datas[0].close

		# 构造快慢两条简单移动均线，并用交叉指标判断方向。
		ma_fast = bt.ind.SMA(period=self.params.fast_length)
		ma_slow = bt.ind.SMA(period=self.params.slow_length)

		self.crossover = bt.ind.CrossOver(ma_fast, ma_slow)

	def next(self) -> None:
		"""根据快慢均线交叉信号生成买卖订单。"""
		# 记录当前收盘价，便于调试或回测日志追踪。
		self.log(f"Close, {self.data_closes[0]:.2f}")

		# 已有挂单时等待订单完成，避免重复提交。
		if self._order:
			return

		# 空仓时只响应金叉；持仓时只响应死叉。
		if not self.position:
			if self.crossover > 0:
				self.log(f"BUY CREATE, {self.data_closes[0]:.2f}")
				# 保存新建订单引用，后续由订单回调清空。
				self._order = self.buy()
		else:
			if self.crossover < 0:
				self.log(f"SELL CREATE, {self.data_closes[0]:.2f}")
				# 保存新建订单引用，后续由订单回调清空。
				self._order = self.sell()
