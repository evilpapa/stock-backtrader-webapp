"""本地竞价行情仓库的请求和来源校验；不访问真实数据。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from src.datahub.auction_tick_repository import AUCTION_FIELDS, AuctionTickRepository, normalize_auction_duplicates
from src.datahub.models import DataKind, DataRequest


class AuctionRepositoryTest(unittest.TestCase):
    @patch('src.datahub.auction_tick_repository.pq.read_table')
    @patch('src.datahub.auction_tick_repository.pq.ParquetFile')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists',return_value=True)
    def test_source_and_filter(self,exists,read_text,parquet,read_table):
        read_text.return_value=json.dumps({'date':'20260331','rows':2,'archive_sha256':'abc','version':2,'archive':'a.rar','member':'a.csv'})
        pf=MagicMock();pf.metadata.num_rows=2;pf.schema_arrow.metadata={b'archive_sha256':b'abc'};parquet.return_value=pf
        read_table.return_value.to_pandas.return_value=pd.DataFrame({'security_id':['000001.SZ'],
                                                                   'md_date':[20260331], 'md_time':[91500000]})
        req=DataRequest(symbols=('000001.SZ',),start='20260331',end='20260331',frequency='tick')
        result=AuctionTickRepository('/mock', storage='parquet').query(DataKind.TICK,req)
        self.assertEqual(result.source,'auction_tick_parquet')
        self.assertEqual(result.data.attrs['frequency'],'tick')
        self.assertEqual(read_table.call_args.kwargs['filters'],[('security_id','in',['000001.SZ'])])
        self.assertEqual(result.data.attrs['duplicates_removed'], 0)

    def test_csv_partition_filters_and_versions_content(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '202611' / '20261123.csv'
            path.parent.mkdir()
            row = ['000001.SZ', '20261123', '91500000', *(['1'] * 16)]
            header = ','.join(AUCTION_FIELDS) + '\n'
            selected = ','.join(row) + '\n'
            other = selected.replace('000001.SZ', '600000.SH')
            path.write_text(header + selected * 2 + other, encoding='utf-8-sig')
            repo = AuctionTickRepository(directory)
            request = DataRequest(symbols=('000001.SZ',), start='20261123', end='20261123', frequency='tick')
            result = repo.query(DataKind.TICK, request)
            self.assertEqual(result.source, 'auction_tick_csv')
            self.assertEqual(result.data.security_id.tolist(), ['000001.SZ'])
            self.assertEqual(result.data.attrs['duplicates_removed'], 1)
            path.write_text(header + selected + other, encoding='utf-8-sig')
            without_duplicate = repo.query(DataKind.TICK, request)
            self.assertNotEqual(result.metadata['source_csv_sha256'], without_duplicate.metadata['source_csv_sha256'])
            self.assertNotEqual(result.metadata['data_version'], without_duplicate.metadata['data_version'])
            path.write_text(header + selected + other.replace('20261123', '20261124'), encoding='utf-8-sig')
            with self.assertRaisesRegex(ValueError, '日期'):
                repo.query(DataKind.TICK, request)

    def test_exact_duplicates_only(self):
        frame=pd.DataFrame({'security_id':['000001.SZ']*3,'md_date':[20260331]*3,
                            'md_time':[91500000,91500000,91509000],'last':[10.,10.,10.1]})
        cleaned,removed=normalize_auction_duplicates(frame)
        self.assertEqual(removed,1)
        self.assertEqual(len(cleaned),2)
        conflict=frame.copy();conflict.loc[1,'last']=11.
        with self.assertRaises(ValueError):
            normalize_auction_duplicates(conflict)

    def test_rejects_different_days_or_adjusted(self):
        repo=AuctionTickRepository('/mock')
        with self.assertRaises(ValueError):
            repo.query(DataKind.TICK,DataRequest(start='20260330',end='20260331',frequency='tick'))
        with self.assertRaises(ValueError):
            repo.query(DataKind.TICK,DataRequest(start='20260331',end='20260331',frequency='tick',adjust='qfq'))
