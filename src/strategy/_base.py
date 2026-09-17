from typing import Optional

import backtrader as bt

from src.utils.logs import logger


class BaseStrategy(bt.Strategy):
	"""所有 Backtrader 策略共享的基础策略。"""

	_name = "base"
	# ``params`` 是 Backtrader 的参数注册接口，不能改为私有名称。
	params = (("print_log", False),)

	def __init__(self):
		"""初始化订单、成交价格和手续费等通用状态。"""
		self._bar_executed = None
		self._buy_comm = None
		self._buy_price = None
		self._order = None
		self._bought = False
		self._rebalance_counter = 0

	def log(self, txt: str, dt: Optional[bt.datetime.date] = None, do_print: bool = False) -> None:
		"""按策略配置输出带交易日期的日志。"""
		if self.params.print_log or do_print:
			dt = dt or self.datas[0].datetime.date(0)
			logger.info("%s, %s" % (dt.isoformat(), txt))

	def notify_order(self, order: bt.OrderBase) -> None:
		"""处理订单生命周期通知，并记录成交价、手续费和订单状态。"""
		if order.status in [order.Submitted, order.Accepted]:
			# 订单已提交或已被经纪商接受，等待后续成交结果。
			return

		# 订单完成时记录成交信息；现金不足等情况可能导致订单被拒绝。
		if order.status in [order.Completed]:
			if order.isbuy():
				self.log(
					"BUY EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f"
					% (order.executed.price, order.executed.value, order.executed.comm)
				)

				self._buy_price = order.executed.price
				self._buy_comm = order.executed.comm
			else:  # 卖单成交
				self.log(
					"SELL EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f"
					% (order.executed.price, order.executed.value, order.executed.comm)
				)

			self._bar_executed = len(self)

		elif order.status in [order.Canceled, order.Margin, order.Rejected]:
			self.log("Order Canceled/Margin/Rejected")

		# 当前订单已进入终态，清空挂单引用。
		self._order = None

	def notify_trade(self, trade: bt.Trade) -> None:
		"""在交易闭合后记录毛利润和扣费后净利润。"""
		if not trade.isclosed:
			return

		self.log("OPERATION PROFIT, GROSS %.2f, NET %.2f" % (trade.pnl, trade.pnlcomm))

	def next(self) -> None:
		"""每根 K 线推进时的默认空实现，子类按策略逻辑覆盖。"""
		pass

	def stop(self) -> None:
		"""回测结束时输出策略参数和期末资产。"""
		params = [f"{k}_{v}" for k, v in self.params._getkwargs().items() if k != "print_log"]
		self.log(
			"(%s %s) Ending Value %.2f" % (self._name, " ".join(params), self.broker.getvalue()),
			do_print=True,
		)
