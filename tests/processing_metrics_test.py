import datetime
import unittest

import pandas as pd

from src.utils import run_backtrader
from src.strategy_evaluation import SCORE_COLUMNS
from src.utils.processing import BACKTRADER_METRIC_COLUMNS
from src.utils.schemas import BacktraderParams, StrategyBase


class ProcessingMetricsTest(unittest.TestCase):
    """回测处理层输出指标的单元测试。"""

    def test_run_backtrader_includes_summary_metric_columns(self):
        """验证回测结果包含累计收益和卡玛比率等汇总列。"""
        dates = pd.date_range("2024-01-01", periods=45, freq="D")
        close = [100.0 + index * 0.4 for index in range(len(dates))]
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": close,
                "high": [value + 1.0 for value in close],
                "low": [value - 1.0 for value in close],
                "close": close,
                "volume": 100000,
            }
        )

        for period, frequency, annual_periods in [("1d", "D", 252), ("1w", "W-FRI", 52), ("1mon", "ME", 12)]:
            with self.subTest(period=period):
                period_dates = pd.date_range(dates[0], periods=len(dates), freq=frequency)
                result = run_backtrader(
                    frame.assign(date=period_dates),
                    StrategyBase(name="Ma", params={"maperiod": range(5, 7)}),
                    BacktraderParams(
                        start_date=datetime.date(2024, 1, 1),
                        end_date=period_dates[-1].date(),
                        start_cash=100000.0,
                        commission_fee=0.0,
                        stake=10,
                    ),
                    period=period,
                )

                self.assertEqual(result.columns.tolist(), ["maperiod", *BACKTRADER_METRIC_COLUMNS, *SCORE_COLUMNS])
                self.assertEqual(result["maperiod"].tolist(), [5, 6])
                self.assertTrue(result["score"].between(0, 100).all())
                expected_annual = ((1 + result["total_return"]) ** (annual_periods / len(dates)) - 1) * 100
                pd.testing.assert_series_equal(result["return"], expected_annual, check_names=False)
                expected_note = "样本不足一年" if len(dates) < annual_periods else ""
                self.assertTrue(result["score_note"].eq(expected_note).all())


if __name__ == "__main__":
    unittest.main()
