"""周度开盘模拟：无未来信号、整手和项目佣金。"""
import unittest
import numpy as np
import pandas as pd
from src.strategy.auction_weekly_backtest import simulate_weekly


class AuctionBacktestTest(unittest.TestCase):
    def test_weekly_signal_timing_and_commission(self):
        cal=pd.bdate_range('2026-01-05',periods=12)
        data=pd.DataFrame([{'symbol':f'{i:02d}','date':d,'open_proxy':10.,'alpha':float(i)}
                           for i in range(10) for d in cal])
        eq,trades=simulate_weekly(data,cal,factor='alpha',initial_cash=10000.)
        self.assertEqual(trades.iloc[0].date,cal[5])
        self.assertEqual(trades.iloc[0].signal_date,cal[4])
        self.assertEqual(trades.iloc[0].symbol,'09')
        self.assertEqual(trades.iloc[0].shares,900)
        self.assertEqual(trades.iloc[0].commission,5.)
        self.assertAlmostEqual(eq.iloc[5].equity,9995.)
        self.assertTrue((eq.cash>=0).all())
        # 信号日之后更新因子不会影响第一次交易
        data.loc[data.date>cal[4],'alpha']=np.arange(len(data.loc[data.date>cal[4]]))
        _,changed=simulate_weekly(data,cal,factor='alpha',initial_cash=10000.)
        self.assertEqual(changed.iloc[0].symbol,'09')

    def test_missing_open_does_not_substitute_another_stock(self):
        cal=pd.bdate_range('2026-01-05',periods=12)
        data=pd.DataFrame([{'symbol':f'{i:02d}','date':d,'open_proxy':(np.nan if i==9 and d==cal[5] else 10.),'alpha':float(i)}
                           for i in range(10) for d in cal])
        _,trades=simulate_weekly(data,cal,factor='alpha')
        self.assertFalse((trades.date==cal[5]).any())
