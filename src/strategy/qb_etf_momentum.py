"""从 qb/etf_mom 迁移的短周期 ETF ROC 轮动策略。"""

from __future__ import annotations

import math

import backtrader as bt

from ._base import BaseStrategy


class QbEtfMomentumStrategy(BaseStrategy):
	"""按短周期 ROC 排名，等权持有前 N 个 ETF。

	该策略保留 qb ``ETFMomStrategy`` 的核心逻辑：按周调仓、选取 ROC
	最高的 ``top_n`` 个标的，以及绝对动量和防御资产领导力的仓位门控。
	qb 原实现依赖其运行时 NHNL CSV；当前项目没有对应的全市场数据输入，
	因此未迁移 NHNL 相关门控。
	"""

	_name = "QbEtfMomentum"
	params = (
		("period", 5),
		("rebalance_weekday", 1),
		("top_n", 5),
		("total_exposure", 1.0),
		("high_return_mode", False),
		("abs_zero_exposure", 0.1),
		("abs_weak_exposure", 0.3),
		("abs_positive_count_threshold", 2),
		("abs_top1_threshold", -0.03),
		("defensive_exposure", 0.0),
		("defensive_count_threshold", 4),
		("defensive_topn_mean_max", 0.08),
		("min_trade_value_pct", 0.01),
		("print_log", False),
	)

	DEFENSIVE_SYMBOLS = frozenset(
		{
			"518880", "159934", "510880", "512800", "511090", "511880",
			"511360", "159001", "511990", "511380", "159396", "511520",
			"511260", "159816", "511100",
		}
	)

	def __init__(self) -> None:
		super().__init__()
		if self.params.period < 1:
			raise ValueError("period 必须大于 0")
		if not 1 <= self.params.rebalance_weekday <= 5:
			raise ValueError("rebalance_weekday 必须在 1~5 之间（周一至周五）")
		if self.params.top_n < 1:
			raise ValueError("top_n 必须大于 0")
		if not 0.0 <= self.params.total_exposure <= 1.0:
			raise ValueError("total_exposure 必须在 0~1 之间")

		self.rebalance_history: list[dict] = []

	def next(self) -> None:
		"""在指定工作日按当前收盘价计算 ROC，并提交目标仓位。"""
		if len(self.datas[0]) <= self.params.period:
			return
		if self.datas[0].datetime.date(0).isoweekday() != self.params.rebalance_weekday:
			return

		roc_by_name = self._calculate_roc()
		if len(roc_by_name) < self.params.top_n:
			return

		ranked = sorted(roc_by_name.items(), key=lambda item: item[1], reverse=True)
		top_items = ranked[: self.params.top_n]
		exposure = self._target_exposure(top_items)
		target_weights = self._build_target_weights(top_items, exposure)
		self._rebalance_portfolio(target_weights)
		self._record_rebalance(roc_by_name, top_items, target_weights, exposure)

	def _calculate_roc(self) -> dict[str, float]:
		"""计算每个数据源当前收盘价相对于 ``period`` 根 K 线前的收益率。"""
		roc_by_name: dict[str, float] = {}
		for data in self.datas:
			current_close = data.close[0]
			previous_close = data.close[-self.params.period]
			if (
				not math.isfinite(current_close)
				or not math.isfinite(previous_close)
				or previous_close <= 0
			):
				continue
			roc_by_name[data._name] = float(current_close / previous_close - 1.0)
		return roc_by_name

	def _target_exposure(self, top_items: list[tuple[str, float]]) -> float:
		"""应用 qb 的绝对动量与防御资产领导力仓位门控。"""
		exposure = self.params.total_exposure
		if self.params.high_return_mode:
			return exposure

		top_rocs = [roc for _, roc in top_items]
		positive_count = sum(roc > 0 for roc in top_rocs)
		if top_rocs[0] <= self.params.abs_top1_threshold:
			exposure = min(exposure, self.params.total_exposure * self.params.abs_zero_exposure)
		elif positive_count < self.params.abs_positive_count_threshold:
			exposure = min(exposure, self.params.total_exposure * self.params.abs_weak_exposure)

		defensive_count = sum(self._symbol_from_name(name) in self.DEFENSIVE_SYMBOLS for name, _ in top_items)
		mean_roc = sum(top_rocs) / len(top_rocs)
		if (
			defensive_count >= self.params.defensive_count_threshold
			and mean_roc <= self.params.defensive_topn_mean_max
		):
			exposure = min(exposure, self.params.total_exposure * self.params.defensive_exposure)
		return exposure

	@staticmethod
	def _symbol_from_name(name: str) -> str:
		"""兼容 ``518880``、``518880.SH`` 等数据源命名。"""
		return name.split(".", maxsplit=1)[0]

	def _build_target_weights(self, top_items: list[tuple[str, float]], exposure: float) -> dict[str, float]:
		weight = exposure / len(top_items)
		selected = {name for name, _ in top_items}
		return {data._name: weight if data._name in selected else 0.0 for data in self.datas}

	def _rebalance_portfolio(self, target_weights: dict[str, float]) -> None:
		"""先卖出非目标持仓，再将入选标的调整为目标权重。"""
		total_value = self.broker.getvalue()
		if not math.isfinite(total_value) or total_value <= 0:
			return
		threshold = total_value * self.params.min_trade_value_pct

		for data in self.datas:
			if target_weights[data._name] == 0.0 and self.getposition(data).size:
				self.close(data=data)

		for data in self.datas:
			price = data.close[0]
			if not math.isfinite(price) or price <= 0:
				continue
			current_value = self.getposition(data).size * price
			target_value = total_value * target_weights[data._name]
			difference = target_value - current_value
			if abs(difference) <= threshold:
				continue
			size = int(difference / price)
			if size > 0:
				self.buy(data=data, size=size)
			elif size < 0 and target_weights[data._name] > 0.0:
				self.sell(data=data, size=-size)

	def _record_rebalance(
		self,
		roc_by_name: dict[str, float],
		top_items: list[tuple[str, float]],
		target_weights: dict[str, float],
		exposure: float,
	) -> None:
		selected_names = [name for name, _ in top_items]
		self.rebalance_history.append(
			{
				"date": self.datas[0].datetime.date(0),
				"selected_names": selected_names,
				"roc_by_name": roc_by_name,
				"target_weights_by_name": target_weights,
				"target_weights": [target_weights[data._name] for data in self.datas],
				"exposure": exposure,
			}
		)
