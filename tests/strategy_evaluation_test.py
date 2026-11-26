import numpy as np
import pandas as pd
import pytest

from examples.backtest_common import build_return_metrics, restore_metric_scores
from src.strategy_evaluation import SCORE_VERSION, evaluate_returns


def test_strategy_score_counts_first_period_loss_and_weights_each_metric():
    evaluation = evaluate_returns([-0.20, 0.375], periods_per_year=2)

    assert evaluation.metrics["annual_return"] == pytest.approx(0.10)
    assert evaluation.metrics["max_drawdown"] == pytest.approx(-0.20)
    assert evaluation.metrics["sharpe"] == pytest.approx(0.175 / 0.575)
    assert evaluation.scoring == {
        "score": 47.48,
        "score_grade": "D",
        "return_points": 21.0,
        "drawdown_points": 21.0,
        "sharpe_points": 5.48,
        "score_version": SCORE_VERSION,
        "score_note": "",
    }


def test_flat_and_unusable_samples_have_distinct_score_results():
    flat = evaluate_returns([0.0, 0.0])
    assert flat.metrics["sharpe"] is None
    assert flat.scoring["score"] == 35.0
    assert flat.scoring["sharpe_points"] == 0.0
    assert flat.scoring["score_note"] == "样本不足一年，零波动，夏普项计 0 分"

    for returns in ([], [0.1], [0.1, np.inf], [0.1, np.nan]):
        evaluation = evaluate_returns(returns)
        assert evaluation.scoring["score"] is None
        assert evaluation.scoring["score_grade"] is None
        assert evaluation.scoring["score_note"]


def test_legacy_metrics_are_scored_from_original_returns():
    legacy = pd.DataFrame([{"策略": "模拟策略", "年化收益率": 0.5}])
    returns = pd.DataFrame({"模拟策略": [-0.02, 0.03]})
    expected = {"策略": "模拟策略"} | build_return_metrics(returns["模拟策略"])

    restored = restore_metric_scores(legacy, returns)

    assert restored.iloc[0].to_dict() == expected
    pd.testing.assert_frame_equal(restore_metric_scores(restored, returns), restored)
