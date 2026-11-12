"""离线验证竞价阶段边界、无效报价和开盘价缺失。"""
import unittest
import numpy as np
import pandas as pd
from src.strategy.auction_factors import auction_daily_factors


def tick(time,last,open_=0,bid=None,ask=None,low=9.,high=11.,pre=10.):
    return {'security_id':'000001.SZ','md_date':20260331,'md_time':time,'last':last,'open':open_,
            'pre_close':pre,'bid1':last if bid is None else bid,'ask1':last if ask is None else ask,'min':low,'max':high}


class AuctionFactorsTest(unittest.TestCase):
    def test_boundary_invalid_quote_and_open(self):
        data=pd.DataFrame([tick(91500000,50,bid=0,ask=0),tick(91503000,9.8),tick(91959000,10.1),
                           tick(92000000,10.3),tick(92459000,9.9),tick(92500000,10.,10.0)])
        factor,quality=auction_daily_factors(data)
        a=factor.iloc[0]; q=quality.iloc[0]
        self.assertAlmostEqual(a.ret_open2AH1,10/10.1-1)
        self.assertAlmostEqual(a.ret_open2AL1,10/9.8-1)
        self.assertAlmostEqual(a.ret_open2AH2,10/10.3-1)
        self.assertAlmostEqual(a.ret_open2AL2,10/9.9-1)
        self.assertAlmostEqual(a.diverge_A1,(10.1-9.8)/10)
        self.assertAlmostEqual(a.ret_overnight,0)
        self.assertEqual(q.stage1_valid,2)
        self.assertEqual(q.stage2_valid,2)

    def test_conflicting_open_and_insufficient_stage(self):
        data=pd.DataFrame([tick(91503000,9.8),tick(92000000,10.3),tick(92459000,9.9),
                           tick(92500000,10.,10.),tick(92503000,10.,10.1)])
        f,q=auction_daily_factors(data)
        self.assertTrue(np.isnan(f.iloc[0].ret_open2AH2))
        self.assertTrue(np.isnan(f.iloc[0].diverge_A1))
        self.assertEqual(q.iloc[0].open_values,2)
        self.assertTrue(np.isnan(q.iloc[0].auction_open))

    def test_duplicate_times_are_rejected(self):
        d=pd.DataFrame([tick(91503000,9.8),tick(91503000,9.8)])
        with self.assertRaisesRegex(ValueError,'重复'):
            auction_daily_factors(d)
