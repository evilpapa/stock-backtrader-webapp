import datetime
import unittest

import pandas as pd

from utils.processing import run_backtrader
from utils.schemas import BacktraderParams, StrategyBase


class ProcessingMetricsTest(unittest.TestCase):
    def test_run_backtrader_includes_summary_metric_columns(self):
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

        result = run_backtrader(
            frame,
            StrategyBase(name="Ma", params={"maperiod": range(5, 6)}),
            BacktraderParams(
                start_date=datetime.date(2024, 1, 1),
                end_date=datetime.date(2024, 2, 14),
                start_cash=100000.0,
                commission_fee=0.0,
                stake=10,
            ),
        )

        self.assertEqual(result.columns.tolist(), ["maperiod", "return", "total_return", "dd", "sharpe", "calmar"])
        self.assertEqual(len(result), 1)
        self.assertIn("total_return", result)
        self.assertIn("calmar", result)


if __name__ == "__main__":
    unittest.main()

