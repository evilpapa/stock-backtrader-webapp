import tempfile
import unittest

import numpy as np
import pandas as pd

from src.strategy.sector_rotation_dual import (
	SectorRotationDualStrategy,
	TushareSectorRotationLoader,
	make_mock_data,
	summarize,
)
from src.strategy.sector_rotation_dual import allocation as alloc
from src.strategy.sector_rotation_dual import factors as fct
from src.strategy.sector_rotation_dual.dtw import dtw_distance_batch, dtw_score
from src.utils.datahub_client import DataHubClient


class FactorTest(unittest.TestCase):
	def setUp(self):
		self.data = make_mock_data(n_etf=12, n_industry=4, n_days=400)

	def test_bias_filter_drops_top_decile_union(self):
		last = fct.bias_filter_mask(self.data.close).iloc[-1]
		self.assertGreaterEqual(last.sum(), 1)
		self.assertLessEqual(last.sum(), 6)

	def test_net_flow_same_industry_same_value(self):
		f = fct.net_flow_percentile(self.data.shares, self.data.close, self.data.industry).iloc[-1]
		for _, grp in self.data.industry.groupby(self.data.industry):
			self.assertEqual(f[grp.index].nunique(), 1)
		self.assertTrue(((f > 0) & (f <= 1)).all())

	def test_baskets_size(self):
		d = self.data.close.index[-1]
		mom = fct.momentum_score(self.data.close).loc[d]
		pos = fct.select_positive(mom, fct.bias_filter_mask(self.data.close).loc[d], 6)
		self.assertEqual(len(pos), 6)

	def test_reverse_score_without_heat_is_flow_only(self):
		d = self.data
		a = fct.reverse_score(d.shares, d.close, None, d.industry)
		b = fct.cs_zscore(fct.net_flow_percentile(d.shares, d.close, d.industry))
		pd.testing.assert_frame_equal(a, b)


class DtwTest(unittest.TestCase):
	def test_identical_is_zero_and_band_limits(self):
		q = np.linspace(1, 2, 20)
		d = dtw_distance_batch(q, np.vstack([q, q[::-1]]), band=2)
		self.assertAlmostEqual(d[0], 0.0)
		self.assertGreater(d[1], 0.1)

	def test_nan_when_short(self):
		self.assertTrue(np.isnan(dtw_score(np.arange(1.0, 50), 40)))


class AllocationTest(unittest.TestCase):
	def test_weight_clip_and_neutral(self):
		w = alloc.score_to_weight(pd.Series([-5.0, 0.0, 5.0, np.nan]))
		self.assertEqual(list(w), [0.2, 0.5, 0.8, 0.5])

	def test_dtw_abstain_degrades_to_two_signals(self):
		tz, g = pd.Series([1.0]), pd.Series([0.5])
		self.assertAlmostEqual(alloc.combine_score(tz, g, pd.Series([np.nan])).iloc[0], 0.75)
		self.assertAlmostEqual(alloc.combine_score(tz, g, pd.Series([1.5])).iloc[0], 1.0)


class StrategyTest(unittest.TestCase):
	def test_end_to_end_mock(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=700)
		res = SectorRotationDualStrategy(use_dtw=False).run(data)
		self.assertTrue(res.nav.notna().all())
		self.assertTrue(res.weights["w"].between(0.2, 0.8).all())
		self.assertTrue(res.heat_used)
		for h in res.holdings.values():
			self.assertLessEqual(len(h["pos"]), 6)
			self.assertLessEqual(len(h["rev"]), 6)

	def test_dtw_runs(self):
		data = make_mock_data(n_etf=6, n_industry=3, n_days=450, seed=1)
		res = SectorRotationDualStrategy(top_n=2, dtw_std_mult=1.0).run(data)
		self.assertGreater(res.weights["dtw_valid"].sum(), 0)

	def test_missing_heat_requires_explicit_opt_in(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=500)
		data.index_heat = None
		with self.assertRaises(ValueError):
			SectorRotationDualStrategy(use_dtw=False).run(data)
		res = SectorRotationDualStrategy(use_dtw=False, allow_missing_heat=True).run(data)
		self.assertFalse(res.heat_used)

	def test_summarize(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=600, seed=2)
		t = summarize(SectorRotationDualStrategy(use_dtw=False, shares_lag=1).run(data))
		self.assertEqual(len(t), 5)
		self.assertLessEqual(t["最大回撤"].max(), 0)


class FakePro:
	"""按 Tushare 接口形状返回合成数据，不访问网络。"""

	def __init__(self):
		rng = np.random.default_rng(0)
		self.days = pd.bdate_range("2019-01-01", periods=400)
		self.etfs = {  # etf -> (index, industry stock prefix)
			"510001.SH": "I1.CSI", "510002.SH": "I2.CSI", "510003.SH": "I3.CSI", "510004.SH": "I4.CSI",
		}
		self.px = {e: 1 + np.cumsum(rng.normal(0, 0.01, len(self.days))) .clip(-0.5) for e in self.etfs}
		self.calls: list[str] = []

	def _d(self, ds):
		return ds.strftime("%Y%m%d")

	def etf_basic(self, **kw):
		return pd.DataFrame(
			{"ts_code": list(self.etfs), "index_code": list(self.etfs.values()), "etf_type": "纯境内"}
		)

	def index_daily(self, ts_code, start_date, end_date):
		days = self.days if ts_code == "000300.SH" else self.days[50:]  # 指数晚于日历起点上市
		return pd.DataFrame({"trade_date": self._d(days), "close": np.linspace(100, 120, len(days))})

	def etf_share_size(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
		if trade_date:
			d = pd.Timestamp(trade_date)
			return pd.DataFrame({"trade_date": [trade_date] * 4, "ts_code": list(self.etfs), "total_size": [50000.0] * 4}) if d in self.days else pd.DataFrame()
		return pd.DataFrame({"trade_date": self._d(self.days), "ts_code": ts_code, "total_share": np.linspace(1e4, 2e4, len(self.days))})

	def fund_daily(self, ts_code=None, trade_date=None, start_date=None, end_date=None):
		if trade_date:
			return pd.DataFrame({"ts_code": list(self.etfs), "amount": [5e4] * 4})
		p = self.px[ts_code]
		return pd.DataFrame({"trade_date": self._d(self.days), "open": p, "close": p, "amount": 5e4})

	def fund_adj(self, ts_code, start_date, end_date):
		return pd.DataFrame({"trade_date": self._d(self.days[::2]), "adj_factor": 1.0})

	def index_weight(self, index_code, start_date, end_date):
		stocks = {"I1.CSI": "A", "I2.CSI": "A", "I3.CSI": "B", "I4.CSI": "C"}[index_code]
		return pd.DataFrame(
			{"index_code": index_code, "con_code": [f"{stocks}1.SH", f"{stocks}2.SH", "Z.SH"],
			"trade_date": "20200630", "weight": [40.0, 30.0, 30.0]}
		)

	def ci_index_member(self, is_new="Y"):
		rows = [(c + n, "行业" + c, "CI" + c, f"{c}{n}.SH") for c in "ABC" for n in "12"]
		return pd.DataFrame(rows, columns=["x", "l1_name", "l1_code", "ts_code"]).drop(columns="x")

	def trade_cal(self, exchange, start_date, end_date):
		d = pd.date_range(start_date, end_date)
		return pd.DataFrame({"cal_date": d.strftime("%Y%m%d"), "is_open": (d.weekday < 5).astype(int)})

	def ci_daily(self, ts_code, start_date, end_date):
		return pd.DataFrame({"trade_date": self._d(self.days), "close": np.linspace(10, 12, len(self.days))})


class FakeDataHubQueryClient:
	"""只模拟 DataHubClient.query，避免缓存单测依赖已废弃的旧客户端。"""

	def __init__(self, backend):
		self.backend = backend

	def query(self, api_name, **kwargs):
		return getattr(self.backend, api_name)(**kwargs)


class LoaderTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.loader = TushareSectorRotationLoader(
			DataHubClient(tushare_client=FakePro()), cache_dir=self.tmp.name, sleep=0
		)

	def tearDown(self):
		self.tmp.cleanup()

	def test_build_pool_and_load(self):
		pool = self.loader.build_pool("2020-07-31", top_k_per_industry=1)
		# I1/I2 同属行业A，取规模排名前1；I3->B；I4->C
		self.assertEqual(set(pool["industry"]), {"行业A", "行业B", "行业C"})
		self.assertEqual(len(pool), 3)
		data = self.loader.load(pool, start="2019-03-01", end="2020-07-31", hist_start="20190101")
		self.assertFalse(data.heat_available)
		self.assertIn("UNAVAILABLE", data.source_flags["index_heat"])
		self.assertEqual(list(data.close.columns), list(data.shares.columns))
		self.assertTrue(data.close.index.equals(data.shares.index))
		# 历史库覆盖整个日历，且指数上市前由行业指数回填（无 NaN）
		self.assertGreater(len(data.history_close), len(data.close))
		self.assertFalse(data.history_close.isna().any().any())

	def test_unavailable_heat_blocks_default_run(self):
		pool = self.loader.build_pool("2020-07-31", top_k_per_industry=1)
		data = self.loader.load(pool, "2019-03-01", "2020-07-31", hist_start="20190101")
		with self.assertRaises(ValueError):
			SectorRotationDualStrategy(use_dtw=False).run(data)


class HeatTest(unittest.TestCase):
	def setUp(self):
		self.days = pd.bdate_range("2024-01-01", periods=10)
		self.pool = pd.DataFrame({"etf": ["E1", "E2"], "index_code": ["I1", "I2"]})
		self.cons = {"I1": ["a", "b"], "I2": ["c"]}

	def test_turnover_heat_is_constituent_median(self):
		from src.strategy.sector_rotation_dual import heat as H

		turn = pd.DataFrame({"a": 1.0, "b": 3.0, "c": 5.0}, index=self.days)
		out = H.turnover_heat(turn, self.cons, self.pool)
		self.assertEqual(list(out.columns), ["E1", "E2"])
		self.assertEqual(out["E1"].iloc[0], 2.0)
		self.assertEqual(out["E2"].iloc[0], 5.0)

	def test_hot_list_heat_zero_after_coverage_nan_before(self):
		from src.strategy.sector_rotation_dual import heat as H

		hot = pd.DataFrame(
			{"trade_date": [self.days[5].strftime("%Y%m%d")] * 2, "ts_code": ["a", "c"], "hot": [10.0, 4.0], "rank": [1, 2]}
		)
		out = H.hot_list_heat(hot, self.cons, self.pool, self.days)
		self.assertTrue(out["E1"].iloc[:5].isna().all())
		self.assertEqual(out["E1"].iloc[5], 10.0)
		self.assertEqual(out["E1"].iloc[6], 0.0)  # 覆盖期内未上榜记 0
		self.assertEqual(out["E2"].iloc[5], 4.0)

	def test_etf_hot_list_and_rank_ic(self):
		from src.strategy.sector_rotation_dual import heat as H

		hot = pd.DataFrame({"trade_date": [self.days[0].strftime("%Y%m%d")], "ts_code": ["E1"], "hot": [7.0], "rank": [1]})
		out = H.etf_hot_list_heat(hot, self.pool, self.days)
		self.assertEqual(out["E1"].iloc[0], 7.0)
		self.assertEqual(out["E2"].iloc[0], 0.0)
		# 完全单调关系 -> IC = 1
		n = 12
		f = pd.DataFrame({f"e{i}": float(i) for i in range(n)}, index=self.days)
		c = pd.DataFrame({f"e{i}": [1.0 + 0.001 * i * k for k in range(10)] for i in range(n)}, index=self.days)
		ic = H.rank_ic(f, c, horizon=5, step=1)
		self.assertAlmostEqual(ic.iloc[0], 1.0)

	def test_heat_ratio_inf_to_nan(self):
		s = pd.DataFrame({"x": [0.0] * 300})
		self.assertTrue(fct.attention_heat_ratio(s).isna().all().all())


class PartialHeatTest(unittest.TestCase):
	def test_reverse_score_falls_back_per_cell_and_heat_active(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=700)
		data.index_heat.iloc[:400] = np.nan  # 热度覆盖晚于起点
		rev = fct.reverse_score(data.shares, data.close, data.index_heat, data.industry)
		flow_only = fct.cs_zscore(fct.net_flow_percentile(data.shares, data.close, data.industry))
		pd.testing.assert_series_equal(rev.iloc[300], flow_only.iloc[300])  # 无热度处=仅净申赎
		self.assertTrue(rev.iloc[-1].notna().all())
		res = SectorRotationDualStrategy(use_dtw=False).run(data)
		w = res.weights["heat_active"]
		self.assertEqual(w.iloc[0], 0.0)
		self.assertGreater(w.iloc[-1], 0.9)


class BoardHeatTest(unittest.TestCase):
	def test_board_map_and_industry_heat(self):
		from src.strategy.sector_rotation_dual import heat as H

		stock_l1 = pd.Series({"s1": "银行", "s2": "银行", "s3": "医药", "s4": "医药"})
		bmap = H.board_industry_map({"B1": ["s1", "s2", "s3"], "B2": ["s4", "x"]}, stock_l1)
		self.assertAlmostEqual(bmap.loc["B1", "银行"], 2 / 3)
		self.assertAlmostEqual(bmap.loc["B2", "医药"], 0.5)  # 未映射成分股计入分母
		days = pd.bdate_range("2024-01-01", periods=5)
		hot = pd.DataFrame({
			"trade_date": [days[2].strftime("%Y%m%d")] * 2, "ts_code": ["B1", "B2"], "hot": [30.0, 10.0], "rank": [1, 2],
		})
		pool = pd.DataFrame({"etf": ["E1", "E2"], "industry": ["银行", "医药"]})
		out = H.board_industry_heat(hot, bmap, pool, days)
		self.assertAlmostEqual(out["E1"].iloc[2], 30 * 2 / 3)
		self.assertAlmostEqual(out["E2"].iloc[2], 30 / 3 + 10 * 0.5)
		self.assertTrue(out["E1"].iloc[:2].isna().all())
		self.assertEqual(out["E1"].iloc[3], 0.0)


class LiveTargetTest(unittest.TestCase):
	def test_latest_target_matches_backtest_signal_and_is_valid(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=700)
		# 截到某个周五，作为“已结束周”的数据末日
		fridays = data.close.index[data.close.index.weekday == 4]
		end = fridays[-5]
		sub = type(data)(
			data.open.loc[:end], data.close.loc[:end], data.shares.loc[:end], data.index_heat.loc[:end], data.industry
		)
		strat = SectorRotationDualStrategy(use_dtw=False)
		t = strat.latest_target(sub)
		self.assertEqual(t["signal_date"], end)
		self.assertAlmostEqual(sum(t["target"].values()), 1.0)
		self.assertTrue(0.2 <= t["w"] <= 0.8)
		# 与完整数据回测在同一信号日的篮子/权重一致（无前视）
		full = strat._signals(data, include_last=False)
		self.assertEqual(full["pos_b"][end], t["pos"])
		self.assertEqual(full["rev_b"][end], t["rev"])
		self.assertAlmostEqual(float(full["w"].loc[end]), t["w"])

	def test_latest_target_rejects_mid_week_data(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=700)
		mid = data.close.index[data.close.index.weekday == 2][-3]
		sub = type(data)(data.open.loc[:mid], data.close.loc[:mid], data.shares.loc[:mid], data.index_heat.loc[:mid], data.industry)
		# 周中数据末日也会被当作周末信号日——调用方(脚本)须保证 asof 为周末交易日；此处仅验证返回日期=数据末日
		self.assertEqual(SectorRotationDualStrategy(use_dtw=False).latest_target(sub)["signal_date"], mid)


class WeekEndTest(unittest.TestCase):
	def test_last_completed_week_end(self):
		with tempfile.TemporaryDirectory() as tmp:
			L = TushareSectorRotationLoader(DataHubClient(tushare_client=FakePro()), cache_dir=tmp, sleep=0)
			# 2026-10-26 周一 -> 上周最后交易日 2026-10-23 周五（FakePro: 周一至周五开市）
			self.assertEqual(L.last_completed_week_end("2026-10-26"), pd.Timestamp("2026-10-23"))
			self.assertEqual(L.last_completed_week_end("2026-10-25"), pd.Timestamp("2026-10-23"))  # 周日
			self.assertEqual(L.last_completed_week_end("2026-10-23"), pd.Timestamp("2026-10-16"))  # 周五当天仍算本周未结束

	def test_empty_recent_result_not_cached(self):
		with tempfile.TemporaryDirectory() as tmp:
			calls = []

			class P:
				def foo(self, trade_date):
					calls.append(trade_date)
					return pd.DataFrame()

			L = TushareSectorRotationLoader(FakeDataHubQueryClient(P()), cache_dir=tmp, sleep=0)
			d = pd.Timestamp.today().strftime("%Y%m%d")
			L._call("foo", trade_date=d)
			L._call("foo", trade_date=d)
			self.assertEqual(len(calls), 2)  # 近期空结果不缓存，每次重取


class RangeSplitTest(unittest.TestCase):
	def test_call_range_splits_history_and_tail_and_dedupes(self):
		with tempfile.TemporaryDirectory() as tmp:
			calls = []

			class P:
				def foo(self, start_date, end_date, ts_code):
					calls.append((start_date, end_date))
					d = pd.date_range(start_date, end_date, freq="D")
					return pd.DataFrame({"trade_date": d.strftime("%Y%m%d"), "v": 1})

			L = TushareSectorRotationLoader(FakeDataHubQueryClient(P()), cache_dir=tmp, sleep=0)
			today = pd.Timestamp.today().normalize()
			df = L._call_range("foo", "20240101", today.strftime("%Y%m%d"), ts_code="x")
			self.assertEqual(len(calls), 2)  # 历史段 + 近期段
			self.assertTrue(df["trade_date"].is_unique)
			self.assertEqual(df["trade_date"].iloc[-1], today.strftime("%Y%m%d"))
			calls.clear()
			L._call_range("foo", "20240101", today.strftime("%Y%m%d"), ts_code="x")
			self.assertEqual(len(calls), 1)  # 历史段命中缓存，仅重取近期段


class FeeModelTest(unittest.TestCase):
	def test_commission_model_uses_project_definition(self):
		from src.utils.commission import ChinaStockCommission

		c = ChinaStockCommission()
		st = SectorRotationDualStrategy(initial_cash=100_000.0)
		# 小额：触发最低 5 元；大额：按比例
		small = st._fee_ratio({}, {"A": 0.05}, 100_000.0)  # 成交 5000 元 -> 比例 0.43 元 -> 取 5 元
		self.assertAlmostEqual(small, c.p.min_comm / 100_000.0)
		big = st._fee_ratio({}, {"A": 1.0}, 100_000_000.0)
		self.assertAlmostEqual(big, c.p.commission)
		# 同时买入+卖出各算一笔
		two = st._fee_ratio({"A": 0.5}, {"B": 0.5}, 100_000_000.0)
		self.assertAlmostEqual(two, 2 * 0.5 * c.p.commission)

	def test_flat_model_matches_report(self):
		st = SectorRotationDualStrategy(fee_model="flat")
		self.assertAlmostEqual(st._fee_ratio({"A": 0.5}, {"B": 0.5}, 1e5), 1.0 * 0.001)

	def test_backtest_runs_with_both_models_and_commission_cheaper(self):
		data = make_mock_data(n_etf=12, n_industry=4, n_days=600, seed=4)
		a = SectorRotationDualStrategy(use_dtw=False).run(data).nav.iloc[-1]
		b = SectorRotationDualStrategy(use_dtw=False, fee_model="flat").run(data).nav.iloc[-1]
		self.assertGreater(a, b)  # 万0.854 < 千一
