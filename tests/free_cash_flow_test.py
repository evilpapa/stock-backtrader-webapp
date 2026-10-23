"""自由现金流策略单元测试（仅模拟数据）。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.datahub import DataKind, DataRequest, DataRouter, MarketDataService
from src.datahub.providers.tushare import TushareProvider
from src.strategy.free_cash_flow import (
    FreeCashFlowParams,
    asof_snapshot,
    backtest_weights,
    build_fundamentals,
    candidate_pool,
    cap_weights,
    quantile_groups,
    rebalance_dates,
    select,
)


def _statements(symbol: str, years: range, *, ocf: float = 100.0, capex: float = 30.0, op: float = 80.0):
    """生成年报 + 三季报累计口径的三表模拟数据。"""
    inc, cf, bs = [], [], []
    for year in years:
        for month, frac, ann in ((9, 0.75, f"{year}-10-28"), (12, 1.0, f"{year + 1}-03-30")):
            end = pd.Timestamp(year, month, 30 if month == 9 else 31)
            keys = {"symbol": symbol, "end_date": end, "ann_date": ann, "f_ann_date": ann, "update_flag": "0"}
            inc.append(keys | {"operate_profit": op * frac, "fin_exp": 2.0 * frac, "n_income_attr_p": 60.0 * frac})
            cf.append(keys | {
                "n_cashflow_act": ocf * frac, "c_pay_acq_const_fiolta": capex * frac, "n_recp_disp_fiolta": 0.0,
                "depr_fa_coga_dpba": 10.0 * frac if month == 12 else np.nan, "amort_intang_assets": 1.0,
                "lt_amort_deferred_exp": 0.0, "use_right_asset_dep": 0.0,
            })
            bs.append(keys | {
                "total_assets": 1000.0, "total_liab": 400.0, "money_cap": 100.0, "trad_asset": 20.0,
                "total_hldr_eqy_exc_min_int": 600.0,
            })
    return pd.DataFrame(inc), pd.DataFrame(cf), pd.DataFrame(bs)


class FundamentalsTest(unittest.TestCase):
    def test_ttm_and_point_in_time(self):
        inc, cf, bs = _statements("000001.SZ", range(2015, 2021))
        fundamentals, annual = build_fundamentals(inc, cf, bs)
        q3 = fundamentals[fundamentals["end_date"] == "2020-09-30"].iloc[0]
        # 三季报 TTM = 75 + 100 - 75 = 100
        self.assertAlmostEqual(q3["n_cashflow_act_ttm"], 100.0)
        self.assertAlmostEqual(q3["fcf_ttm"], 70.0)
        # 三季报前一天不可见，当天可见
        self.assertEqual(asof_snapshot(fundamentals, pd.Timestamp("2020-10-27")).loc["000001.SZ", "end_date"], pd.Timestamp("2019-12-31"))
        self.assertEqual(asof_snapshot(fundamentals, pd.Timestamp("2020-10-28")).loc["000001.SZ", "end_date"], pd.Timestamp("2020-09-30"))
        last = annual[annual["end_date"] == "2020-12-31"].iloc[0]
        self.assertEqual(last["ocf_positive_years"], 5)
        self.assertAlmostEqual(last["capex_growth"], 1.0)

    def test_revised_report_keeps_first_announcement_date(self):
        inc, cf, bs = _statements("000001.SZ", range(2019, 2021))
        revised = cf.iloc[[-1]].assign(update_flag="1", f_ann_date="2021-08-01", ann_date="2021-08-01", n_cashflow_act=200.0)
        fundamentals, _ = build_fundamentals(inc, pd.concat([cf, revised]), bs)
        row = fundamentals[fundamentals["end_date"] == "2020-12-31"].iloc[0]
        self.assertEqual(row["n_cashflow_act"], 200.0)
        self.assertEqual(row["avail_date"], pd.Timestamp("2021-03-30"))


class SelectionTest(unittest.TestCase):
    def _pool(self) -> pd.DataFrame:
        symbols = [f"{i:06d}.SZ" for i in range(1, 11)]
        frames = [_statements(s, range(2014, 2021), ocf=100 + 10 * i, op=80) for i, s in enumerate(symbols)]
        inc, cf, bs = (pd.concat(parts, ignore_index=True) for parts in zip(*frames))
        fundamentals, annual = build_fundamentals(inc, cf, bs)
        market = pd.DataFrame({
            "total_mv": np.linspace(1000, 2000, 10), "pb": 1.5, "avg_amount": np.arange(10, 20, dtype=float),
            "list_date": pd.Timestamp("2010-01-01"), "is_st": False, "industry": ["银行"] + ["电子"] * 9,
        }, index=symbols)
        market.loc[symbols[1], "is_st"] = True
        return candidate_pool(pd.Timestamp("2021-06-11"), market, fundamentals, annual,
                              FreeCashFlowParams(liquidity_keep=0.8, quality_keep=1.0))

    def test_filters_st_finance_and_liquidity(self):
        pool = self._pool()
        self.assertNotIn("000001.SZ", pool.index)  # 银行（同时流动性后 20%）
        self.assertNotIn("000002.SZ", pool.index)  # ST
        self.assertEqual(len(pool), 8)
        self.assertTrue((pool["fcf_yield"] > 0).all())
        self.assertTrue(pool["composite"].notna().all())

    def test_select_and_quantile_groups(self):
        pool = self._pool()
        picked = select(pool, "fcf_yield", size=3, weighting="fcf", cap=0.5)
        self.assertEqual(len(picked), 3)
        self.assertAlmostEqual(picked.sum(), 1.0)
        groups = quantile_groups(pool, "composite", groups=4, first_size=2)
        self.assertEqual([len(g) for g in groups], [2, 2, 2, 2])


class WeightAndBacktestTest(unittest.TestCase):
    def test_cap_weights_redistributes(self):
        weights = cap_weights(pd.Series([90.0, 5.0, 3.0, 2.0] + [1.0] * 8), 0.10)
        self.assertAlmostEqual(weights.sum(), 1.0)
        self.assertLessEqual(weights.max(), 0.10 + 1e-9)

    def test_rebalance_dates_second_friday(self):
        days = pd.bdate_range("2024-01-01", "2024-12-31")
        dates = rebalance_dates(days, "2024-01-01", "2024-12-31")
        self.assertEqual([d.strftime("%Y-%m-%d") for d in dates], ["2024-03-08", "2024-06-14", "2024-09-13", "2024-12-13"])

    def test_backtest_drifts_and_rebalances(self):
        idx = pd.bdate_range("2024-01-01", periods=6)
        returns = pd.DataFrame({"A": [0, 0.1, 0.1, 0, 0, 0], "B": [0, 0, 0, 0.1, 0, 0]}, index=idx)
        targets = {idx[0]: pd.Series({"A": 1.0}), idx[2]: pd.Series({"B": 1.0})}
        result = backtest_weights(returns, targets)
        np.testing.assert_allclose(result["return"].to_numpy(), [0.1, 0.1, 0.1, 0, 0])
        self.assertEqual(result["turnover"].loc[idx[3]], 2.0)


class TushareFinancialPeriodTest(unittest.TestCase):
    def test_vip_pagination_and_revision_order(self):
        calls = []

        class FakePro:
            def cashflow_vip(self, **kwargs):
                calls.append(kwargs)
                rows = [
                    {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "20240320", "f_ann_date": "20240320",
                     "report_type": "1", "update_flag": "1", "n_cashflow_act": 2.0},
                    {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "20240320", "f_ann_date": "20240320",
                     "report_type": "1", "update_flag": "0", "n_cashflow_act": 1.0},
                    {"ts_code": "833243!1.BJ", "end_date": "20231231", "ann_date": "20240320", "f_ann_date": "20240320",
                     "report_type": "1", "update_flag": "0", "n_cashflow_act": 9.0},
                ]
                return pd.DataFrame(rows if kwargs["offset"] == 0 else [])

        provider = TushareProvider(pro_client=FakePro())
        provider._VIP_PAGE_SIZE = 3
        service = MarketDataService(DataRouter({"tushare": provider}, {DataKind.FINANCIAL: {"providers": ("tushare",)}}))
        frame = service.get_financial(DataRequest(table="cashflow", options={"period": "20231231"}), use_cache=False)
        self.assertEqual([c["offset"] for c in calls], [0, 3])
        self.assertEqual(frame["n_cashflow_act"].tolist(), [2.0])
        self.assertEqual(frame["symbol"].tolist(), ["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
