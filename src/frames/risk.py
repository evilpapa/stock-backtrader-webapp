"""风控参数侧边栏组件。

所有页面共用同一套控件，保证命令行（``--risk-*``）和页面上的参数语义一致。
"""

from __future__ import annotations

import streamlit as st

from src.risk import RISK_PRESETS, RiskConfig


def risk_control_ui(prefix: str = "") -> RiskConfig:
	"""渲染风控参数面板，返回风控配置对象。

	Args:
		prefix (str): 控件 key 前缀，多个页面共存时避免 key 冲突。

	Returns:
		RiskConfig: 风控配置；未勾选「启用风控」时返回关闭状态。
	"""
	label_prefix = f"{prefix} " if prefix else ""
	key_prefix = f"risk_{prefix}"

	with st.sidebar.expander(f"🛡️ {label_prefix}风控", expanded=False):
		enabled = st.checkbox("启用风控", value=False, key=f"{key_prefix}_enabled")
		preset_name = st.selectbox(
			"风控预设",
			list(RISK_PRESETS),
			index=list(RISK_PRESETS).index("balanced"),
			key=f"{key_prefix}_preset",
			help="preset 提供一组默认参数，下方各参数会覆盖其中对应项",
		)
		base = RISK_PRESETS[preset_name]

		max_drawdown = st.number_input(
			"组合回撤熔断",
			min_value=0.0,
			max_value=0.9,
			value=base.max_drawdown,
			step=0.01,
			format="%.2f",
			key=f"{key_prefix}_max_drawdown",
		)
		drawdown_cooldown = st.number_input(
			"熔断冷却交易日",
			min_value=0,
			max_value=120,
			value=base.drawdown_cooldown_days,
			step=1,
			key=f"{key_prefix}_cooldown",
		)
		stop_loss = st.number_input(
			"单标的固定止损",
			min_value=0.0,
			max_value=0.9,
			value=base.stop_loss,
			step=0.01,
			format="%.2f",
			key=f"{key_prefix}_stop_loss",
		)
		trailing_stop = st.number_input(
			"单标的移动止损",
			min_value=0.0,
			max_value=0.9,
			value=base.trailing_stop,
			step=0.01,
			format="%.2f",
			key=f"{key_prefix}_trailing_stop",
		)
		max_asset_weight = st.number_input(
			"单标的最大权重",
			min_value=0.0,
			max_value=1.0,
			value=base.max_asset_weight,
			step=0.05,
			format="%.2f",
			key=f"{key_prefix}_max_asset_weight",
		)
		target_volatility = st.number_input(
			"目标年化波动率（0=关闭）",
			min_value=0.0,
			max_value=1.0,
			value=base.target_volatility,
			step=0.01,
			format="%.2f",
			key=f"{key_prefix}_target_vol",
		)

	# 单标的上限为 0 会让整条策略无法建仓，这里回退到预设值。
	asset_cap = max_asset_weight if max_asset_weight > 0 else base.max_asset_weight
	return base.merged(
		enabled=enabled,
		max_drawdown=float(max_drawdown),
		drawdown_cooldown_days=int(drawdown_cooldown),
		stop_loss=float(stop_loss),
		trailing_stop=float(trailing_stop),
		max_asset_weight=float(asset_cap),
		target_volatility=float(target_volatility),
	)
