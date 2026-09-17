"""小盘股 Backtrader 策略测试。"""

import unittest

import backtrader as bt
import pandas as pd

from src.strategy import Small2PandasData, Small2Strategy
from src.utils.qmt_universe import StockUniverseSnapshot


def make_feed(base: float, daily_return: float, amount: float = 10_000_000) -> Small2PandasData:
	"""生成不触发涨跌停过滤的合成日线。"""
	dates = pd.date_range("2024-01-01", periods=50, freq="D")
	closes = [base * (1 + daily_return) ** index for index in range(len(dates))]
	frame = pd.DataFrame(
		{
			"open": closes,
			"high": [price * 1.01 for price in closes],
			"low": [price * 0.99 for price in closes],
			"close": closes,
			"volume": [amount / price for price in closes],
			"amount": amount,
		},
		index=dates,
	)
	return Small2PandasData(dataname=frame)


class Small2StrategyTest(unittest.TestCase):
	def _snapshot(self) -> StockUniverseSnapshot:
		return StockUniverseSnapshot(
			pd.Timestamp("2024-02-19"),
			pd.DataFrame([
				{"code": "600001.SH", "name": "Small", "listing_date": "20200101", "is_st": False, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 8.0},
				{"code": "600002.SH", "name": "Large", "listing_date": "20200101", "is_st": False, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 15.0},
				{"code": "600003.SH", "name": "ST", "listing_date": "20200101", "is_st": True, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 5.0},
			]),
		)

	def _run(self, market_factors=None, **params):
		cerebro = bt.Cerebro()
		cerebro.adddata(make_feed(10, 0.002), name="600001.SH")
		cerebro.adddata(make_feed(10, 0.001), name="600002.SH")
		cerebro.adddata(make_feed(10, 0.003), name="600003.SH")
		cerebro.broker.setcash(100_000)
		cerebro.broker.setcommission(commission=0)
		strategy_params = {
			"universe_snapshot": self._snapshot(), "market_factors": market_factors,
			"stock_num": 1, "pool_num": 2, "rebalance_days": 1, "listing_days": 375,
			"min_cap": 5, "max_cap": 20, "vol_days": 5, "rev_days": 5, "amt_days": 5,
			"shape_days": 5, "atr_days": 5, "amount_z_days": 5, "market_guard": False,
			"avoid_months": (),
		}
		strategy_params.update(params)
		cerebro.addstrategy(Small2Strategy, **strategy_params)
		return cerebro.run()[0]

	def test_selects_lowest_scoring_eligible_stock(self):
		"""ST 股票应剔除，剩余股票按 qb 评分选择得分最低者。"""
		strategy = self._run()
		snapshot = strategy.rebalance_history[-1]
		self.assertEqual(snapshot["selected_names"], ["600001.SH"])
		self.assertNotIn("600003.SH", snapshot["scores"])
		self.assertEqual(snapshot["target_weights_by_name"]["600003.SH"], 0.0)

	def test_market_guard_reduces_exposure(self):
		"""NHNL、相对收益和涨停数同时恶化时应降低仓位。"""
		factors = pd.DataFrame({"nhnl": [-40], "limit_up_count": [10]}, index=[pd.Timestamp("2024-02-19")])
		strategy = self._run(
			market_factors=factors, market_guard=True, guard_nhnl=-30,
			guard_limit_up=29, guard_rel=1.0, guard_pos=0.3,
		)
		self.assertAlmostEqual(strategy.rebalance_history[-1]["exposure"], 0.3)


if __name__ == "__main__":
	unittest.main()
