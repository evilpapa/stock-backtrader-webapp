"""基于模拟快照的成分变化测试。"""
import unittest
import pandas as pd
from scripts.fetch_csi500_history import changes_between_snapshots, has_monthly_coverage


class CSI500HistoryTest(unittest.TestCase):
    def test_changes_only_record_interval_between_snapshots(self):
        frame = pd.DataFrame({'trade_date':['20210129','20210129','20210226','20210226'], 'con_code':['a','b','b','c']})
        result = changes_between_snapshots(frame).set_index('con_code')
        self.assertEqual(result.loc['a','event'], 'observed_removed')
        self.assertEqual(result.loc['c','event'], 'observed_added')
        self.assertEqual(result.loc['c','previous_snapshot'], '20210129')
        self.assertEqual(result.loc['c','snapshot_date'], '20210226')
        self.assertNotIn('effective_date', result.columns)

    def test_partial_cache_is_not_a_complete_quarter(self):
        frame = pd.DataFrame({'trade_date': ['20210129', '20210331']})
        self.assertFalse(has_monthly_coverage(frame, pd.Timestamp('2021-01-01'), pd.Timestamp('2021-03-31')))
        self.assertTrue(has_monthly_coverage(frame, pd.Timestamp('2021-01-01'), pd.Timestamp('2021-01-31')))
