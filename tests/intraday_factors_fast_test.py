"""矩阵加速不能改变39个因子：随机、平局、常量、零量、无效价格和多日。"""
import unittest
import warnings
import numpy as np
import pandas as pd
from src.strategy.intraday_factors import daily_factors
from src.strategy.intraday_factors_fast import daily_factors_fast


class FastFactorsTest(unittest.TestCase):
    def test_matches_reference(self):
        rng = np.random.default_rng(41)
        pieces = []
        for day in ["2026-01-05", "2026-01-06"]:
            times = pd.date_range(day + " 09:31", periods=120, freq="min").append(
                pd.date_range(day + " 13:01", periods=120, freq="min"))
            for i in range(8):
                p = 10 * np.exp(np.cumsum(rng.normal(0, .001, 240)))
                v = rng.integers(0, 10, 240).astype(float)  # 大量平局
                if i == 1: p[:] = 10
                if i == 2: v[:] = 7
                if i == 3: v[:] = 0
                if i == 4: p = np.linspace(10, 11, 240)
                if i == 5: p = np.linspace(11, 10, 240)
                if i == 6: p[25] = np.nan
                if i == 7: p[15] = 0
                pieces.append(pd.DataFrame(dict(symbol=f"{i:06}.SZ", datetime=times, open=10., close=p, volume=v)))
        bars = pd.concat(pieces, ignore_index=True).sample(frac=1, random_state=1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            expected = daily_factors(bars)
            actual = daily_factors_fast(bars)
        pd.testing.assert_frame_equal(actual[expected.columns], expected, rtol=1e-10, atol=1e-12)

    def test_missing_minute_rejected(self):
        bars = pd.DataFrame({"symbol": ["000001.SZ"], "datetime": pd.to_datetime(["2026-01-05 09:31"]),
                             "open": [10.], "close": [10.], "volume": [10.]})
        with self.assertRaises(ValueError):
            daily_factors_fast(bars)
