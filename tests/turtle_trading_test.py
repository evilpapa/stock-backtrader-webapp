import unittest

import backtrader as bt
import pandas as pd

from strategy.turtle_trading import TurtleTradingStrategy


def make_feed(closes: list[float], signal_bar: int | None = None, signal_side: str | None = None) -> bt.feeds.PandasData:
	dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
	rows = []
	prev_close = closes[0]
	for idx, close in enumerate(closes):
		open_price = prev_close
		high_price = close + 0.5
		low_price = close - 0.5

		if signal_bar is not None and idx == signal_bar:
			if signal_side == "both":
				high_price = close + 6.0
				low_price = close - 6.0
			elif signal_side == "up":
				high_price = close + 3.0
			elif signal_side == "down":
				low_price = close - 3.0

		rows.append(
			{
				"open": open_price,
				"high": high_price,
				"low": low_price,
				"close": close,
				"volume": 100000,
			}
		)
		prev_close = close

	df = pd.DataFrame(rows, index=dates)
	return bt.feeds.PandasData(dataname=df)


class TurtleTradingStrategyTest(unittest.TestCase):
	def _run(self, feed: bt.feeds.PandasData, **params):
		cerebro = bt.Cerebro()
		cerebro.adddata(feed)
		cerebro.broker.setcash(100000.0)
		cerebro.broker.setcommission(commission=0.0)
		cerebro.addstrategy(TurtleTradingStrategy, **params)
		results = cerebro.run()
		return results[0], cerebro.broker.getvalue()

	def test_long_breakout_and_pyramiding(self):
		closes = [100.0] * 20 + [103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
		strategy, final_value = self._run(
			make_feed(closes, signal_bar=20, signal_side="up"),
			entry_period=20,
			exit_period=10,
			atr_period=5,
			max_units=3,
			risk_pct=0.0015,
			lot_size=1,
			allow_short=False,
		)

		self.assertGreater(strategy.unit_count, 0)
		self.assertEqual(strategy.unit_count, 3)
		self.assertGreater(len(strategy.trade_log), 0)
		self.assertGreater(final_value, 100000.0)

	def test_short_breakout(self):
		closes = [100.0] * 20 + [97.0, 96.0, 95.0, 94.0, 93.0]
		strategy, final_value = self._run(
			make_feed(closes, signal_bar=20, signal_side="down"),
			entry_period=20,
			exit_period=10,
			atr_period=5,
			max_units=2,
			risk_pct=0.2,
			lot_size=1,
			allow_short=True,
		)

		self.assertGreater(len(strategy.trade_log), 0)
		self.assertLess(strategy.trade_log[0]["size"], 0)
		self.assertGreater(final_value, 100000.0)

	def test_stop_exit_resets_position_state(self):
		closes = [100.0] * 20 + [103.0, 104.0, 98.0, 97.0, 97.0]
		strategy, _ = self._run(
			make_feed(closes, signal_bar=20, signal_side="up"),
			entry_period=20,
			exit_period=10,
			atr_period=5,
			max_units=2,
			risk_pct=0.2,
			lot_size=1,
			stop_atr=1.0,
			allow_short=False,
		)

		self.assertEqual(strategy.position.size, 0)
		self.assertEqual(strategy.unit_count, 0)
		self.assertIsNone(strategy.stop_price)

	def test_channel_exit_resets_position_state(self):
		closes = [100.0] * 20 + [103.0, 104.0, 105.0, 103.0, 102.0, 101.0, 101.0]
		strategy, _ = self._run(
			make_feed(closes, signal_bar=20, signal_side="up"),
			entry_period=20,
			exit_period=3,
			atr_period=5,
			max_units=1,
			risk_pct=0.2,
			lot_size=1,
			stop_atr=10.0,
			allow_short=False,
		)

		self.assertEqual(strategy.position.size, 0)
		self.assertEqual(strategy.unit_count, 0)

	def test_ambiguous_breakout_bar_is_skipped(self):
		closes = [100.0] * 20 + [100.0, 100.0, 100.0]
		strategy, final_value = self._run(
			make_feed(closes, signal_bar=20, signal_side="both"),
			entry_period=20,
			exit_period=10,
			atr_period=5,
			max_units=1,
			risk_pct=0.2,
			lot_size=1,
		)

		self.assertEqual(len(strategy.trade_log), 0)
		self.assertEqual(strategy.position.size, 0)
		self.assertEqual(final_value, 100000.0)

	def test_parameter_injection(self):
		strategy, _ = self._run(
			make_feed([100.0] * 30),
			entry_period=25,
			exit_period=15,
			atr_period=10,
			max_units=2,
			lot_size=1,
		)

		self.assertEqual(strategy.params.entry_period, 25)
		self.assertEqual(strategy.params.exit_period, 15)
		self.assertEqual(strategy.params.atr_period, 10)
		self.assertEqual(strategy.params.max_units, 2)


if __name__ == "__main__":
	unittest.main()
