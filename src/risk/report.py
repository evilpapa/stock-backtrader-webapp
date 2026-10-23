"""风控结果报告：事件明细表、统计表和文本摘要。

示例脚本与 Streamlit 页面共用这里的格式化逻辑，保证命令行和页面看到的风控
信息一致。
"""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .manager import RiskEvent

EVENT_COLUMNS = ["日期", "规则", "标的", "动作", "说明"]

SUMMARY_LABELS = {
	"enabled": "风控启用",
	"rules": "生效规则",
	"bars": "评估交易日",
	"events": "风控事件数",
	"halt_count": "回撤熔断次数",
	"daily_loss_block_days": "单日亏损禁开仓天数",
	"stop_loss_count": "固定止损次数",
	"trailing_stop_count": "移动止损次数",
	"take_profit_count": "止盈次数",
	"scale_adjust_count": "仓位缩放调整次数",
	"blocked_bars": "禁止开仓交易日",
	"blocked_buy_count": "拦截买入次数",
	"max_drawdown": "风控观测最大回撤",
	"max_drawdown_date": "最大回撤日期",
	"final_exposure_scale": "期末仓位系数",
}


def build_risk_event_frame(events: Iterable[RiskEvent]) -> pd.DataFrame:
	"""把风控事件列表转换为可直接导出的事件表。"""
	rows = [event.to_row() for event in events]
	return pd.DataFrame(rows, columns=EVENT_COLUMNS)


def build_risk_summary_frame(strategy: Any) -> pd.DataFrame:
	"""把策略的风控统计转换为「指标 / 数值」两列表。"""
	summary = _summary_of(strategy)
	rows = []
	for key, label in SUMMARY_LABELS.items():
		if key not in summary:
			continue
		rows.append({"指标": label, "数值": _format_value(key, summary[key])})
	return pd.DataFrame(rows, columns=["指标", "数值"])


def format_risk_summary(strategy: Any) -> str:
	"""生成命令行输出用的单行风控摘要。"""
	summary = _summary_of(strategy)
	if not summary.get("enabled"):
		return "风控: 未启用"
	parts = [
		f"规则={summary.get('rules') or '无'}",
		f"事件={summary.get('events', 0)}",
		f"熔断={summary.get('halt_count', 0)}",
		f"止损={summary.get('stop_loss_count', 0)}",
		f"移动止损={summary.get('trailing_stop_count', 0)}",
		f"止盈={summary.get('take_profit_count', 0)}",
		f"禁开仓天数={summary.get('blocked_bars', 0)}",
		f"最大回撤={summary.get('max_drawdown', 0.0):.2%}",
		f"期末仓位系数={summary.get('final_exposure_scale', 1.0):.2f}",
	]
	return "风控: " + "，".join(parts)


def _summary_of(strategy: Any) -> dict[str, Any]:
	"""兼容传入策略实例、RiskManager 或空值。"""
	if strategy is None:
		return {"enabled": False}
	getter = getattr(strategy, "risk_summary", None)
	if callable(getter):
		result = getter()
		return result if isinstance(result, dict) else {"enabled": False}
	fallback = getattr(strategy, "summary", None)
	if callable(fallback):
		result = fallback()
		return result if isinstance(result, dict) else {"enabled": False}
	return {"enabled": False}


def _format_value(key: str, value: Any) -> Any:
	"""按指标语义格式化数值，比例类统一为百分比文本。"""
	if key in {"max_drawdown"}:
		return f"{float(value):.2%}"
	if key in {"final_exposure_scale"}:
		return f"{float(value):.2f}"
	if key == "enabled":
		return "是" if value else "否"
	return value
