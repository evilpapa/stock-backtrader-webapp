"""离线测试分钟因子构建和输入版本变化后的重算。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import build_intraday_minute_factors as builder
from src.datahub.minute_batch_repository import MinuteBatchRepository
from src.datahub.models import DataKind, DataRequest, DataResult


class FakeService:
    def __init__(self, repo):
        self.repo = repo

    def get_cached(self, kind, request, source=None):
        result = self.repo.query(kind, request, source=source)
        return None if result is None else result.data

    def close(self):
        pass


class MinuteFactorBuildTest(unittest.TestCase):
    def test_resume_and_changed_input(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            repo = MinuteBatchRepository(root / 'input')
            req = DataRequest(symbols=('000001.SZ',), start='20251101', end='20251130235959', frequency='1m', adjust='none', options={'download':False,'fill_data':False})
            times = pd.date_range('2025-11-03 09:31', periods=120, freq='min').append(pd.date_range('2025-11-03 13:01', periods=120, freq='min'))
            bars = pd.DataFrame({'symbol':'000001.SZ', 'datetime':times, 'open':10., 'close':[10+i/10000 for i in range(240)], 'volume':100.})
            repo.save(DataResult(bars, 'xtquant', DataKind.MINUTE, metadata={'data_version':'test'}), req)
            snapshot = pd.DataFrame({'con_code':['000001.SZ'], 'trade_date':['20251031']})
            read_parquet = pd.read_parquet
            def read(path, *args, **kwargs):
                return snapshot.copy() if str(path) == 'data/intraday_factors/csi500/snapshots.parquet' else read_parquet(path, *args, **kwargs)
            argv = ['build', '--start','2025-11-01','--end','2025-11-30','--batch-size','1', '--input-dir',str(root/'input'),'--output-dir',str(root/'output')]
            with patch.object(builder.pd, 'read_parquet', side_effect=read), patch.object(builder, 'create_service', return_value=FakeService(repo)), patch.object(sys, 'argv', argv), patch.object(builder, 'daily_factors', wraps=builder.daily_factors) as calculate:
                builder.main()
                self.assertEqual(calculate.call_count, 1)
                builder.main()
                self.assertEqual(calculate.call_count, 1)
                bars.loc[0, 'close'] = 10.01
                repo.save(DataResult(bars, 'xtquant', DataKind.MINUTE, metadata={'data_version':'changed'}), req)
                builder.main()
                self.assertEqual(calculate.call_count, 2)
            output = next((root/'output').rglob('*.parquet'))
            self.assertEqual(len(read_parquet(output).columns) - 2, 39)
            self.assertEqual(json.loads(output.with_suffix('.json').read_text())['input_data_version'], 'changed')


if __name__ == '__main__': unittest.main()
