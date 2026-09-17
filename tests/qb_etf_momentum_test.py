"""qb ETF 短周期动量策略测试。"""

import unittest

import backtrader as bt
import pandas as pd

from src.strategy import QbEtfMomentumStrategy


def make_feed(closes: list[float]) -> bt.feeds.PandasData:
	"""由收盘价构造连续日线数据。"""
	dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
	data = pd.DataFrame(
		{
			"open": closes,
			"high": [close + 0.2 for close in closes],
			"low": [close - 0.2 for close in closes],
			"close": closes,
			"volume": 100_000,
		},
		index=dates,
	)
	return bt.feeds.PandasData(dataname=data)


class QbEtfMomentumStrategyTest(unittest.TestCase):
	"""验证从 qb 迁移的 ETF ROC 轮动策略。"""

	def _run(self, feeds: list[tuple[str, bt.feeds.PandasData]], **params):
		cerebro = bt.Cerebro()
		for name, feed in feeds:
			cerebro.adddata(feed, name=name)
		cerebro.broker.setcash(100_000.0)
		cerebro.broker.setcommission(commission=0.0)
		cerebro.addstrategy(QbEtfMomentumStrategy, **params)
		return cerebro.run()[0]

	def test_selects_highest_roc_assets_with_equal_weights(self):
		"""应按 ROC 选择排名前 N 的 ETF，并等权配置。"""
		strategy = self._run(
			[
				("Leader", make_feed([100 + index * 2 for index in range(22)])),
				("RunnerUp", make_feed([100 + index for index in range(22)])),
				("Laggard", make_feed([100 - index * 0.5 for index in range(22)])),
			],
			period=5,
			rebalance_weekday=1,
			top_n=2,
			high_return_mode=True,
		)

		snapshot = strategy.rebalance_history[-1]
		self.assertEqual(snapshot["selected_names"], ["Leader", "RunnerUp"])
		self.assertAlmostEqual(snapshot["target_weights_by_name"]["Leader"], 0.5)
		self.assertAlmostEqual(snapshot["target_weights_by_name"]["RunnerUp"], 0.5)
		self.assertEqual(snapshot["target_weights_by_name"]["Laggard"], 0.0)

	def test_absolute_momentum_gate_reduces_exposure(self):
		"""最强 ROC 低于阈值时，应按 abs_zero_exposure 降仓。"""
		strategy = self._run(
			[
				("WeakA", make_feed([100 - index for index in range(22)])),
				("WeakB", make_feed([100 - index * 0.8 for index in range(22)])),
			],
			period=5,
			rebalance_weekday=1,
			top_n=2,
			abs_top1_threshold=0.0,
			abs_zero_exposure=0.2,
		)

		snapshot = strategy.rebalance_history[-1]
		self.assertAlmostEqual(snapshot["exposure"], 0.2)
		self.assertAlmostEqual(sum(snapshot["target_weights"]), 0.2)

	def test_defensive_leadership_gate_can_clear_position(self):
		"""防御 ETF 主导且收益有限时，应使用 defensive_exposure。"""
		strategy = self._run(
			[
				("518880.SH", make_feed([100 + index * 0.1 for index in range(22)])),
				("511090.SH", make_feed([100 + index * 0.08 for index in range(22)])),
			],
			period=5,
			rebalance_weekday=1,
			top_n=2,
			abs_positive_count_threshold=0,
			defensive_count_threshold=2,
			defensive_exposure=0.0,
			defensive_topn_mean_max=0.1,
		)

		snapshot = strategy.rebalance_history[-1]
		self.assertEqual(snapshot["exposure"], 0.0)
		self.assertEqual(sum(snapshot["target_weights"]), 0.0)


if __name__ == "__main__":
	unittest.main()
