import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from utils.etf_momentum_backtest import (
	EQUAL_WEIGHT_NAME,
	STRATEGY_NAME,
	build_etf_momentum_weight_frame,
	run_etf_momentum_backtest,
)


def make_price_frame(closes: list[float]) -> pd.DataFrame:
	dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
	close = np.array(closes, dtype=float)
	return pd.DataFrame(
		{
			"Open": close,
			"High": close + 1.0,
			"Low": close - 1.0,
			"Close": close,
			"Volume": 1000000,
		},
		index=dates,
	)


class EtfMomentumBacktestServiceTest(unittest.TestCase):
	def test_build_weight_frame_accepts_strategy_rebalance_history(self):
		frame = build_etf_momentum_weight_frame(
			[
				{
					"date": pd.Timestamp("2024-01-10").date(),
					"target_weights": np.array([0.25, 0.75]),
				}
			],
			["ETF A", "ETF B"],
		)

		self.assertEqual(frame.columns.tolist(), ["Date", "ETF A", "ETF B", "权重合计"])
		self.assertAlmostEqual(frame.loc[0, "权重合计"], 1.0)

	def test_run_etf_momentum_backtest_builds_and_saves_result_frames(self):
		assets = [
			{"symbol": "AAA", "name": "上涨ETF"},
			{"symbol": "BBB", "name": "震荡ETF"},
			{"symbol": "CCC", "name": "下跌ETF"},
		]
		price_data = {
			"AAA": make_price_frame([100.0 + index * 0.5 for index in range(90)]),
			"BBB": make_price_frame([100.0 + np.sin(index / 5) for index in range(90)]),
			"CCC": make_price_frame([120.0 - index * 0.2 for index in range(90)]),
		}

		with tempfile.TemporaryDirectory() as tmp:
			output_dir = Path(tmp)
			frames = run_etf_momentum_backtest(
				assets=assets,
				benchmark_symbol="AAA",
				benchmark_name="上涨ETF",
				start_date="2024-01-01",
				end_date="2024-03-31",
				initial_cash=100000.0,
				momentum_window=10,
				rebalance_days=5,
				output_dir=output_dir,
				price_data=price_data,
			)

			self.assertEqual(frames.metrics["策略"].tolist(), [STRATEGY_NAME, "上涨ETF", EQUAL_WEIGHT_NAME])
			self.assertEqual(frames.returns.columns.tolist(), ["Date", STRATEGY_NAME, "上涨ETF", EQUAL_WEIGHT_NAME])
			self.assertEqual(frames.cumulative.columns.tolist(), ["Date", STRATEGY_NAME, "上涨ETF", EQUAL_WEIGHT_NAME])
			self.assertEqual(frames.drawdown.columns.tolist(), ["Date", STRATEGY_NAME, "上涨ETF", EQUAL_WEIGHT_NAME])
			self.assertIn("权重合计", frames.weights.columns)
			self.assertFalse(frames.weights.empty)
			self.assertTrue(((frames.weights["权重合计"] - 1.0).abs() < 1e-6).any())

			for filename in [
				"performance_metrics.csv",
				"daily_returns.csv",
				"cumulative_returns.csv",
				"drawdowns.csv",
				"daily_weights.csv",
			]:
				self.assertTrue((output_dir / filename).exists(), filename)


if __name__ == "__main__":
	unittest.main()
