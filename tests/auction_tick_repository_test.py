"""本地竞价行情仓库的请求和来源校验；不访问真实数据。"""
import json
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from src.datahub.auction_tick_repository import AuctionTickRepository
from src.datahub.models import DataKind, DataRequest


class AuctionRepositoryTest(unittest.TestCase):
    @patch('src.datahub.auction_tick_repository.pq.read_table')
    @patch('src.datahub.auction_tick_repository.pq.ParquetFile')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists',return_value=True)
    def test_source_and_filter(self,exists,read_text,parquet,read_table):
        read_text.return_value=json.dumps({'date':'20260331','rows':2,'archive_sha256':'abc','version':2,'archive':'a.rar','member':'a.csv'})
        pf=MagicMock();pf.metadata.num_rows=2;pf.schema_arrow.metadata={b'archive_sha256':b'abc'};parquet.return_value=pf
        read_table.return_value.to_pandas.return_value=pd.DataFrame({'security_id':['000001.SZ']})
        req=DataRequest(symbols=('000001.SZ',),start='20260331',end='20260331',frequency='tick')
        result=AuctionTickRepository('/mock').query(DataKind.TICK,req)
        self.assertEqual(result.source,'auction_tick_parquet')
        self.assertEqual(result.data.attrs['frequency'],'tick')
        self.assertEqual(read_table.call_args.kwargs['filters'],[('security_id','in',['000001.SZ'])])

    def test_rejects_different_days_or_adjusted(self):
        repo=AuctionTickRepository('/mock')
        with self.assertRaises(ValueError):
            repo.query(DataKind.TICK,DataRequest(start='20260330',end='20260331',frequency='tick'))
        with self.assertRaises(ValueError):
            repo.query(DataKind.TICK,DataRequest(start='20260331',end='20260331',frequency='tick',adjust='qfq'))
