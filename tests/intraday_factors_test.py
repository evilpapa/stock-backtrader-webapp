"""离线合成分钟行情，检验分钟因子公式与缺失数据处理。"""
import unittest
import numpy as np
import pandas as pd
from examples.intraday_factors import minute_end_bars
from src.datahub.models import DataKind, DataRequest
from src.datahub.providers.xtquant import XtQuantProvider
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.strategy.intraday_factors import daily_factors, smooth_factors


class IntradayFactorsTest(unittest.TestCase):
    def test_xtquant_minute_bars_through_datahub(self):
        times = pd.date_range('2021-01-04 09:30', periods=120, freq='min').append(pd.date_range('2021-01-04 13:00', periods=120, freq='min'))
        close = 10 * np.cumprod(1 + np.linspace(-0.001, 0.002, 240))
        calls = []

        class FakeXtData:
            def get_market_data_ex(self, **kwargs):
                calls.append(kwargs)
                return {'600000.SH': pd.DataFrame({'open':close, 'high':close, 'low':close, 'close':close, 'volume':np.arange(1, 241), 'amount':close * np.arange(1, 241)}, index=times)}

        provider = XtQuantProvider(xtdata_client=FakeXtData())
        service = MarketDataService(DataRouter({'xtquant': provider}, {DataKind.MINUTE: {'providers': ('xtquant',)}}))
        bars = service.get_minute(DataRequest(symbols=('600000.SH',), start='20210104', end='20210104235959', frequency='1m', options={'download': False, 'fill_data': False}))
        self.assertEqual(bars.attrs['source'], 'xtquant')
        self.assertEqual(bars.volume.iloc[0], 100)
        self.assertFalse(calls[0]['fill_data'])
        self.assertEqual(calls[0]['end_time'], '20210104235959')
        with self.assertRaises(ValueError):
            minute_end_bars(bars, 'xtquant', None)
        converted = minute_end_bars(bars, 'xtquant', 'start')
        self.assertEqual(converted.datetime.iloc[0].strftime('%H:%M'), '09:31')
        self.assertEqual(converted.datetime.iloc[-1].strftime('%H:%M'), '15:00')
        self.assertEqual(len(daily_factors(converted)), 1)
        self.assertTrue(daily_factors(bars).empty)

    def test_factor_formulas_and_incomplete_session(self):
        times = pd.date_range('2021-01-04 09:31', periods=120, freq='min').append(pd.date_range('2021-01-04 13:01', periods=120, freq='min'))
        close = 10 * np.cumprod(1 + np.linspace(-0.001, 0.002, 240))
        frame = pd.DataFrame({'symbol':'600000.SH', 'datetime': times, 'open':10., 'close':close, 'volume':np.arange(1, 241)})
        values = daily_factors(frame).iloc[0]
        self.assertAlmostEqual(values['ret_intraday'], close[-1] / 10 - 1)
        self.assertAlmostEqual(values['ratio_volumeH8'], np.arange(211, 241).sum() / np.arange(1, 241).sum())
        self.assertAlmostEqual(values['ret_H8'], close[-1] / close[-31] - 1)
        r = pd.Series(close).pct_change().dropna()
        expected = ((r-r.mean())**3).mean() / r.var(ddof=1)**1.5
        self.assertAlmostEqual(values['real_skew'], expected)
        self.assertEqual(len(values.index) - 2, 39)
        self.assertAlmostEqual(values['ratio_volumeH1'], np.arange(1, 31).sum() / np.arange(1, 241).sum())
        self.assertAlmostEqual(sum(values[f'ratio_volumeH{i}'] for i in range(1, 9)), 1)
        self.assertTrue(daily_factors(frame.iloc[:-1]).empty)

    def test_smoothing_requires_full_window(self):
        frame = pd.DataFrame({'symbol':['a']*5, 'date':pd.date_range('2021-01-01', periods=5), 'value':[1, 2, 3, 4, 5]})
        result = smooth_factors(frame)
        self.assertTrue(result['value'].iloc[:4].isna().all())
        self.assertEqual(result['value'].iloc[4], 3)
