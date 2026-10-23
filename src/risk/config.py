"""风控参数定义与预设。

风控层只消费回测过程中的账户状态（权益、现金、持仓成本价），不依赖任何
第三方行情 SDK，因此可以直接被 Backtrader 策略、示例脚本和单元测试复用。
所有比例参数均使用小数（``0.2`` 表示 20%），``0`` 表示关闭对应规则。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Mapping


def _check_ratio(name: str, value: float, *, allow_zero: bool = True, upper: float = 1.0) -> None:
	"""校验比例类参数：必须是数值，且落在 [0, upper] 区间内。"""
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		raise TypeError(f"风控参数 {name} 必须是数值，当前 {value!r}")
	if not allow_zero and value <= 0:
		raise ValueError(f"风控参数 {name} 必须大于 0，当前 {value}")
	if value < 0 or value > upper:
		raise ValueError(f"风控参数 {name} 必须落在 [0, {upper}] 之间，当前 {value}")


def _check_days(name: str, value: int) -> None:
	"""校验交易日类参数：必须是非负整数。"""
	if isinstance(value, bool) or not isinstance(value, int):
		raise TypeError(f"风控参数 {name} 必须是整数，当前 {value!r}")
	if value < 0:
		raise ValueError(f"风控参数 {name} 不能为负数，当前 {value}")


@dataclass(frozen=True)
class RiskConfig:
	"""策略风控参数。

	``enabled=False`` 时风控层完全不介入，策略行为与接入风控前完全一致；
	所有规则可以单独开启，未开启的规则不会产生任何开销。

	参数分为三层：

	* 组合级：回撤熔断、单日亏损限制、波动率目标
	* 仓位级：总仓位上限、单标的上限
	* 标的级：固定止损、移动止损、止盈、止损后冷却
	"""

	enabled: bool = False

	# ---- 组合级 ----
	max_drawdown: float = 0.25  # 组合权益自峰值的最大回撤，触发熔断清仓
	drawdown_cooldown_days: int = 10  # 熔断后禁止开仓的交易日数
	reset_peak_after_halt: bool = True  # 熔断后是否以当前权益重置峰值
	daily_loss_limit: float = 0.0  # 单日组合亏损上限，触发当日禁止开仓
	target_volatility: float = 0.0  # 年化目标波动率，>0 时按实现波动率缩放仓位
	volatility_window: int = 20  # 波动率估计窗口（交易日）
	min_vol_scale: float = 0.2  # 波动率缩放的仓位系数下限

	# ---- 仓位级 ----
	max_gross_exposure: float = 1.0  # 组合总仓位上限
	max_asset_weight: float = 1.0  # 单一标的最大权重

	# ---- 标的级 ----
	stop_loss: float = 0.0  # 相对持仓成本的固定止损
	trailing_stop: float = 0.0  # 相对持仓期最高价的移动止损
	take_profit: float = 0.0  # 相对持仓成本的止盈
	asset_cooldown_days: int = 5  # 止损/止盈后同一标的禁止回补的交易日数

	def __post_init__(self) -> None:
		"""构造时立即校验参数，避免非法配置在回测中途才暴露。"""
		if not isinstance(self.enabled, bool):
			raise TypeError("风控参数 enabled 必须是布尔值")
		for name in ("max_drawdown", "daily_loss_limit", "target_volatility", "stop_loss", "trailing_stop", "take_profit"):
			_check_ratio(name, getattr(self, name))
		for name in ("max_gross_exposure", "max_asset_weight"):
			_check_ratio(name, getattr(self, name), allow_zero=False)
		_check_ratio("min_vol_scale", self.min_vol_scale, allow_zero=False)
		_check_days("drawdown_cooldown_days", self.drawdown_cooldown_days)
		_check_days("volatility_window", self.volatility_window)
		_check_days("asset_cooldown_days", self.asset_cooldown_days)
		if self.volatility_window < 2:
			raise ValueError("风控参数 volatility_window 至少为 2")
		if self.min_vol_scale > 1:
			raise ValueError("风控参数 min_vol_scale 不能大于 1")
		if not isinstance(self.reset_peak_after_halt, bool):
			raise TypeError("风控参数 reset_peak_after_halt 必须是布尔值")

	@classmethod
	def from_dict(cls, data: Mapping[str, Any] | None) -> "RiskConfig":
		"""从字典构造配置，未知字段直接报错以尽早发现拼写错误。"""
		if not data:
			return cls()
		known = {item.name for item in fields(cls)}
		unknown = set(data) - known
		if unknown:
			raise ValueError(f"未知风控参数: {', '.join(sorted(unknown))}")
		return cls(**dict(data))

	def merged(self, **overrides: Any) -> "RiskConfig":
		"""返回替换部分参数后的新配置对象（不可变配置的常用做法）。"""
		return replace(self, **overrides)

	def to_dict(self) -> dict[str, Any]:
		"""转换为可序列化字典，便于写入日志和结果文件。"""
		return asdict(self)

	@property
	def active_rules(self) -> list[str]:
		"""列出当前实际生效的规则名称。"""
		if not self.enabled:
			return []
		rules = []
		if self.max_drawdown > 0:
			rules.append("max_drawdown")
		if self.daily_loss_limit > 0:
			rules.append("daily_loss_limit")
		if self.target_volatility > 0:
			rules.append("target_volatility")
		if self.max_gross_exposure < 1 or self.max_asset_weight < 1:
			rules.append("position_limit")
		if self.stop_loss > 0:
			rules.append("stop_loss")
		if self.trailing_stop > 0:
			rules.append("trailing_stop")
		if self.take_profit > 0:
			rules.append("take_profit")
		return rules


RISK_PRESETS: dict[str, RiskConfig] = {
	"none": RiskConfig(enabled=False),
	"conservative": RiskConfig(
		enabled=True,
		max_drawdown=0.15,
		drawdown_cooldown_days=15,
		daily_loss_limit=0.03,
		target_volatility=0.15,
		max_gross_exposure=0.95,
		max_asset_weight=0.35,
		stop_loss=0.08,
		trailing_stop=0.12,
		asset_cooldown_days=10,
	),
	"balanced": RiskConfig(
		enabled=True,
		max_drawdown=0.20,
		drawdown_cooldown_days=10,
		daily_loss_limit=0.05,
		target_volatility=0.20,
		max_gross_exposure=1.0,
		max_asset_weight=0.5,
		stop_loss=0.12,
		trailing_stop=0.18,
		asset_cooldown_days=5,
	),
	"aggressive": RiskConfig(
		enabled=True,
		max_drawdown=0.30,
		drawdown_cooldown_days=5,
		daily_loss_limit=0.0,
		target_volatility=0.0,
		max_asset_weight=1.0,
		stop_loss=0.18,
		trailing_stop=0.25,
		asset_cooldown_days=3,
	),
}


def load_preset(name: str) -> RiskConfig:
	"""按名称读取内置风控预设；名称不存在时给出可用选项。"""
	key = (name or "none").strip().lower()
	if key not in RISK_PRESETS:
		raise ValueError(f"未知风控预设: {name}，可选 {', '.join(sorted(RISK_PRESETS))}")
	return RISK_PRESETS[key]
