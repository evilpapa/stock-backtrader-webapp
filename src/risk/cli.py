"""风控命令行参数：让示例脚本用统一的开关控制风控。

用法::

    parser = argparse.ArgumentParser()
    add_risk_arguments(parser)
    args = parser.parse_args()
    risk_config = risk_config_from_args(args)

``--risk-preset`` 选择内置预设，其余 ``--risk-*`` 参数覆盖预设中的单项配置。
只给覆盖项而不指定预设时，自动启用风控。
"""

from __future__ import annotations

import argparse
from typing import Any

from .config import RISK_PRESETS, RiskConfig, load_preset

# 命令行参数名 -> RiskConfig 字段名
_OVERRIDE_FIELDS: dict[str, str] = {
	"risk_max_drawdown": "max_drawdown",
	"risk_drawdown_cooldown": "drawdown_cooldown_days",
	"risk_daily_loss_limit": "daily_loss_limit",
	"risk_target_vol": "target_volatility",
	"risk_max_gross_exposure": "max_gross_exposure",
	"risk_max_asset_weight": "max_asset_weight",
	"risk_stop_loss": "stop_loss",
	"risk_trailing_stop": "trailing_stop",
	"risk_take_profit": "take_profit",
	"risk_asset_cooldown": "asset_cooldown_days",
}


def add_risk_arguments(parser: argparse.ArgumentParser) -> None:
	"""为命令行解析器注册统一的风控参数。"""
	parser.add_argument(
		"--risk-preset",
		choices=sorted(RISK_PRESETS),
		default="none",
		help="风控预设：none=关闭，conservative/balanced/aggressive 逐级放宽",
	)
	parser.add_argument("--risk-max-drawdown", type=float, default=None, help="组合回撤熔断阈值，如 0.2")
	parser.add_argument("--risk-drawdown-cooldown", type=int, default=None, help="熔断后禁止开仓的交易日数")
	parser.add_argument("--risk-daily-loss-limit", type=float, default=None, help="单日亏损禁开仓阈值，0 表示关闭")
	parser.add_argument("--risk-target-vol", type=float, default=None, help="年化目标波动率，0 表示关闭")
	parser.add_argument("--risk-max-gross-exposure", type=float, default=None, help="组合总仓位上限")
	parser.add_argument("--risk-max-asset-weight", type=float, default=None, help="单一标的最大权重")
	parser.add_argument("--risk-stop-loss", type=float, default=None, help="相对成本的固定止损，如 0.1")
	parser.add_argument("--risk-trailing-stop", type=float, default=None, help="相对持仓高点的移动止损")
	parser.add_argument("--risk-take-profit", type=float, default=None, help="相对成本的止盈线")
	parser.add_argument("--risk-asset-cooldown", type=int, default=None, help="止损后同一标的禁止回补的交易日数")


def risk_config_from_args(args: argparse.Namespace) -> RiskConfig:
	"""按「预设 + 显式覆盖」生成风控配置。"""
	preset = getattr(args, "risk_preset", "none") or "none"
	config = load_preset(preset)

	overrides: dict[str, Any] = {}
	for attr, field in _OVERRIDE_FIELDS.items():
		value = getattr(args, attr, None)
		if value is not None:
			overrides[field] = value
	if not overrides:
		return config
	# 未选择预设但给出了具体参数时，视为显式启用风控。
	if not config.enabled:
		overrides["enabled"] = True
	return config.merged(**overrides)
