"""DataHub 本地研究缓存请求和元信息传递。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from src.datahub.duckdb_frames import file_sha256, frame_metadata, write_frame
from src.datahub.models import DataKind,DataRequest
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.datahub.research_daily_repository import ResearchDailyRepository


class ResearchDailyRepositoryTest(unittest.TestCase):
    def test_legacy_cache_migrates_only_inside_project(self):
        data = pd.DataFrame({
            'ts_code': ['000001.SZ', '600000.SH'],
            'trade_date': ['20210104', '20210104'],
            'flag': [True, None],
        })
        req = DataRequest(start='20210104', end='20210104')
        with TemporaryDirectory() as root, TemporaryDirectory() as outside:
            for directory in (root, outside):
                path = Path(directory) / 'raw/daily/20210104.parquet'
                path.parent.mkdir(parents=True)
                data.to_parquet(path, index=False)
            with patch('src.datahub.duckdb_frames.PROJECT_ROOT', Path(root)):
                internal = ResearchDailyRepository(root).query(DataKind.DAILY_BULK, req)
                external = ResearchDailyRepository(outside).query(DataKind.DAILY_BULK, req)
            database = Path(root) / 'raw/daily/20210104.duckdb'
            original = database.with_suffix('.parquet')
            self.assertEqual(frame_metadata(database)['legacy_sha256'], file_sha256(original))
            self.assertEqual(internal.metadata['storage'], 'duckdb')
            self.assertEqual(external.metadata['storage'], 'parquet')
            self.assertFalse((Path(outside) / 'raw/daily/20210104.duckdb').exists())
            pd.testing.assert_frame_equal(internal.data, external.data)

    def test_read_by_day_and_symbol(self):
        data = pd.DataFrame({'ts_code':['000001.SZ','600000.SH'],'trade_date':['20210104','20210104'],'close':[1.,2.]})
        with TemporaryDirectory() as root:
            write_frame(Path(root) / 'raw/daily/20210104.duckdb', data)
            service=MarketDataService(DataRouter({}),repository=ResearchDailyRepository(root))
            req=DataRequest(start='20210104',end='20210104',symbols=('000001.SZ',),frequency='1d')
            frame=service.get_cached(DataKind.DAILY_BULK,req)
        self.assertEqual(frame.ts_code.tolist(),['000001.SZ'])
        self.assertEqual(frame.attrs['source'],'tushare_research_duckdb')
        self.assertTrue(frame.attrs['data_version'])
        self.assertEqual(frame.attrs['data_kind'],'daily_bulk')

    def test_reject_incorrect_date(self):
        data = pd.DataFrame({'ts_code':['000001.SZ'],'trade_date':['20210105']})
        with TemporaryDirectory() as root:
            write_frame(Path(root) / 'raw/stock_st/20210104.duckdb', data)
            req=DataRequest(start='20210104',end='20210104')
            with self.assertRaises(ValueError):
                ResearchDailyRepository(root).query(DataKind.ST,req)
