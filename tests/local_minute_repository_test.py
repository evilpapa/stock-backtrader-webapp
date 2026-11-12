"""本地分钟文件的单日过滤、来源追溯和时间边界测试。"""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from scripts.build_local_minute_factors import normalize_bars
from src.datahub.local_minute_repository import LocalMinuteRepository
from src.datahub.models import DataKind, DataRequest


class LocalMinuteRepositoryTest(unittest.TestCase):
    def test_annual_read_and_missing_daily(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)/'year=2021'; directory.mkdir()
            df = pd.DataFrame({'ts_code':['000001.SZ','000001.SZ','600000.SH'],
                'trade_time':['2021-01-04 09:30:00','2021-01-05 09:30:00','2021-01-04 09:30:00'],
                'open':[10.,11.,12.], 'high':[10.,11.,12.], 'low':[10.,11.,12.],
                'close':[10.,11.,12.], 'vol':[100.,200.,300.], 'amount':[1000.,2200.,3600.]})
            df.to_parquet(directory/'2021.parquet',index=False)
            repo = LocalMinuteRepository(root)
            try:
                request=DataRequest(symbols=('000001.SZ',),start='20210104',end='20210104',frequency='1m')
                result=repo.query(DataKind.MINUTE,request)
                self.assertEqual(len(result.data),1)
                self.assertEqual(result.data.iloc[0]['volume'],100.)
                self.assertEqual(len(result.metadata['data_version']),64)
                self.assertEqual(result.metadata['adjust'],'none_assumed')
                missing=DataRequest(symbols=('000001.SZ',),start='20260105',end='20260105',frequency='1m')
                self.assertIsNone(repo.query(DataKind.MINUTE,missing))
                with self.assertRaises(ValueError):
                    repo.query(DataKind.MINUTE,DataRequest(symbols=('000001.SZ',),start='20210104',end='20210105',frequency='1m'))
            finally: repo.close()

    def test_continuous_minutes_keep_close_and_drop_0930(self):
        times=['09:30','09:31','11:30','13:01','14:59','15:00']
        frame=pd.DataFrame({'symbol':'000001.SZ','datetime':pd.to_datetime(['2021-01-04 '+t for t in times]),
                            'close':[1.,2.,3.,4.,5.,6.], 'volume':[1.,2.,3.,4.,5.,6.]})
        got=normalize_bars(frame)
        self.assertTrue(got.empty)
        complete_times=pd.date_range('2021-01-04 09:31',periods=120,freq='min').append(pd.date_range('2021-01-04 13:01',periods=120,freq='min'))
        complete=pd.DataFrame({'symbol':'000001.SZ','datetime':complete_times,'close':1.,'volume':2.})
        complete.loc[239, 'volume']=6.
        got=normalize_bars(complete)
        self.assertEqual(len(got),240)
        self.assertEqual(got.volume.iloc[-1],6.)
        with self.assertRaises(ValueError): normalize_bars(pd.concat([frame,frame.iloc[[0]]]))

if __name__ == '__main__': unittest.main()
