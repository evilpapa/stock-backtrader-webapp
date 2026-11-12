"""DataHub 本地研究缓存请求和元信息传递。"""
import unittest
from unittest.mock import patch
import pandas as pd
from src.datahub.models import DataKind,DataRequest
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.datahub.research_daily_repository import ResearchDailyRepository


class ResearchDailyRepositoryTest(unittest.TestCase):
    @patch('pathlib.Path.read_bytes',return_value=b'data')
    @patch('pandas.read_parquet')
    @patch('pathlib.Path.exists',return_value=True)
    def test_read_by_day_and_symbol(self,exists,read,read_bytes):
        read.return_value=pd.DataFrame({'ts_code':['000001.SZ','600000.SH'],'trade_date':['20210104','20210104'],'close':[1.,2.]})
        service=MarketDataService(DataRouter({}),repository=ResearchDailyRepository('/mock'))
        req=DataRequest(start='20210104',end='20210104',symbols=('000001.SZ',),frequency='1d')
        frame=service.get_cached(DataKind.DAILY_BULK,req)
        self.assertEqual(frame.ts_code.tolist(),['000001.SZ'])
        self.assertEqual(frame.attrs['source'],'tushare_research_parquet')
        self.assertTrue(frame.attrs['data_version'])
        self.assertEqual(frame.attrs['data_kind'],'daily_bulk')

    @patch('pandas.read_parquet')
    @patch('pathlib.Path.exists',return_value=True)
    def test_reject_incorrect_date(self,exists,read):
        read.return_value=pd.DataFrame({'ts_code':['000001.SZ'],'trade_date':['20210105']})
        req=DataRequest(start='20210104',end='20210104')
        with self.assertRaises(ValueError):ResearchDailyRepository('/mock').query(DataKind.ST,req)
