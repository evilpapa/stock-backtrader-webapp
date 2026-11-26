"""验证交易日对齐、未来收益区间和缺失日的处理。"""
import unittest
import numpy as np
import pandas as pd
from src.strategy.intraday_factor_research import weekly_research


class WeeklyResearchTest(unittest.TestCase):
    def test_alignment_and_missing_session(self):
        calendar = pd.bdate_range('2026-01-05', periods=20)
        rows = []
        for i in range(10):
            for j, day in enumerate(calendar):
                if i == 0 and j == 2:
                    continue
                rows.append({'symbol':str(i), 'date':day, 'open_proxy':100 + j * (i+1), 'alpha':float(i)})
        data = pd.DataFrame(rows)
        out = weekly_research(data, calendar)
        self.assertEqual(len(out), 1)  # 首周缺一只而不足十只；末周没有足够未来数据
        row = out.iloc[0]
        self.assertEqual(row.signal_date, calendar[9])
        self.assertEqual(row.entry_date, calendar[10])
        self.assertEqual(row.exit_date, calendar[15])
        self.assertEqual(row.n, 10)
        self.assertAlmostEqual(row.group_1, (100+15)/(100+10)-1)
        self.assertAlmostEqual(row.rank_ic, 1.0)
        # 信号日之后的因子值不影响该日的排序。
        data.loc[data.date > calendar[9], 'alpha'] = np.nan
        modified = weekly_research(data, calendar)
        self.assertAlmostEqual(modified.iloc[0].group_1, row.group_1)

    def test_grouping_does_not_use_future_price_availability(self):
        calendar = pd.bdate_range('2026-01-05', periods=15)
        rows = [{'symbol':f'{i:02d}', 'date':day,
                 'open_proxy':(np.nan if i == 0 and j == 5 else 100+j*(i+1)), 'alpha':i}
                for i in range(20) for j,day in enumerate(calendar)]
        row = weekly_research(pd.DataFrame(rows), calendar).iloc[0]
        self.assertEqual(row.signal_n, 20)
        self.assertEqual(row.n, 19)
        self.assertEqual(row.group_1_n, 1)
        self.assertAlmostEqual(row.group_1, (100 + 10*2)/(100+5*2)-1)

    def test_empty_decile_keeps_its_column_and_does_not_shift_ties(self):
        calendar = pd.bdate_range('2026-01-05', periods=15)
        data = pd.DataFrame([
            {'symbol': f'{i:02d}', 'date': day, 'open_proxy': 100.,
             'alpha': i // 4, 'forward_return': np.nan if i < 2 else i / 100}
            for i in range(20) for day in calendar
        ]).sample(frac=1, random_state=4)
        row = weekly_research(data, calendar, returns_column='forward_return').iloc[0]
        self.assertEqual(row.signal_n, 20)
        self.assertEqual(row.n, 18)
        self.assertTrue(np.isnan(row.group_1))
        self.assertEqual(row.group_1_n, 0)
        self.assertEqual(row.group_2_n, 2)
        self.assertAlmostEqual(row.group_2, 0.025)
        self.assertAlmostEqual(row.group_3, 0.045)

    def test_missing_entry_price_excludes_symbol(self):
        calendar = pd.bdate_range('2026-01-05', periods=15)
        rows = [{'symbol':str(i), 'date':day, 'open_proxy':(np.nan if i == 0 and j == 5 else 10+j), 'alpha':i}
                for i in range(10) for j,day in enumerate(calendar)]
        self.assertTrue(weekly_research(pd.DataFrame(rows), calendar).empty)
