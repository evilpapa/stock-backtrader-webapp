import unittest

import backtrader as bt
import pandas as pd

from strategy.sector_rotation import SectorRotationStrategy


def make_feed(closes: list[float]) -> bt.feeds.PandasData:
	dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
	rows = []
	prev_close = closes[0]
	for close in closes:
		rows.append(
			{
				"open": prev_close,
				"high": max(prev_close, close) + 0.2,
				"low": min(prev_close, close) - 0.2,
				"close": close,
				"volume": 100000,
			}
		)
		prev_close = close

	return bt.feeds.PandasData(dataname=pd.DataFrame(rows, index=dates))


class SectorRotationStrategyTest(unittest.TestCase):
	def _run(self, feeds: list[tuple[str, bt.feeds.PandasData]], **params):
		cerebro = bt.Cerebro()
		for name, feed in feeds:
			cerebro.adddata(feed, name=name)

		cerebro.broker.setcash(100000.0)
		cerebro.broker.setcommission(commission=0.0)
		cerebro.addstrategy(SectorRotationStrategy, **params)
		results = cerebro.run()
		return results[0], cerebro.broker.getvalue()

	def test_selects_top_positive_sector_etfs(self):
		ai = [100.0 + i * 1.0 for i in range(30)]
		chip = [100.0 + i * 0.7 for i in range(30)]
		real_estate = [100.0 - i * 0.4 for i in range(30)]
		benchmark = [100.0 + i * 0.1 for i in range(30)]

		strategy, final_value = self._run(
			[
				("人工智能ETF", make_feed(ai)),
				("半导体ETF", make_feed(chip)),
				("房地产ETF", make_feed(real_estate)),
				("科创50ETF", make_feed(benchmark)),
			],
			momentum_window=5,
			rebalance_days=5,
			top_l=2,
			benchmark_index=3,
		)

		last_snapshot = strategy.rebalance_history[-1]
		self.assertEqual(set(last_snapshot["selected_names"]), {"人工智能ETF", "半导体ETF"})
		self.assertAlmostEqual(sum(last_snapshot["target_weights"]), 1.0, places=6)
		self.assertEqual(last_snapshot["target_weights_by_name"]["房地产ETF"], 0.0)
		self.assertEqual(last_snapshot["target_weights_by_name"]["科创50ETF"], 0.0)
		self.assertGreater(final_value, 100000.0)

	def test_parameter_injection(self):
		strategy, _ = self._run(
			[("人工智能ETF", make_feed([100.0 + i * 0.2 for i in range(25)]))],
			momentum_window=10,
			rebalance_days=3,
			top_l=1,
			min_trade_value_pct=0.02,
		)

		self.assertEqual(strategy.params.momentum_window, 10)
		self.assertEqual(strategy.params.rebalance_days, 3)
		self.assertEqual(strategy.params.top_l, 1)
		self.assertEqual(strategy.params.min_trade_value_pct, 0.02)


if __name__ == "__main__":
	unittest.main()
