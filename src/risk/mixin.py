"""把风控引擎接入 Backtrader 策略的通用混入。

设计目标：策略作者不需要在 :meth:`next` 里书写任何风控代码。混入会在子类
定义时包装 ``next``，让风控在每个交易日、策略逻辑执行之前完成评估:

* 组合回撤熔断 -> 清空所有持仓并进入冷却期；
* 标的止损/止盈 -> 平掉对应标的，并在冷却期内拒绝回补；
* 熔断/单日亏损限制 -> 直接拦截 ``buy`` 调用；
* 波动率目标、总仓位与单标的上限 -> 通过 :meth:`apply_risk_weights` 裁剪
  轮动策略计算出的目标权重。

包装只发生在子类自己定义 ``next`` 的时候，因此不会重复包装同一个方法。
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import backtrader as bt

from src.utils.logs import logger

from .manager import AssetSnapshot, PortfolioSnapshot, RiskDecision, RiskEvent, RiskManager


def _wrap_hook(func: Any, hook: str) -> Any:
	"""为策略钩子包一层风控前置检查。"""

	@functools.wraps(func)
	def _risk_hook(self: "RiskControlMixin", *args: Any, **kwargs: Any) -> Any:
		if self._risk_before_bar(in_open=hook == "next_open"):
			return None
		return func(self, *args, **kwargs)

	setattr(_risk_hook, "__risk_control__", True)  # 标记已包装，避免重复套娃
	return _risk_hook


class RiskControlMixin:
	"""为 Backtrader 策略提供统一风控能力的混入类。"""

	if TYPE_CHECKING:  # 这些成员由 BaseStrategy / Backtrader 提供，仅用于类型检查
		p: Any
		datas: Any
		broker: Any

		def __len__(self) -> int: ...

		def getposition(self, *args: Any, **kwargs: Any) -> Any: ...

		def _track_order(self, *args: Any, **kwargs: Any) -> Any: ...

		def close(self, *args: Any, **kwargs: Any) -> Any: ...

		def log(self, *args: Any, **kwargs: Any) -> None: ...


	def __init_subclass__(cls, **kwargs: Any) -> None:
		"""在子类定义时包装 ``next`` / ``next_open``，让风控先于策略逻辑执行。"""
		super().__init_subclass__(**kwargs)
		for hook in ("next", "next_open"):
			func = cls.__dict__.get(hook)
			if func is None or getattr(func, "__risk_control__", False):
				continue
			wrapped = _wrap_hook(func, hook)
			setattr(cls, hook, wrapped)

	# ------------------------------------------------------------------ 初始化
	def _init_risk_control(self) -> None:
		"""由 :class:`BaseStrategy` 在 ``__init__`` 中调用。"""
		self.risk = RiskManager(getattr(self.p, "risk_config", None))
		self._risk_decision = RiskDecision()
		self._risk_disabled = False
		self._risk_blocked_buy_count = 0
		self._risk_last_block_bar = -1
		self._risk_last_eval_bar = -1
		self._risk_skip_bar = False
		self._risk_in_open = False

	# ------------------------------------------------------------------ 每日流程
	def _risk_before_bar(self, in_open: bool = False) -> bool:
		"""评估当日风控，返回 True 表示跳过当日策略逻辑。"""
		risk = getattr(self, "risk", None)
		if risk is None or not risk.enabled or self._risk_disabled:
			return False

		bar = len(self)
		# 同一根 K 线可能先后触发 next_open 与 next，只评估一次。
		if bar == self._risk_last_eval_bar:
			return self._risk_skip_bar
		self._risk_last_eval_bar = bar
		self._risk_in_open = in_open

		try:
			decision = risk.evaluate(self._risk_snapshot(), bar=bar)
		except Exception:  # 风控异常不应打断整个回测，但必须留下明确记录
			logger.exception("风控评估失败，后续交易日将跳过风控")
			self._risk_disabled = True
			self._risk_skip_bar = False
			return False

		self._risk_decision = decision
		skip = False
		if decision.close_all:
			self._risk_close_all()
			skip = True
		elif decision.halted:
			skip = True
		elif decision.close_assets:
			for name in decision.close_assets:
				self._risk_close_asset(name)
			# 当日不再调仓：平仓单尚未成交时重新调仓容易产生来回对冲。
			skip = True

		self._risk_skip_bar = skip
		return skip

	def _risk_snapshot(self) -> PortfolioSnapshot:
		"""把当前账户与持仓转换为风控引擎需要的快照。"""
		assets: list[AssetSnapshot] = []
		for data in self.datas:
			position = self.getposition(data)
			if not position.size:
				continue
			# 开盘前决策（cheat-on-open）时使用开盘价，避免引用当日收盘价。
			raw = float(data.open[0]) if self._risk_in_open else float(data.close[0])
			assets.append(
				AssetSnapshot(
					name=self._risk_name(data),
					size=float(position.size),
					cost_price=float(position.price),
					last_price=raw,
				)
			)
		return PortfolioSnapshot(
			date=self.datas[0].datetime.date(0).isoformat(),
			equity=float(self.broker.getvalue()),
			cash=float(self.broker.getcash()),
			assets=tuple(assets),
		)

	def _risk_name(self, data: Any) -> str:
		"""返回数据源的稳定名称，未命名数据源用 data0/data1 兜底。"""
		name = getattr(data, "_name", "") or ""
		if name:
			return name
		try:
			return f"data{self.datas.index(data)}"
		except ValueError:
			return "data"

	def _risk_close_all(self) -> None:
		"""熔断清仓：平掉所有非空持仓。"""
		self._risk_blocked_buy_count += 1
		for data in self.datas:
			if self.getposition(data).size:
				self._track_order(self.close(data=data))
		self.log("风控触发组合熔断，全部持仓已提交清仓", do_print=True)

	def _risk_close_asset(self, name: str) -> None:
		"""平掉指定标的的持仓。"""
		for data in self.datas:
			if self._risk_name(data) == name and self.getposition(data).size:
				self._track_order(self.close(data=data))
				self.log(f"风控平仓: {name}", do_print=True)
				return

	# ------------------------------------------------------------------ 开仓拦截
	def buy(self, *args: Any, **kwargs: Any):
		"""在不允许开仓的时段拦截买入，返回 None 与策略原有的空单处理逻辑一致。"""
		if not self._risk_buy_allowed(args, kwargs):
			return None
		return super().buy(*args, **kwargs)

	def _risk_buy_allowed(self, args: Sequence[Any], kwargs: Mapping[str, Any]) -> bool:
		"""判断当前买入是否被风控允许。"""
		risk = getattr(self, "risk", None)
		if risk is None or not risk.enabled or self._risk_disabled:
			return True

		data = kwargs.get("data")
		if data is None and args and isinstance(args[0], bt.feed.AbstractDataBase):
			data = args[0]
		if data is None and self.datas:
			data = self.datas[0]
		name = self._risk_name(data) if data is not None else ""

		if not self._risk_decision.allow_new_positions:
			self._risk_blocked_buy_count += 1
			return False
		if risk.is_asset_blocked(name):
			self._risk_blocked_buy_count += 1
			self._record_blocked_buy(name)
			return False
		return True

	def _record_blocked_buy(self, name: str) -> None:
		"""同一根 K 线只记录一次回补拦截，避免事件日志被刷屏。"""
		bar = len(self)
		if self._risk_last_block_bar == bar:
			return
		self._risk_last_block_bar = bar
		self.risk.events.append(
			RiskEvent(
				date=self.datas[0].datetime.date(0).isoformat(),
				rule="buy_blocked",
				symbol=name,
				action="block_buy",
				detail=f"{name} 处于止损/止盈冷却期，拦截回补买入",
			)
		)

	# ------------------------------------------------------------------ 权重裁剪
	def apply_risk_weights(self, weights: Mapping[str, float]) -> dict[str, float]:
		"""按风控要求缩放目标权重；风控关闭时原样返回。"""
		risk = getattr(self, "risk", None)
		if risk is None or not risk.enabled:
			return {name: float(weight) for name, weight in weights.items()}
		return risk.clamp_weights(weights, self._risk_decision)

	def apply_risk_weights_to_array(self, weights: Any) -> list[float]:
		"""按 ``self.datas`` 顺序对权重数组（list 或 ndarray）应用风控裁剪。"""
		weight_map = {
			self._risk_name(data): float(weights[index])
			for index, data in enumerate(self.datas)
			if index < len(weights)
		}
		adjusted = self.apply_risk_weights(weight_map)
		return [adjusted.get(self._risk_name(data), 0.0) for data in self.datas]

	# ------------------------------------------------------------------ 结果访问
	@property
	def risk_events(self) -> list[RiskEvent]:
		"""返回本次回测产生的全部风控事件。"""
		risk = getattr(self, "risk", None)
		return list(risk.events) if risk is not None else []

	def risk_summary(self) -> dict[str, Any]:
		"""返回风控运行统计。"""
		risk = getattr(self, "risk", None)
		if risk is None:
			return {"enabled": False}
		summary = risk.summary()
		summary["blocked_buy_count"] = self._risk_blocked_buy_count
		return summary
