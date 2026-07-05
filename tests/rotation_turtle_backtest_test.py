import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from utils.rotation_backtest import ROTATION_SPECS, run_rotation_backtest
from utils.turtle_backtest import run_turtle_backtest


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


class RotationAndTurtleBacktestServiceTest(unittest.TestCase):
	def test_leading_rotation_service_builds_optional_result_frames(self):
		spec = ROTATION_SPECS["LeadingRotation"]
		spec = spec.__class__(**{**spec.__dict__, "output_dir": Path(tempfile.mkdtemp())})
		assets = [
			{"symbol": "AAA", "name": "龙头A"},
			{"symbol": "BBB", "name": "龙头B"},
		]
		price_data = {
			"AAA": make_price_frame([100.0 + index * 0.8 for index in range(80)]),
			"BBB": make_price_frame([100.0 - index * 0.2 for index in range(80)]),
			"IDX": make_price_frame([100.0 + index * 0.1 for index in range(80)]),
		}

		frames = run_rotation_backtest(
			spec=spec,
			assets=assets,
			benchmark_symbol="IDX",
			benchmark_name="基准ETF",
			start_date="2024-01-01",
			end_date="2024-03-20",
			initial_cash=100000.0,
			momentum_window=10,
			rebalance_days=5,
			top_l=1,
			price_data=price_data,
		)

		self.assertEqual(frames.metrics["策略"].tolist(), [spec.strategy_name, "基准ETF", spec.equal_weight_name])
		self.assertFalse(frames.weights.empty)
		self.assertIsNotNone(frames.selection_frequency)
		self.assertIsNotNone(frames.rebalance_details)
		self.assertTrue((spec.output_dir / "selection_frequency.csv").exists())
		self.assertTrue((spec.output_dir / "rebalance_details.csv").exists())

	def test_sector_rotation_service_excludes_benchmark_from_equal_weight(self):
		spec = ROTATION_SPECS["SectorRotation"]
		spec = spec.__class__(**{**spec.__dict__, "output_dir": Path(tempfile.mkdtemp())})
		assets = [
			{"symbol": "IDX", "name": "科创50ETF"},
			{"symbol": "AAA", "name": "行业A"},
			{"symbol": "BBB", "name": "行业B"},
		]
		price_data = {
			"IDX": make_price_frame([100.0 + index * 0.1 for index in range(80)]),
			"AAA": make_price_frame([100.0 + index * 0.7 for index in range(80)]),
			"BBB": make_price_frame([100.0 - index * 0.1 for index in range(80)]),
		}

		frames = run_rotation_backtest(
			spec=spec,
			assets=assets,
			benchmark_symbol="IDX",
			benchmark_name="科创50ETF",
			start_date="2024-01-01",
			end_date="2024-03-20",
			initial_cash=100000.0,
			momentum_window=10,
			rebalance_days=5,
			top_l=1,
			price_data=price_data,
		)

		self.assertEqual(frames.returns.columns.tolist(), ["Date", spec.strategy_name, "科创50ETF", spec.equal_weight_name])
		self.assertIn("行业A", frames.weights.columns)
		self.assertTrue((spec.output_dir / "daily_weights.csv").exists())

	def test_turtle_service_builds_equity_and_trade_outputs(self):
		with tempfile.TemporaryDirectory() as tmp:
			output_dir = Path(tmp)
			price_data = {
				"AAA": make_price_frame(
					[100.0 + index * 1.5 for index in range(35)]
					+ [152.0 - index * 2.0 for index in range(35)]
				)
			}
			frames = run_turtle_backtest(
				symbol="AAA",
				start_date="2024-01-01",
				end_date="2024-03-10",
				entry_period=10,
				exit_period=5,
				atr_period=10,
				max_units=2,
				risk_pct=0.01,
				lot_size=1,
				initial_cash=100000.0,
				allow_short=True,
				output_dir=output_dir,
				price_data=price_data,
			)

			self.assertIn("value", frames.equity.columns)
			self.assertIn("drawdown", frames.equity.columns)
			self.assertEqual(frames.metrics["策略"].tolist(), ["海龟交易策略"])
			self.assertIn("累计收益率", frames.metrics.columns)
			self.assertIn("卡玛比率", frames.metrics.columns)
			self.assertTrue((output_dir / "equity_curve.csv").exists())
			self.assertTrue((output_dir / "trade_log.csv").exists())
			self.assertTrue((output_dir / "performance_metrics.csv").exists())


if __name__ == "__main__":
	unittest.main()

