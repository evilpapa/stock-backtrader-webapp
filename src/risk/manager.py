"""风控规则引擎：与回测框架解耦的纯状态机实现。

引擎在每个交易日拿到一份账户快照，返回当日应该执行的风控指令：

* ``close_all``：熔断清仓
* ``close_assets``：需要止损/止盈的标的
* ``allow_new_positions``：当日是否允许开新仓
* ``exposure_scale``：仓位缩放系数

指令由 :class:`src.risk.mixin.RiskControlMixin` 落地为 Backtrader 订单，
引擎本身不导入 Backtrader，便于用普通单元测试覆盖全部规则。
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Mapping

from .config import RiskConfig

TRADING_DAYS = 252

RULE_LABELS = {
	"max_drawdown": "组合回撤熔断",
	"daily_loss_limit": "单日亏损限制",
	"stop_loss": "固定止损",
	"trailing_stop": "移动止损",
	"take_profit": "止盈",
	"target_volatility": "波动率目标",
}

ACTION_LABELS = {
	"close_all": "清仓",
	"close_asset": "平仓",
	"block_buy": "禁止开仓",
	"scale_exposure": "缩放仓位",
}


@dataclass(frozen=True)
class RiskEvent:
	"""一条风控事件记录，用于回测审计和结果导出。"""

	date: str
	rule: str
	symbol: str
	action: str
	detail: str

	@property
	def rule_label(self) -> str:
		"""返回规则中文名称。"""
		return RULE_LABELS.get(self.rule, self.rule)

	@property
	def action_label(self) -> str:
		"""返回动作中文名称。"""
		return ACTION_LABELS.get(self.action, self.action)

	def to_row(self) -> dict[str, Any]:
		"""转换为结果表的一行。"""
		return {
			"日期": self.date,
			"规则": self.rule_label,
			"标的": self.symbol or "组合",
			"动作": self.action_label,
			"说明": self.detail,
		}


@dataclass(frozen=True)
class AssetSnapshot:
	"""单个持仓标的的风控视图。"""

	name: str
	size: float  # 持仓数量，负数表示空头
	cost_price: float  # 持仓成本价（多头为买入均价，空头为卖空均价）
	last_price: float  # 当前收盘价


@dataclass(frozen=True)
class PortfolioSnapshot:
	"""账户级风控视图。"""

	date: str
	equity: float
	cash: float
	assets: tuple[AssetSnapshot, ...] = ()


@dataclass(frozen=True)
class RiskDecision:
	"""单个交易日的风控决策。"""

	close_all: bool = False
	close_assets: tuple[str, ...] = ()
	allow_new_positions: bool = True
	exposure_scale: float = 1.0
	halted: bool = False
	drawdown: float = 0.0
	realized_volatility: float = 0.0


def _positive(value: Any) -> float:
	"""把任意输入规约为有限正数，无法识别时返回 0。"""
	try:
		number = float(value)
	except (TypeError, ValueError):
		return 0.0
	return number if math.isfinite(number) and number > 0 else 0.0


class RiskManager:
	"""按优先顺序执行组合级、仓位级、标的级风控规则。"""

	def __init__(self, config: RiskConfig | Mapping[str, Any] | None = None) -> None:
		"""接受 :class:`RiskConfig`、参数字典或空值（等同于关闭风控）。"""
		if isinstance(config, RiskConfig):
			self.config = config
		else:
			self.config = RiskConfig.from_dict(config)

		self.events: list[RiskEvent] = []
		self.bars = 0
		self.max_drawdown_seen = 0.0
		self.max_drawdown_date = ""

		self._peak_equity: float | None = None
		self._prev_equity: float | None = None
		self._returns: deque[float] = deque(maxlen=max(self.config.volatility_window, 2))
		self._asset_peak: dict[str, float] = {}
		self._asset_trough: dict[str, float] = {}
		self._asset_blocked_until: dict[str, int] = {}
		self._halt_until = -1
		self._bar = 0
		self._blocked_bars = 0
		self._scale = 1.0
		self._last_scale_event = 1.0

	@property
	def enabled(self) -> bool:
		"""风控是否启用。"""
		return self.config.enabled

	# ------------------------------------------------------------------ 主流程
	def evaluate(self, snapshot: PortfolioSnapshot, bar: int | None = None) -> RiskDecision:
		"""计算当日风控指令；``bar`` 缺省时按调用次数自增。"""
		if not self.enabled:
			return RiskDecision()

		if bar is not None:
			self._bar = int(bar)
		else:
			self._bar += 1
		bar = self._bar
		self.bars = max(self.bars, bar)

		equity = _positive(snapshot.equity)
		if equity <= 0:
			return RiskDecision()

		day_return = 0.0
		if self._prev_equity:
			day_return = equity / self._prev_equity - 1.0
			self._returns.append(day_return)
		self._prev_equity = equity

		if self._peak_equity is None or equity > self._peak_equity:
			self._peak_equity = equity
		drawdown = 1.0 - equity / self._peak_equity if self._peak_equity else 0.0
		drawdown = max(0.0, drawdown)
		if drawdown > self.max_drawdown_seen:
			self.max_drawdown_seen = drawdown
			self.max_drawdown_date = snapshot.date

		cfg = self.config

		# 熔断冷却期内只禁止开仓，不重复触发清仓。
		if bar <= self._halt_until:
			self._blocked_bars += 1
			return RiskDecision(allow_new_positions=False, halted=True, exposure_scale=0.0, drawdown=drawdown)

		if cfg.max_drawdown > 0 and drawdown >= cfg.max_drawdown:
			self._halt_until = bar + cfg.drawdown_cooldown_days
			self._blocked_bars += 1
			# 默认以当前权益重置峰值，否则空仓状态下回撤永远不会修复。
			if cfg.reset_peak_after_halt:
				self._peak_equity = equity
			self.events.append(
				RiskEvent(
					date=snapshot.date,
					rule="max_drawdown",
					symbol="",
					action="close_all",
					detail=(
						f"组合回撤 {drawdown:.2%} ≥ 阈值 {cfg.max_drawdown:.2%}，"
						f"清仓并冷却 {cfg.drawdown_cooldown_days} 个交易日"
					),
				)
			)
			return RiskDecision(
				close_all=True,
				allow_new_positions=False,
				halted=True,
				exposure_scale=0.0,
				drawdown=drawdown,
			)

		allow_new = True
		if cfg.daily_loss_limit > 0 and day_return <= -cfg.daily_loss_limit:
			allow_new = False
			self._blocked_bars += 1
			self.events.append(
				RiskEvent(
					date=snapshot.date,
					rule="daily_loss_limit",
					symbol="",
					action="block_buy",
					detail=f"当日组合收益 {day_return:.2%}，触发单日亏损限制 {cfg.daily_loss_limit:.2%}",
				)
			)

		closed = self._evaluate_assets(snapshot, bar)
		scale, realized = self._evaluate_volatility(snapshot)

		return RiskDecision(
			close_assets=tuple(closed),
			allow_new_positions=allow_new,
			exposure_scale=scale,
			drawdown=drawdown,
			realized_volatility=realized,
		)

	def _evaluate_assets(self, snapshot: PortfolioSnapshot, bar: int) -> list[str]:
		"""逐个检查止损/止盈；返回当日需要平仓的标的名称。"""
		closed: list[str] = []
		for asset in snapshot.assets:
			if asset.size == 0:
				# 已无持仓时清理极值缓存，下一笔建仓重新累计。
				self._asset_peak.pop(asset.name, None)
				self._asset_trough.pop(asset.name, None)
				continue

			price = _positive(asset.last_price) or _positive(asset.cost_price)
			if price <= 0:
				continue

			is_long = asset.size > 0
			peak = max(self._asset_peak.get(asset.name, price), price)
			trough = min(self._asset_trough.get(asset.name, price), price)
			self._asset_peak[asset.name] = peak
			self._asset_trough[asset.name] = trough

			reason = self._exit_reason(asset, price, peak, trough, is_long)
			if reason is None:
				continue
			rule, detail = reason
			closed.append(asset.name)
			# cooldown=0 时同样阻止当根 K 线立刻回补，但不影响下一交易日。
			self._asset_blocked_until[asset.name] = bar + self.config.asset_cooldown_days
			self.events.append(
				RiskEvent(date=snapshot.date, rule=rule, symbol=asset.name, action="close_asset", detail=detail)
			)
		return closed

	def _exit_reason(
		self,
		asset: AssetSnapshot,
		price: float,
		peak: float,
		trough: float,
		is_long: bool,
	) -> tuple[str, str] | None:
		"""判断单一持仓是否触发止损或止盈，返回 (规则, 说明)。"""
		cfg = self.config
		cost = _positive(asset.cost_price)

		if is_long:
			if cost > 0 and cfg.stop_loss > 0 and price <= cost * (1.0 - cfg.stop_loss):
				return "stop_loss", f"价格 {price:.3f} 相对成本 {cost:.3f} 下跌 {price / cost - 1.0:.2%}"
			if peak > 0 and cfg.trailing_stop > 0 and price <= peak * (1.0 - cfg.trailing_stop):
				return "trailing_stop", f"价格 {price:.3f} 相对持仓高点 {peak:.3f} 回撤 {price / peak - 1.0:.2%}"
			if cost > 0 and cfg.take_profit > 0 and price >= cost * (1.0 + cfg.take_profit):
				return "take_profit", f"价格 {price:.3f} 相对成本 {cost:.3f} 上涨 {price / cost - 1.0:.2%}"
		else:
			if cost > 0 and cfg.stop_loss > 0 and price >= cost * (1.0 + cfg.stop_loss):
				return "stop_loss", f"价格 {price:.3f} 相对卖空均价 {cost:.3f} 上涨 {price / cost - 1.0:.2%}"
			if trough > 0 and cfg.trailing_stop > 0 and price >= trough * (1.0 + cfg.trailing_stop):
				return "trailing_stop", f"价格 {price:.3f} 相对持仓低点 {trough:.3f} 反弹 {price / trough - 1.0:.2%}"
			if cost > 0 and cfg.take_profit > 0 and price <= cost * (1.0 - cfg.take_profit):
				return "take_profit", f"价格 {price:.3f} 相对卖空均价 {cost:.3f} 下跌 {price / cost - 1.0:.2%}"
		return None

	def _evaluate_volatility(self, snapshot: PortfolioSnapshot) -> tuple[float, float]:
		"""按实现波动率计算仓位缩放系数，返回 (系数, 年化实现波动率)。"""
		cfg = self.config
		if cfg.target_volatility <= 0 or len(self._returns) < cfg.volatility_window:
			return 1.0, 0.0

		window = list(self._returns)[-cfg.volatility_window :]
		realized = statistics.pstdev(window) * math.sqrt(TRADING_DAYS)
		if realized <= 1e-9:
			return 1.0, realized

		scale = max(cfg.min_vol_scale, min(1.0, cfg.target_volatility / realized))
		# 仓位系数连续变动会淹没事件日志，只在变化明显时留痕。
		if abs(scale - self._last_scale_event) >= 0.05:
			self._last_scale_event = scale
			self.events.append(
				RiskEvent(
					date=snapshot.date,
					rule="target_volatility",
					symbol="",
					action="scale_exposure",
					detail=(
						f"年化实现波动率 {realized:.2%}，目标 {cfg.target_volatility:.2%}，"
						f"仓位系数调整为 {scale:.2f}"
					),
				)
			)
		return scale, realized

	# ------------------------------------------------------------------ 查询接口
	def is_asset_blocked(self, name: str, bar: int | None = None) -> bool:
		"""判断某个标的当前是否处于止损后的禁止回补期。"""
		if not self.enabled:
			return False
		bar = self._bar if bar is None else int(bar)
		until = self._asset_blocked_until.get(name)
		return until is not None and bar <= until

	def clamp_weights(self, weights: Mapping[str, float], decision: RiskDecision | None = None) -> dict[str, float]:
		"""按风控要求缩放并裁剪目标权重。

		处理顺序：仓位系数 → 单标的上限 → 组合上限 → 禁止回补标的归零。
		不重新分配被裁剪掉的权重，剩余部分自然成为现金。
		"""
		if not self.enabled:
			return {name: float(weight) for name, weight in weights.items()}

		cfg = self.config
		scale = self._scale if decision is None else decision.exposure_scale
		blocked = {name for name in weights if self.is_asset_blocked(name)}

		result: dict[str, float] = {}
		for name, weight in weights.items():
			value = float(weight)
			if name in blocked or not math.isfinite(value) or value == 0.0:
				continue
			sign = 1.0 if value > 0 else -1.0
			capped = min(abs(value) * scale, cfg.max_asset_weight)
			if capped > 0:
				result[name] = sign * capped

		# 组合上限：按比例压缩，再重新施加单标的上限，最多迭代 8 次保证收敛。
		for _ in range(8):
			gross = sum(abs(value) for value in result.values())
			if gross <= cfg.max_gross_exposure + 1e-12 or gross <= 0:
				break
			ratio = cfg.max_gross_exposure / gross
			rescaled = {
				name: (1.0 if value > 0 else -1.0) * min(abs(value) * ratio, cfg.max_asset_weight)
				for name, value in result.items()
			}
			if rescaled == result:
				break
			result = rescaled
		return {name: value for name, value in result.items() if value != 0.0}

	def summary(self) -> dict[str, Any]:
		"""汇总风控运行统计，供回测结果打印和结果文件使用。"""
		counts = Counter(event.rule for event in self.events)
		return {
			"enabled": self.enabled,
			"rules": ",".join(self.config.active_rules),
			"bars": self.bars,
			"events": len(self.events),
			"halt_count": counts.get("max_drawdown", 0),
			"daily_loss_block_days": counts.get("daily_loss_limit", 0),
			"stop_loss_count": counts.get("stop_loss", 0),
			"trailing_stop_count": counts.get("trailing_stop", 0),
			"take_profit_count": counts.get("take_profit", 0),
			"scale_adjust_count": counts.get("target_volatility", 0),
			"blocked_bars": self._blocked_bars,
			"max_drawdown": self.max_drawdown_seen,
			"max_drawdown_date": self.max_drawdown_date,
			"final_exposure_scale": self._scale,
		}
