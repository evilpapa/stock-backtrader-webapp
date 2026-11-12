"""历史选股研究：报价向量化、成分时点及除权近似。"""
import unittest
import pandas as pd
import numpy as np
from examples.auction_history_research import adjust_open_returns
from src.strategy.auction_factors import auction_daily_factors,auction_daily_factors_vectorized
from src.strategy.intraday_factor_research import weekly_research
from tests.auction_factors_test import tick


class AuctionHistoryResearchTest(unittest.TestCase):
    def test_vectorized_matches_reference(self):
        rows=[tick(91500000,50,bid=0,ask=0),tick(91503000,9.8),tick(91959000,10.1),
              tick(92000000,10.3),tick(92459000,9.9),tick(92500000,10.,10.)]
        x=pd.DataFrame(rows);a,_=auction_daily_factors(x);b,_=auction_daily_factors_vectorized(x)
        pd.testing.assert_frame_equal(a,b,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)

    def test_ex_dividend_adjustment_uses_previous_close(self):
        days=pd.bdate_range('2021-01-04',periods=8)
        quote=pd.DataFrame({'symbol':['a']*8,'date':days,'open_proxy':[10,10,9,9,9,9,9,9],
                            'pre_close':[10,10,9,9,9,9,9,9],'close':[10,10,9,9,9,9,9,9]})
        result=adjust_open_returns(quote,days).set_index('date').loc[days[0],'forward_return']
        self.assertAlmostEqual(result,0.)

    def test_eligibility_is_applied_at_signal_day_not_future(self):
        days=pd.bdate_range('2021-01-04',periods=15)
        rows=[]
        for i in range(11):
            for day in days:
                rows.append({'symbol':str(i),'date':day,'open_proxy':10+i,'alpha':i,
                             'eligible':i!=10,'future':0.01*i})
        frame=pd.DataFrame(rows)
        out=weekly_research(frame,days,eligibility_column='eligible',returns_column='future')
        self.assertEqual(out.iloc[0]['signal_n'],10)
        self.assertEqual(out.iloc[0]['n'],10)
        self.assertAlmostEqual(out.iloc[0]['group_10'],0.09)
        self.assertEqual(set(out.factor),{'alpha'})
