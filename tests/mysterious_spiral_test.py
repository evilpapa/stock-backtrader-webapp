"""神秘螺旋策略测试。"""

import unittest

import backtrader as bt
import pandas as pd

from src.strategy import MysteriousSpiralStrategy


def make_feed(closes: list[float]) -> bt.feeds.PandasData:
	"""用收盘价序列构造日线数据。"""
	dates = pd.date_range("2024-01-01", periods=len(closes), freq="B")
	frame = pd.DataFrame(
		{
			"open": closes,
			"high": [close * 1.01 for close in closes],
			"low": [close * 0.99 for close in closes],
			"close": closes,
			"volume": 100_000,
		},
		index=dates,
	)
	return bt.feeds.PandasData(dataname=frame)


class MysteriousSpiralStrategyTest(unittest.TestCase):
	def test_monthly_rebalance_selects_highest_rps_assets(self):
		"""月初应基于上月末 RPS，等权选取排名前 N 的标的。"""
		cerebro = bt.Cerebro(cheat_on_open=True)
		cerebro.broker.setcash(100_000)
		cerebro.broker.setcommission(commission=0)
		cerebro.adddata(make_feed([100 + index * 1.0 for index in range(90)]), name="Leader")
		cerebro.adddata(make_feed([100 + index * 0.5 for index in range(90)]), name="RunnerUp")
		cerebro.adddata(make_feed([100 - index * 0.2 for index in range(90)]), name="Laggard")
		cerebro.addstrategy(
			MysteriousSpiralStrategy,
			rps_window=20,
			td_lookback=5,
			top_n=2,
			require_perfected_setup=False,
		)

		strategy = cerebro.run()[0]
		self.assertTrue(strategy.rebalance_history)
		snapshot = strategy.rebalance_history[-1]
		self.assertEqual(set(snapshot["selected_names"]), {"Leader", "RunnerUp"})
		self.assertAlmostEqual(snapshot["target_weights"]["Leader"], 0.5)
		self.assertAlmostEqual(snapshot["target_weights"]["RunnerUp"], 0.5)
		self.assertEqual(snapshot["target_weights"]["Laggard"], 0.0)


if __name__ == "__main__":
	unittest.main()
