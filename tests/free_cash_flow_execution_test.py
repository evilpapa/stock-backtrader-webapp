import unittest
import pandas as pd
import numpy as np
from src.strategy.free_cash_flow_execution import constrained_weights, select_with_buffer, simulate, ExecutionParams


class ExecutionTest(unittest.TestCase):
    def test_constraints_and_infeasible_cash(self):
        p = pd.DataFrame({'fcf_ttm': [10., 5., 4., 3.], 'industry': ['A', 'A', 'B', 'C']}, index=list('abcd'))
        w = constrained_weights(p, .3, .4)
        self.assertLessEqual(w.max(), .3 + 1e-9)
        self.assertLessEqual(w.groupby(p.industry).sum().max(), .4 + 1e-9)
        self.assertAlmostEqual(w.sum(), 1.)
        w = constrained_weights(p.iloc[:2], .08, .25)
        self.assertAlmostEqual(w.sum(), .16)

    def test_buffer_retains_old_first(self):
        p = pd.DataFrame({'composite': [5, 4, 3, 2, 1]}, index=list('abcde'))
        self.assertEqual(set(select_with_buffer(p, 3, {'c', 'd', 'e'}, 4).index), {'a', 'c', 'd'})

    def test_lots_minimum_fee_and_cash(self):
        dates = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04'])
        base = pd.DataFrame({'000001.SZ': [10., 10., 10.], '000002.SZ': [100., 100., 100.]}, index=dates)
        prices = {k: base.copy() for k in ['open', 'close', 'pre_close', 'high', 'low']}
        prices['volume'] = base * 100
        target = {pd.Timestamp('2024-01-01'): pd.Series({'000001.SZ': .5, '000002.SZ': .5})}
        industry = {pd.Timestamp('2024-01-01'): pd.Series({'000001.SZ': 'A', '000002.SZ': 'B'})}
        ledger, orders, pos = simulate(prices, target, industry, '2024-01-02', '2024-01-04', ExecutionParams(initial_cash=20000, slippage=0))
        self.assertTrue((orders.quantity % 100 == 0).all())
        self.assertTrue((orders.commission >= 5).all())
        self.assertGreaterEqual(ledger.cash.min(), -1e-8)
        self.assertLessEqual(pos.market_value.sum() + orders.commission.sum(), 20000 + 1e-8)

    def test_corporate_action_preserves_whole_lots_and_value(self):
        dates = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04'])
        close = pd.DataFrame({'000001.SZ': [10., 9.5, 9.5]}, index=dates)
        prices = {k: close.copy() for k in ['open', 'close', 'high', 'low']}
        prices['pre_close'] = pd.DataFrame({'000001.SZ': [10., 9.5, 9.5]}, index=dates)
        prices['volume'] = close * 100
        targets = {pd.Timestamp('2024-01-01'): pd.Series({'000001.SZ': 1.}),
                   dates[1]: pd.Series({'000001.SZ': 1.})}
        industries = {d: pd.Series({'000001.SZ': 'A'}) for d in targets}
        ledger, orders, positions = simulate(prices, targets, industries, str(dates[0].date()), str(dates[-1].date()),
                                               ExecutionParams(initial_cash=10000, slippage=0))
        self.assertTrue((positions.shares % 100 == 0).all())
        self.assertTrue((orders.quantity % 100 == 0).all())
        self.assertGreater(ledger.loc[dates[1], 'corporate_action_cash'], 0)
        self.assertAlmostEqual(ledger.loc[dates[1], 'nav'], ledger.loc[dates[0], 'nav'])

    def test_suspended_stock_not_bought(self):
        dates = pd.to_datetime(['2024-01-02'])
        base = pd.DataFrame({'000001.SZ': [np.nan]}, index=dates)
        prices = {k: base.copy() for k in ['open', 'close', 'pre_close', 'high', 'low', 'volume']}
        target = {pd.Timestamp('2024-01-01'): pd.Series({'000001.SZ': 1.})}
        ledger, orders, _ = simulate(prices, target, {pd.Timestamp('2024-01-01'): pd.Series(dtype=object)}, '2024-01-02', '2024-01-02')
        self.assertTrue(orders.empty)
        self.assertEqual(ledger.nav.iloc[0], 200000)


if __name__ == '__main__':
    unittest.main()
