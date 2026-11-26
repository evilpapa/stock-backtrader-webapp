"""基于周期收益的统一策略回测评价。"""

from dataclasses import dataclass

import numpy as np


SCORE_VERSION = "v1"
SCORE_RULES = {
    "return_points": (35, (0.0, 0.10, 0.25), (0, 60, 100)),
    "drawdown_points": (35, (0.05, 0.20, 0.40), (100, 60, 0)),
    "sharpe_points": (30, (0.0, 1.0, 2.0), (0, 60, 100)),
}
GRADE_THRESHOLDS = ((85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "E"))
SCORE_COLUMNS = ("score", "score_grade", *SCORE_RULES, "score_version", "score_note")
METRIC_COLUMNS = ("total_return", "annual_return", "annual_volatility", "max_drawdown", "sharpe", "calmar")


@dataclass(frozen=True)
class BacktestEvaluation:
    metrics: dict[str, float | None]
    scoring: dict[str, float | str | None]


def evaluate_returns(returns, periods_per_year: int = 252) -> BacktestEvaluation:
    """以按时间排序的小数收益序列计算指标与百分制评分。"""
    if periods_per_year < 1:
        raise ValueError("每年周期数必须为正数")

    values = np.asarray(returns, dtype=float)
    count = len(values)
    metrics = dict.fromkeys(METRIC_COLUMNS)
    scoring = dict.fromkeys(SCORE_COLUMNS) | {"score_version": SCORE_VERSION}
    if not count:
        return BacktestEvaluation(metrics, scoring | {"score_note": "没有收益样本"})
    if not np.isfinite(values).all() or (values < -1).any():
        return BacktestEvaluation(metrics, scoring | {"score_note": "存在无效收益"})

    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        nav = np.r_[1.0, np.cumprod(1.0 + values)]
        annual = float(nav[-1] ** (periods_per_year / count) - 1)
        drawdown = float((nav / np.maximum.accumulate(nav) - 1).min())
        volatility = float(values.std(ddof=1) * np.sqrt(periods_per_year)) if count > 1 else None
        if count > 1 and values.min() == values.max():
            volatility = 0.0
        sharpe = float(values.mean() * periods_per_year / volatility) if volatility else None
        calmar = annual / abs(drawdown) if drawdown else None
    metrics = {
        key: value if value is not None and np.isfinite(value) else None
        for key, value in zip(
            METRIC_COLUMNS, (float(nav[-1] - 1), annual, volatility, drawdown, sharpe, calmar), strict=True
        )
    }
    if count < 2:
        return BacktestEvaluation(metrics, scoring | {"score_note": "少于 2 个收益样本"})
    if not all(np.isfinite(value) for value in (annual, drawdown, volatility)) or (
        volatility and metrics["sharpe"] is None
    ):
        return BacktestEvaluation(metrics, scoring | {"score_note": "评分指标不可计算"})

    inputs = (annual, abs(drawdown), sharpe if sharpe is not None else 0.0)
    points = {
        name: float(np.interp(value, anchors, scores)) * weight / 100
        for (name, (weight, anchors, scores)), value in zip(SCORE_RULES.items(), inputs, strict=True)
    }
    points = {name: round(value, 2) for name, value in points.items()}
    total = round(sum(points.values()), 2)
    notes = []
    if count < periods_per_year:
        notes.append("样本不足一年")
    if volatility == 0:
        notes.append("零波动，夏普项计 0 分")
    scoring.update(
        points,
        score=total,
        score_grade=next(grade for threshold, grade in GRADE_THRESHOLDS if total >= threshold),
        score_note="，".join(notes),
    )
    return BacktestEvaluation(metrics, scoring)


def summarize_research_returns(returns, periods_per_year: int = 252) -> dict:
    """生成研究脚本使用的指标表行，按正数幅度展示最大回撤。"""
    evaluation = evaluate_returns(returns, periods_per_year)
    metrics = evaluation.metrics
    drawdown, total = metrics["max_drawdown"], metrics["total_return"]
    return {
        "累计收益": total,
        "年化收益": metrics["annual_return"],
        "年化波动": metrics["annual_volatility"],
        "夏普比率": metrics["sharpe"],
        "最大回撤": abs(drawdown) if drawdown is not None else None,
        "卡玛比率": metrics["calmar"],
        "累计净值": 1 + total if total is not None else None,
    } | evaluation.scoring
