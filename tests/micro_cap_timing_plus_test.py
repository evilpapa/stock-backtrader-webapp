"""微盘择时增强策略状态机与回测的模拟数据测试（不访问网络）。"""

import unittest

import numpy as np
import pandas as pd

from src.strategy.micro_cap_timing_plus import MicroCapTimingParams, backtest, build_positions, performance


def _signals(n: int, **flags: dict[int, bool]) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-01", periods=n)
    frame = pd.DataFrame({"close": 2.0, "ma": 1.0, "bottom": False, "crisis": False, "top": False}, index=dates)
    for column, days in flags.items():
        frame.iloc[list(days), frame.columns.get_loc(column)] = True
    return frame


class MicroCapTimingPlusTest(unittest.TestCase):
    def test_top_locks_flat_then_returns_to_trend(self) -> None:
        position = build_positions(_signals(20, top={3}), MicroCapTimingParams(top_lock_days=5))
        self.assertEqual(position.iloc[:3].tolist(), [1, 1, 1])
        self.assertEqual(position.iloc[3:8].tolist(), [0] * 5)
        self.assertEqual(position.iloc[8:].tolist(), [1] * 12)

    def test_bottom_overrides_trend_and_ignores_top_during_hold(self) -> None:
        signals = _signals(12, bottom={2}, top={4})
        signals["close"] = 0.5  # 趋势空仓
        position = build_positions(signals, MicroCapTimingParams(bottom_hold_days=5))
        self.assertEqual(position.tolist(), [0, 0] + [1] * 5 + [0] * 5)

    def test_backtest_executes_next_open_and_charges_cost(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=4)
        index = pd.DataFrame({"open": [100, 110, 121, 121], "close": [100, 110, 121, 121]}, index=dates, dtype=float)
        position = pd.Series([1.0, 1.0, 0.0, 0.0], index=dates)
        ret = backtest(index, position, cost=0.001)
        # 第 2 日开盘买入（成本 0.1%），第 2 日内无涨跌；第 3 日隔夜 +10%
        self.assertAlmostEqual(ret.iloc[0], -0.001)
        self.assertAlmostEqual(ret.iloc[1], 0.10)
        self.assertAlmostEqual(ret.iloc[2], -0.001, places=6)

    def test_performance_max_drawdown(self) -> None:
        metrics = performance(pd.Series([0.1, -0.5, 0.1]))
        self.assertAlmostEqual(metrics["最大回撤"], 0.5)


if __name__ == "__main__":
    unittest.main()
