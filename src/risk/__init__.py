"""统一风控层。

对外入口：

* :class:`RiskConfig` / :func:`load_preset`：风控参数与内置预设
* :class:`RiskManager`：与回测框架解耦的规则引擎
* :class:`RiskControlMixin`：Backtrader 策略接入用的混入
* :func:`build_risk_event_frame` / :func:`format_risk_summary`：结果报告
"""

from .config import RISK_PRESETS, RiskConfig, load_preset
from .manager import (
	ACTION_LABELS,
	RULE_LABELS,
	AssetSnapshot,
	PortfolioSnapshot,
	RiskDecision,
	RiskEvent,
	RiskManager,
)
from .mixin import RiskControlMixin
from .report import build_risk_event_frame, build_risk_summary_frame, format_risk_summary

__all__ = [
	"RISK_PRESETS",
	"ACTION_LABELS",
	"RULE_LABELS",
	"AssetSnapshot",
	"PortfolioSnapshot",
	"RiskConfig",
	"RiskControlMixin",
	"RiskDecision",
	"RiskEvent",
	"RiskManager",
	"build_risk_event_frame",
	"build_risk_summary_frame",
	"format_risk_summary",
	"load_preset",
]
