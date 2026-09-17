"""从 qb/small2 迁移的全市场小市值选股 Backtrader 策略。"""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd

from src.utils.qmt_universe import StockUniverseSnapshot

from ._base import BaseStrategy


class Small2PandasData(bt.feeds.PandasData):
	"""增加 ``amount`` 行的 QMT 日线数据源。"""

	lines = ("amount",)
	params = (("amount", -1),)


class Small2Strategy(BaseStrategy):
	"""按小流通市值、反转、流动性和 K 线形态评分的全市场选股策略。

	``universe_snapshot`` 必须由 :class:`QmtUniverseClient` 在回测起点或每次
	调仓日前构建；数据源名称使用 QMT 股票代码。 ``market_factors`` 为可选的
	日期索引表，列为 ``nhnl`` 与 ``limit_up_count``，用于复刻 qb 市场风控。
	"""

	_name = "Small2"
	params = (
		("stock_num", 30), ("pool_num", 100), ("min_cap", 5.0), ("max_cap", 100.0),
		("listing_days", 375), ("rebalance_days", 10), ("vol_days", 20), ("rev_days", 12),
		("amt_days", 20), ("min_amt", 7_000_000.0), ("max_price", 25.0),
		("cap_w", 0.55), ("vol_w", 0.0), ("rev_w", 0.35), ("liq_w", 0.10),
		("shape_w", 0.10), ("shape_days", 30), ("atr_days", 14), ("atr_limit", 0.1),
		("amount_z_days", 20), ("amount_z_limit", 2.0), ("pos", 1.0),
		("market_guard", True), ("guard_nhnl", -30.0), ("guard_rel", -0.010457),
		("guard_limit_up", 29), ("guard_pos", 0.3), ("guard_days", 20),
		("avoid_months", (1, 4)), ("main_board_only", True),
		("universe_snapshot", None), ("universe_snapshots", None), ("market_factors", None), ("zz1000_name", "000852.SH"),
		("hs300_name", "000300.SH"), ("min_trade_value_pct", 0.01), ("print_log", False),
	)

	def __init__(self) -> None:
		super().__init__()
		snapshot = self.params.universe_snapshot
		self.snapshots = self._normalize_snapshots(self.params.universe_snapshots)
		if not self.snapshots and not isinstance(snapshot, StockUniverseSnapshot):
			raise ValueError("Small2Strategy 需要 universe_snapshot 或按调仓日提供的 universe_snapshots")
		self.snapshot = snapshot
		self.data_by_name = {data._name: data for data in self.datas}
		self.rebalance_history: list[dict] = []
		self.market_factors = self._normalize_market_factors(self.params.market_factors)

	def next(self) -> None:
		if self.datas[0].datetime.date(0).month in self.params.avoid_months:
			self._close_all()
			return
		self._rebalance_counter += 1
		if self._rebalance_counter < self.params.rebalance_days:
			return
		self._rebalance_counter = 0

		self.snapshot = self._snapshot_for_date()
		selected, scores = self._pick()
		exposure = self._market_position() if selected else self.params.pos
		target_weights = self._target_weights(selected, exposure)
		self._rebalance(target_weights)
		self.rebalance_history.append(
			{
				"date": self.datas[0].datetime.date(0), "selected_names": selected,
				"scores": scores, "target_weights_by_name": target_weights, "exposure": exposure,
			}
		)

	def _pick(self) -> tuple[list[str], dict[str, float]]:
		codes = self.snapshot.eligible_codes(
			self.params.listing_days, self.params.min_cap, self.params.max_cap, self.params.main_board_only,
		)[: self.params.pool_num]
		rows = []
		for code in codes:
			data = self.data_by_name.get(code)
			if data is None or len(data) < self._required_bars():
				continue
			frame = self._frame(data)
			price = frame["close"].iloc[-1]
			if price > self.params.max_price or self._limit_move(frame):
				continue
			atr = self._atr_pct(frame).iloc[-1]
			if pd.isna(atr) or atr > self.params.atr_limit or self._amount_z(frame) > self.params.amount_z_limit:
				continue
			amount = frame["amount"].tail(self.params.amt_days).mean()
			if amount < self.params.min_amt:
				continue
			shape = self._ubl(frame)
			if pd.isna(shape):
				continue
			cap = self._cap(code)
			rows.append({
				"code": code, "cap": cap,
				"ret": price / frame["close"].iloc[-self.params.rev_days - 1] - 1,
				"vol": frame["close"].pct_change().tail(self.params.vol_days).std(),
				"amt": amount, "shape": shape,
			})
		if not rows:
			return [], {}
		score = pd.DataFrame(rows).set_index("code")
		score["score"] = (
			self.params.cap_w * score["cap"].rank(pct=True)
			+ self.params.vol_w * score["vol"].rank(pct=True)
			+ self.params.rev_w * score["ret"].rank(pct=True)
			+ self.params.liq_w * (-score["amt"]).rank(pct=True)
			+ self.params.shape_w * score["shape"].rank(pct=True)
		)
		selected = score.sort_values("score").head(self.params.stock_num)
		return selected.index.tolist(), selected["score"].to_dict()

	def _required_bars(self) -> int:
		return max(self.params.vol_days, self.params.rev_days + 1, self.params.amt_days, self.params.shape_days, self.params.atr_days, self.params.amount_z_days) + 1

	def _frame(self, data: bt.feed.DataBase) -> pd.DataFrame:
		count = self._required_bars()
		close = list(data.close.get(size=count))
		open_ = list(data.open.get(size=count))
		high = list(data.high.get(size=count))
		low = list(data.low.get(size=count))
		volume = list(data.volume.get(size=count))
		amount_line = getattr(data, "amount", None)
		amount = list(amount_line.get(size=count)) if amount_line is not None else [price * volume_ for price, volume_ in zip(close, volume)]
		return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": amount})

	def _cap(self, code: str) -> float:
		value = self.snapshot.stocks.loc[self.snapshot.stocks["code"] == code, "float_market_cap"]
		return float(value.iloc[0])

	@staticmethod
	def _range(frame: pd.DataFrame) -> pd.Series:
		return (frame["high"] - frame["low"]).mask(lambda value: value.eq(0))

	def _ubl(self, frame: pd.DataFrame) -> float:
		range_ = self._range(frame)
		upper = (frame["high"] - frame[["open", "close"]].max(axis=1)) / range_
		recover = (frame["close"] - frame["low"]) / range_
		return float(upper.tail(self.params.shape_days).std() + recover.tail(self.params.shape_days).mean())

	def _atr_pct(self, frame: pd.DataFrame) -> pd.Series:
		previous = frame["close"].shift(1)
		true_range = pd.concat([frame["high"] - frame["low"], (frame["high"] - previous).abs(), (frame["low"] - previous).abs()], axis=1).max(axis=1)
		return true_range.rolling(self.params.atr_days).mean() / frame["close"]

	def _amount_z(self, frame: pd.DataFrame) -> float:
		amount = frame["amount"].tail(self.params.amount_z_days)
		std = amount.std()
		return 0.0 if not math.isfinite(std) or std == 0 else float((amount.iloc[-1] - amount.mean()) / std)

	@staticmethod
	def _limit_move(frame: pd.DataFrame) -> bool:
		if len(frame) < 2:
			return True
		change = frame["close"].iloc[-1] / frame["close"].iloc[-2] - 1
		return abs(change) >= 0.095

	def _market_position(self) -> float:
		if not self.params.market_guard or self.market_factors.empty:
			return self.params.pos
		day = pd.Timestamp(self.datas[0].datetime.date(0)).normalize()
		if day not in self.market_factors.index:
			return self.params.pos
		factor = self.market_factors.loc[day]
		if factor["nhnl"] <= self.params.guard_nhnl and factor["limit_up_count"] <= self.params.guard_limit_up and self._relative_strength() <= self.params.guard_rel:
			return self.params.guard_pos
		return self.params.pos

	def _relative_strength(self) -> float:
		zz1000, hs300 = self.data_by_name.get(self.params.zz1000_name), self.data_by_name.get(self.params.hs300_name)
		if zz1000 is None or hs300 is None or len(zz1000) <= self.params.guard_days or len(hs300) <= self.params.guard_days:
			return 0.0
		return zz1000.close[0] / zz1000.close[-self.params.guard_days] - hs300.close[0] / hs300.close[-self.params.guard_days]

	def _snapshot_for_date(self) -> StockUniverseSnapshot:
		"""取当前日最近一份不晚于它的快照，避免回测读取未来股票池数据。"""
		if not self.snapshots:
			return self.snapshot
		day = pd.Timestamp(self.datas[0].datetime.date(0)).normalize()
		available = [snapshot_day for snapshot_day in self.snapshots if snapshot_day <= day]
		if not available:
			raise ValueError(f"缺少不晚于 {day.date()} 的股票池快照")
		return self.snapshots[max(available)]

	@staticmethod
	def _normalize_snapshots(value: object) -> dict[pd.Timestamp, StockUniverseSnapshot]:
		if not isinstance(value, dict):
			return {}
		return {
			pd.Timestamp(day).normalize(): snapshot
			for day, snapshot in value.items()
			if isinstance(snapshot, StockUniverseSnapshot)
		}

	@staticmethod
	def _normalize_market_factors(value: object) -> pd.DataFrame:
		if not isinstance(value, pd.DataFrame) or value.empty:
			return pd.DataFrame(columns=["nhnl", "limit_up_count"])
		frame = value.copy()
		frame.index = pd.to_datetime(frame.index).normalize()
		return frame

	def _target_weights(self, selected: list[str], exposure: float) -> dict[str, float]:
		weight = exposure / len(selected) if selected else 0.0
		return {data._name: weight if data._name in selected else 0.0 for data in self.datas}

	def _rebalance(self, target_weights: dict[str, float]) -> None:
		value, threshold = self.broker.getvalue(), self.broker.getvalue() * self.params.min_trade_value_pct
		for data in self.datas:
			weight = target_weights[data._name]
			if weight == 0 and self.getposition(data).size:
				self.close(data=data)
			elif weight > 0 and data.close[0] > 0:
				diff = value * weight - self.getposition(data).size * data.close[0]
				if abs(diff) > threshold:
					size = int(diff / data.close[0])
					if size > 0:
						self.buy(data=data, size=size)
					elif size < 0:
						self.sell(data=data, size=-size)

	def _close_all(self) -> None:
		for data in self.datas:
			if self.getposition(data).size:
				self.close(data=data)
