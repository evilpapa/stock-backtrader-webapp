"""以模拟交易日和成分快照验证历史分钟下载计划。"""
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
from scripts.build_tushare_minute_history import make_plan


class TushareMinutePlanTest(unittest.TestCase):
    def test_chunk_size_and_future_members_only_for_data(self):
        days = pd.bdate_range('2021-02-01', periods=45)
        files = [Path(x.strftime('%Y%m%d') + '.parquet') for x in days]
        snapshots = pd.DataFrame({'trade_date':['20201231','20210215'], 'con_code':['000001.SZ','000002.SZ']})
        with patch.object(Path, 'glob', return_value=files), patch('scripts.build_tushare_minute_history.pd.read_parquet', return_value=snapshots):
            actual_days, tasks = make_plan('2021-02-01','2021-04-05')
        self.assertEqual(len(actual_days),45)
        self.assertEqual(len(set((a,b) for a,b,_ in tasks)),2)
        self.assertIn(('20210201','20210316','000002.SZ'),tasks)
        for a,b,_ in tasks:
            self.assertLessEqual(sum(pd.Timestamp(a) <= d <= pd.Timestamp(b) for d in days),32)
        with self.assertRaises(ValueError): make_plan('2021-01-01','2021-12-31',33)


if __name__ == '__main__': unittest.main()
