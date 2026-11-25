"""历史 IC 方向只可使用持有期已结束的观测。"""
import unittest
import pandas as pd
from examples.intraday_all_factor_backtest import training_directions, weekly_execution_dates

class DirectionTimingTest(unittest.TestCase):
    def test_excludes_future_exit_and_requires_full_window(self):
        history=pd.DataFrame({'exit_date':pd.to_datetime(['2022-01-03','2022-01-10','2022-01-17']), 'rank_ic':[0.2,0.1,-0.9]})
        byfactor={'factor':history}
        self.assertEqual(training_directions(byfactor,pd.Timestamp('2022-01-09'),window=2),{})
        self.assertEqual(training_directions(byfactor,pd.Timestamp('2022-01-10'),window=2),{'factor':1})
        self.assertEqual(training_directions(byfactor,pd.Timestamp('2022-01-17'),window=2),{'factor':-1})

    def test_weekly_schedule_excludes_partial_week_and_handles_closed_friday(self):
        days = pd.DatetimeIndex(['2026-11-19', '2026-11-23', '2026-11-24', '2026-11-27', '2026-11-30'])
        end = pd.Timestamp('2026-11-23')
        self.assertEqual(weekly_execution_dates(days, end, pd.Timestamp('2026-11-24')),
                         {pd.Timestamp('2026-11-19'): end})

if __name__=='__main__':unittest.main()
