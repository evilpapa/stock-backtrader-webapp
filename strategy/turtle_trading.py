from __future__ import annotations

import math

import backtrader as bt

from .base import BaseStrategy


class TurtleTradingStrategy(BaseStrategy):
	"""经典海龟核心规则策略。"""

	_name = "TurtleTrading"
	params = (
		("entry_period", 20),
		("exit_period", 10),
		("atr_period", 20),
		("max_units", 4),
		("risk_pct", 0.01),
		("add_unit_atr", 0.5),
		("stop_atr", 2.0),
		("allow_short", True),
		("lot_size", 100),
		("printlog", False),
	)

	def __init__(self) -> None:
		super().__init__()
		self.dataclose = self.datas[0].close
		self.order: bt.OrderBase | None = None
		self.pending_order_meta: dict[str, float | int | str] | None = None
		self.buyprice = None
		self.buycomm = None
		self.unit_count = 0
		self.last_entry_price: float | None = None
		self.stop_price: float | None = None
		self.trade_log: list[dict[str, float | int | str]] = []
		self.value_history: list[dict[str, float | object]] = []

		self.entry_high = bt.ind.Highest(self.datas[0].high(-1), period=self.params.entry_period)
		self.entry_low = bt.ind.Lowest(self.datas[0].low(-1), period=self.params.entry_period)
		self.exit_high = bt.ind.Highest(self.datas[0].high(-1), period=self.params.exit_period)
		self.exit_low = bt.ind.Lowest(self.datas[0].low(-1), period=self.params.exit_period)
		self.atr = bt.ind.AverageTrueRange(self.datas[0], period=self.params.atr_period)
		self.min_bars = max(self.params.entry_period, self.params.exit_period, self.params.atr_period) + 1

	def next(self) -> None:
		self.value_history.append(
			{
				"date": self.datas[0].datetime.date(0),
				"value": float(self.broker.getvalue()),
				"close": float(self.dataclose[0]),
				"position": int(self.position.size),
			}
		)
		self.log(f"Close, {self.dataclose[0]:.2f}")

		if len(self) < self.min_bars or self.order or math.isnan(self.atr[0]) or self.atr[0] <= 0:
			return

		if not self.position:
			self._handle_entry()
			return

		if self.position.size > 0:
			self._handle_long_position()
			return

		self._handle_short_position()

	def notify_order(self, order: bt.OrderBase) -> None:
		super().notify_order(order)
		if order.status in [order.Canceled, order.Margin, order.Rejected]:
			self.pending_order_meta = None
			return

		if order.status != order.Completed:
			return

		if self.pending_order_meta:
			if self.pending_order_meta["type"] == "entry":
				self.unit_count += 1
				self.last_entry_price = float(order.executed.price)
				stop_offset = float(self.pending_order_meta["atr"]) * self.params.stop_atr
				direction = int(self.pending_order_meta["direction"])
				self.stop_price = (
					self.last_entry_price - stop_offset
					if direction > 0
					else self.last_entry_price + stop_offset
				)
			else:
				self.unit_count = 0
				self.last_entry_price = None
				self.stop_price = None

		action = "BUY" if order.isbuy() else "SELL"
		self.trade_log.append(
			{
				"date": self.datas[0].datetime.date(0).isoformat(),
				"action": action,
				"price": float(order.executed.price),
				"size": int(order.executed.size),
				"units": int(self.unit_count),
				"position": int(self.position.size),
			}
		)
		self.pending_order_meta = None

	def _handle_entry(self) -> None:
		long_breakout = self.datas[0].high[0] > self.entry_high[0]
		short_breakout = self.datas[0].low[0] < self.entry_low[0]

		if long_breakout and short_breakout:
			self.log("ENTRY SKIPPED, ambiguous breakout bar")
			return

		unit_size = self._calculate_unit_size()
		if unit_size <= 0:
			self.log("ENTRY SKIPPED, unit size is 0")
			return

		if long_breakout:
			self._submit_entry(size=unit_size, direction=1)
		elif short_breakout and self.params.allow_short:
			self._submit_entry(size=unit_size, direction=-1)

	def _handle_long_position(self) -> None:
		if self.stop_price is not None and self.datas[0].low[0] <= self.stop_price:
			self.log(f"LONG STOP EXIT, {self.dataclose[0]:.2f}")
			self._submit_flatten()
			return

		if self.datas[0].low[0] < self.exit_low[0]:
			self.log(f"LONG CHANNEL EXIT, {self.dataclose[0]:.2f}")
			self._submit_flatten()
			return

		if self.unit_count >= self.params.max_units or self.last_entry_price is None:
			return

		add_price = self.last_entry_price + self.params.add_unit_atr * self.atr[0]
		if self.datas[0].high[0] >= add_price:
			unit_size = self._calculate_unit_size()
			if unit_size > 0:
				self.log(f"LONG PYRAMID ADD, {self.dataclose[0]:.2f}")
				self._submit_entry(size=unit_size, direction=1)

	def _handle_short_position(self) -> None:
		if self.stop_price is not None and self.datas[0].high[0] >= self.stop_price:
			self.log(f"SHORT STOP EXIT, {self.dataclose[0]:.2f}")
			self._submit_flatten()
			return

		if self.datas[0].high[0] > self.exit_high[0]:
			self.log(f"SHORT CHANNEL EXIT, {self.dataclose[0]:.2f}")
			self._submit_flatten()
			return

		if self.unit_count >= self.params.max_units or self.last_entry_price is None:
			return

		add_price = self.last_entry_price - self.params.add_unit_atr * self.atr[0]
		if self.datas[0].low[0] <= add_price:
			unit_size = self._calculate_unit_size()
			if unit_size > 0:
				self.log(f"SHORT PYRAMID ADD, {self.dataclose[0]:.2f}")
				self._submit_entry(size=unit_size, direction=-1)

	def _submit_entry(self, size: int, direction: int) -> None:
		if direction > 0:
			self.log(f"BUY CREATE, {self.dataclose[0]:.2f}")
			self.order = self.buy(size=size)
		else:
			self.log(f"SELL CREATE, {self.dataclose[0]:.2f}")
			self.order = self.sell(size=size)

		self.pending_order_meta = {
			"type": "entry",
			"direction": direction,
			"atr": float(self.atr[0]),
		}

	def _submit_flatten(self) -> None:
		self.order = self.close()
		self.pending_order_meta = {"type": "exit"}

	def _calculate_unit_size(self) -> int:
		capital_at_risk = self.broker.getvalue() * self.params.risk_pct
		raw_size = capital_at_risk / self.atr[0]
		unit_size = int(raw_size)
		lot_size = max(int(self.params.lot_size), 1)
		if lot_size > 1:
			unit_size = (unit_size // lot_size) * lot_size
		return max(unit_size, 0)
