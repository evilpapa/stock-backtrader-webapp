"""Streamlit 顶部绩效摘要卡片与通用指标格式化工具。"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from src.strategy_evaluation import GRADE_THRESHOLDS


SUMMARY_CARD_CSS = """
<style>
.performance-summary {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px 18px;
    background: #ffffff;
    min-height: 116px;
}
.performance-summary-primary {
    min-height: 116px;
}
.performance-summary-label {
    color: #6b7280;
    font-size: 0.9rem;
    margin-bottom: 8px;
}
.performance-summary-annual {
    color: #d62728;
    font-size: 2.45rem;
    font-weight: 700;
    line-height: 1.05;
}
.performance-summary-sub {
    color: #374151;
    font-size: 0.98rem;
    margin-top: 10px;
}
.performance-summary-value {
    color: #111827;
    font-size: 1.6rem;
    font-weight: 650;
    line-height: 1.15;
}
</style>
"""


def _number_or_none(value) -> float | None:
	"""将输入安全转换为有限浮点数，无法转换时返回空值。"""
	if value is None:
		return None
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	if not math.isfinite(number):
		return None
	return number


def _row_value(row: pd.Series | dict, names: list[str]) -> float | None:
	"""按候选字段名从指标行中取出第一个有效数值。"""
	for name in names:
		if name in row:
			value = _number_or_none(row[name])
			if value is not None:
				return value
	return None


def _annual_return_from_row(row: pd.Series | dict) -> float | None:
	"""从不同来源的指标字段中解析年化收益率。"""
	value = _row_value(row, ["年化收益率", "年化收益", "annual_return", "annualized_return"])
	if value is not None:
		return value
	value = _row_value(row, ["return"])
	return value / 100.0 if value is not None else None


def _cumulative_return_from_row(row: pd.Series | dict) -> float | None:
	"""从指标行中解析累计收益率。"""
	value = _row_value(row, ["累计收益率", "累计收益", "总收益", "total_return", "cumulative_return"])
	if value is not None:
		return value
	nav = _row_value(row, ["累计净值"])
	return nav - 1.0 if nav is not None else None


def _max_drawdown_from_row(row: pd.Series | dict) -> float | None:
	"""从指标行中解析最大回撤，并统一为负数展示。"""
	value = _row_value(row, ["最大回撤", "max_drawdown"])
	if value is not None:
		return -abs(value)
	value = _row_value(row, ["dd"])
	return -abs(value / 100.0) if value is not None else None


def _ratio_from_row(row: pd.Series | dict, names: list[str]) -> float | None:
	"""按候选字段名读取夏普、卡玛等比率类指标。"""
	return _row_value(row, names)


def _format_percent(value: float | None) -> str:
	"""将小数形式的收益或回撤格式化为百分比文本。"""
	if value is None:
		return "N/A"
	return f"{value * 100:.2f}%"


def _format_ratio(value: float | None) -> str:
	"""将比率类数值格式化为固定精度文本。"""
	if value is None:
		return "N/A"
	return f"{value:.3f}"


def render_performance_summary(
	annual_return: float | None,
	cumulative_return: float | None,
	max_drawdown: float | None,
	sharpe_ratio: float | None,
	calmar_ratio: float | None,
	scoring: pd.Series | dict,
) -> None:
	"""渲染顶部绩效摘要卡片。"""
	st.markdown(SUMMARY_CARD_CSS, unsafe_allow_html=True)
	score_col, left, dd_col, sharpe_col, calmar_col = st.columns([1.4, 2.2, 1, 1, 1])
	score = _number_or_none(scoring.get("score"))
	grade = next((grade for _, grade in GRADE_THRESHOLDS if grade == scoring.get("score_grade")), "—")
	score_text = f"{score:.2f} / 100 · {grade}" if score is not None else "暂无法评分"
	with left:
		st.markdown(
			f"""
			<div class="performance-summary performance-summary-primary">
				<div class="performance-summary-label">年化收益</div>
				<div class="performance-summary-annual">{_format_percent(annual_return)}</div>
				<div class="performance-summary-sub">累计收益 {_format_percent(cumulative_return)}</div>
			</div>
			""",
			unsafe_allow_html=True,
		)
	for column, label, value, formatter in [
		(score_col, "策略评分", score_text, str),
		(dd_col, "最大回撤", max_drawdown, _format_percent),
		(sharpe_col, "夏普比率", sharpe_ratio, _format_ratio),
		(calmar_col, "卡玛比率", calmar_ratio, _format_ratio),
	]:
		with column:
			st.markdown(
				f"""
				<div class="performance-summary">
					<div class="performance-summary-label">{label}</div>
					<div class="performance-summary-value">{formatter(value)}</div>
				</div>
				""",
				unsafe_allow_html=True,
			)
	if score is not None:
		return_pts = _number_or_none(scoring.get("return_points"))
		dd_pts = _number_or_none(scoring.get("drawdown_points"))
		sharpe_pts = _number_or_none(scoring.get("sharpe_points"))
		version = scoring.get("score_version") or "v1"
		if return_pts is not None and dd_pts is not None and sharpe_pts is not None:
			st.caption(
				f"评分 {version} · "
				f"收益 {return_pts:.2f} 分 · "
				f"回撤 {dd_pts:.2f} 分 · "
				f"夏普 {sharpe_pts:.2f} 分"
			)
	note = scoring.get("score_note")
	if isinstance(note, str) and note:
		st.caption(note)


def render_summary_from_metric_row(row: pd.Series | dict, cumulative_return: float | None = None) -> None:
	"""从一行绩效指标中抽取摘要字段并渲染指标卡片。"""
	render_performance_summary(
		annual_return=_annual_return_from_row(row),
		cumulative_return=cumulative_return if cumulative_return is not None else _cumulative_return_from_row(row),
		max_drawdown=_max_drawdown_from_row(row),
		sharpe_ratio=_ratio_from_row(row, ["夏普比率", "夏普", "sharpe", "sharpe_ratio"]),
		calmar_ratio=_ratio_from_row(row, ["卡玛比率", "卡尔马比率", "卡玛", "calmar", "calmar_ratio"]),
		scoring=row,
	)


def cumulative_return_from_frame(cumulative: pd.DataFrame, strategy_name: str) -> float | None:
	"""从累计净值表中计算指定策略最终累计收益率。"""
	if strategy_name not in cumulative.columns or cumulative.empty:
		return None
	value = _number_or_none(cumulative[strategy_name].iloc[-1])
	return value - 1.0 if value is not None else None
