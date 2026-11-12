"""分钟批次缓存使用模拟数据，不依赖行情账号。"""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.datahub.minute_batch_repository import MinuteBatchRepository
from src.datahub.models import BarTimestamp, DataKind, DataRequest, DataResult


class MinuteBatchRepositoryTest(unittest.TestCase):
    def test_tushare_source_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            req = DataRequest(symbols=('000001.SZ',), start='20210104', end='20210131', frequency='1m')
            repo = MinuteBatchRepository(root, source='tushare')
            frame = pd.DataFrame({'symbol':['000001.SZ'], 'close':[10.]})
            repo.save(DataResult(frame, 'tushare', DataKind.MINUTE, timestamp_semantics=BarTimestamp.END), req)
            result = repo.query(DataKind.MINUTE, req, source='tushare')
            self.assertEqual(result.source, 'tushare')
            self.assertEqual(result.timestamp_semantics, BarTimestamp.END)
            with self.assertRaises(ValueError):
                repo.query(DataKind.MINUTE, req, source='xtquant')
            self.assertIsNone(MinuteBatchRepository(root).query(DataKind.MINUTE, req, source='xtquant'))

    def test_round_trip_and_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            repo = MinuteBatchRepository(root)
            req = DataRequest(symbols=('000001.SZ',), start='20260101', end='20260131235959', frequency='1m', options={'fill_data': False, 'download': False})
            frame = pd.DataFrame({'symbol': ['000001.SZ'], 'datetime': [pd.Timestamp('2026-01-02 09:31')], 'close': [10.]})
            result = DataResult(frame, 'xtquant', DataKind.MINUTE, timestamp_semantics=BarTimestamp.START, metadata={'data_version': 'v1'})
            self.assertIsNone(repo.query(DataKind.MINUTE, req, source='xtquant'))
            repo.save(result, req)
            actual = repo.query(DataKind.MINUTE, req, source='xtquant')
            pd.testing.assert_frame_equal(actual.data, frame, check_flags=False)
            self.assertEqual(actual.metadata['data_version'], 'v1')
            self.assertEqual(actual.metadata['options']['fill_data'], False)
            metadata_path = next(Path(root).rglob('*.json'))
            metadata = json.loads(metadata_path.read_text())
            metadata['parquet_sha256'] = 'bad'
            metadata_path.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, '校验失败'):
                repo.query(DataKind.MINUTE, req)

    def test_empty_and_request_identity(self):
        with tempfile.TemporaryDirectory() as root:
            repo = MinuteBatchRepository(root)
            req = DataRequest(symbols=('000001.SZ',), start='20260101', end='20260131', frequency='1m')
            repo.save(DataResult(pd.DataFrame({'symbol': pd.Series(dtype='str')}), 'xtquant', DataKind.MINUTE), req)
            self.assertTrue(repo.query(DataKind.MINUTE, req).data.empty)
            other = DataRequest(symbols=('000002.SZ',), start='20260101', end='20260131', frequency='1m')
            self.assertIsNone(repo.query(DataKind.MINUTE, other))


if __name__ == '__main__':
    unittest.main()
