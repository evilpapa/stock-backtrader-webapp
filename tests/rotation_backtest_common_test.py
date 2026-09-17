from __future__ import annotations

import pandas as pd

from examples import backtest_common as backtest_common


def test_prepare_price_data_removes_non_positive_ohlc_rows(monkeypatch):
    """验证行情准备逻辑会剔除非正 OHLC 记录并合并重复日期。"""
    raw_data = pd.DataFrame(
        {
            "Open": [0.0, 10.0, 0.0],
            "High": [11.0, 11.0, 11.0],
            "Low": [9.0, 9.0, 9.0],
            "Close": [0.0, 10.0, 10.0],
            "Volume": [100, 100, 100],
        },
        index=pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-03"]),
    )
    monkeypatch.setattr(backtest_common, "fetch_history_ohlcv", lambda *args, **kwargs: raw_data)
    monkeypatch.setattr(backtest_common, "to_title_case_ohlcv", lambda frame: frame)

    prepared = backtest_common.prepare_price_data(["510300"], "2025-01-01", "2025-01-03", "测试")

    assert prepared["510300"].index.tolist() == [pd.Timestamp("2025-01-01")]
    assert (prepared["510300"][["Open", "High", "Low", "Close"]] > 0).all().all()


def test_align_series_uses_last_value_for_duplicate_dates():
    """验证收益序列对齐前会使用重复日期的最后一条记录。"""
    first = pd.Series([0.1, 0.2, 0.3], index=pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02"]))
    second = pd.Series([0.4, 0.5], index=pd.to_datetime(["2025-01-01", "2025-01-02"]))

    aligned_first, aligned_second = backtest_common.align_series(first, second)

    assert aligned_first.tolist() == [0.2, 0.3]
    assert aligned_second.tolist() == [0.4, 0.5]


def test_plot_weights_writes_png_without_tight_layout_warning(tmp_path):
    """验证权重图能写出 PNG，且不再依赖会报警的 tight_layout。"""
    weights_df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "ETF A": [0.4, 0.6],
            "ETF B": [0.6, 0.4],
            "权重合计": [1.0, 1.0],
        }
    )

    backtest_common.plot_weights(weights_df, "测试策略", tmp_path)

    assert (tmp_path / "daily_weights_plot.png").is_file()
