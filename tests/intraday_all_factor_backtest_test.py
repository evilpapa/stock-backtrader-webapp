"""历史 IC 方向只可使用持有期已结束的观测。"""
import unittest
import pandas as pd
from examples.intraday_all_factor_backtest import training_directions

class DirectionTimingTest(unittest.TestCase):
    def test_excludes_future_exit_and_requires_full_window(self):
        history=pd.DataFrame({'exit_date':pd.to_datetime(['2022-01-03','2022-01-10','2022-01-17']), 'rank_ic':[0.2,0.1,-0.9]})
        byfactor={'factor':history}
        self.assertEqual(training_directions(byfactor,pd.Timestamp('2022-01-09'),window=2),{})
        self.assertEqual(training_directions(byfactor,pd.Timestamp('2022-01-10'),window=2),{'factor':1})
        self.assertEqual(training_directions(byfactor,pd.Timestamp('2022-01-17'),window=2),{'factor':-1})

if __name__=='__main__':unittest.main()
