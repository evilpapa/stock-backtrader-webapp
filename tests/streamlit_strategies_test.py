"""所有接入 Streamlit 页面的策略配置、服务层与渲染分发单元测试（仅使用模拟数据）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd

import app
from src.charts.results import draw_multi_line
from src.frames.summary import (
	_annual_return_from_row,
	_cumulative_return_from_row,
	_max_drawdown_from_row,
	_ratio_from_row,
)
from src.utils.datahub_universe import StockUniverseSnapshot
from src.utils.load import load_strategy
from src.utils.mysterious_spiral_backtest import (
	load_mysterious_spiral_results,
	run_mysterious_spiral_backtest,
)
from src.utils.research_strategy_backtest import (
	discover_intraday_result_dirs,
	load_free_cash_flow_account_results,
	load_free_cash_flow_results,
	load_index_timing_results,
	load_intraday_all_factor_results,
	load_micro_cap_timing_results,
	load_sector_rotation_dual_results,
	load_turnover_stability_results,
	run_index_timing_backtest,
)
from src.utils.small_cap_backtest import (
	load_small_cap_results,
	run_small_cap_page_backtest,
)


def _make_upper_ohlcv(closes: list[float], start: str = "2023-01-02") -> pd.DataFrame:
	dates = pd.bdate_range(start, periods=len(closes))
	close = np.array(closes, dtype=float)
	return pd.DataFrame(
		{
			"Open": close * 0.999,
			"High": close * 1.01,
			"Low": close * 0.99,
			"Close": close,
			"Volume": 1_000_000.0,
		},
		index=dates,
	)


def _make_small_cap_bar(base: float, daily_ret: float, periods: int = 80) -> pd.DataFrame:
	dates = pd.bdate_range("2024-01-02", periods=periods)
	closes = [base * (1.0 + daily_ret) ** i for i in range(periods)]
	return pd.DataFrame(
		{
			"date": dates,
			"open": closes,
			"high": [c * 1.01 for c in closes],
			"low": [c * 0.99 for c in closes],
			"close": closes,
			"volume": [10_000_000.0 / c for c in closes],
			"amount": 10_000_000.0,
		}
	)


class StreamlitStrategiesIntegrationTest(unittest.TestCase):
	"""验证 strategy.yaml、app.py 策略分发以及新增策略服务层。"""

	def test_all_yaml_strategies_have_valid_dispatch_and_labels(self):
		"""每个配置在 strategy.yaml 的策略都必须有对应自定义页面或有效单标的策略类。"""
		yaml_strategies = load_strategy("src/config/strategy.yaml")
		expected_strategies = {
			"Ma",
			"MaCross",
			"EtfMomentum",
			"QbEtfMomentum",
			"LeadingRotation",
			"SectorRotation",
			"Small2",
			"MysteriousSpiral",
			"TurtleTrading",
			"SectorRotationDual",
			"FreeCashFlow",
			"MicroCapTimingPlus",
			"TurnoverStability",
			"IntradayAllFactor",
			"IndexTiming",
		}
		self.assertTrue(expected_strategies.issubset(yaml_strategies.keys()))
		strategy_module = import_module("src.strategy")
		for key in yaml_strategies:
			self.assertIn(key, app.STRATEGY_LABELS)
			if key not in app.CUSTOM_STRATEGY_RENDERERS:
				self.assertTrue(
					hasattr(strategy_module, f"{key}Strategy"),
					f"{key} 既未注册自定义页面，也未在 src.strategy 中找到 {key}Strategy",
				)

	def test_summary_metric_parsers_handle_research_and_backtrader_schemas(self):
		"""摘要卡片字段解析需兼容研究脚本（中文简称）与 Backtrader 输出。"""
		research_row = {"年化收益": 0.18, "累计收益": 1.25, "最大回撤": 0.22, "夏普": 1.4, "卡玛": 0.82}
		self.assertAlmostEqual(_annual_return_from_row(research_row), 0.18)
		self.assertAlmostEqual(_cumulative_return_from_row(research_row), 1.25)
		self.assertAlmostEqual(_max_drawdown_from_row(research_row), -0.22)
		self.assertAlmostEqual(_ratio_from_row(research_row, ["夏普比率", "夏普"]), 1.4)
		self.assertAlmostEqual(_ratio_from_row(research_row, ["卡玛比率", "卡玛"]), 0.82)

		nav_row = {"累计净值": 2.5}
		self.assertAlmostEqual(_cumulative_return_from_row(nav_row), 1.5)

	def test_draw_multi_line_converts_nan_to_none(self):
		"""折线图序列化前应把 NaN 转为 None，防止前端 JSON 解析失败。"""
		df = pd.DataFrame({"Date": ["2024-01-01", "2024-01-02"], "val": [np.nan, 1.23]})
		chart = draw_multi_line(df, "test")
		series_data = chart.options["series"][0]["data"]
		self.assertIsNone(series_data[0][1])
		self.assertAlmostEqual(series_data[1][1], 1.23)

	def test_mysterious_spiral_backtest_and_reload(self):
		"""神秘螺旋回测服务应输出完整结果表并支持重新加载。"""
		with tempfile.TemporaryDirectory() as tmp:
			out = Path(tmp)
			assets = [
				{"symbol": "AAA.SH", "name": "标的A"},
				{"symbol": "BBB.SZ", "name": "标的B"},
				{"symbol": "CCC.SH", "name": "标的C"},
			]
			price_data = {
				"AAA.SH": _make_upper_ohlcv([10.0 * (1.003 ** i) for i in range(140)]),
				"BBB.SZ": _make_upper_ohlcv([10.0 * (1.001 ** i) for i in range(140)]),
				"CCC.SH": _make_upper_ohlcv([10.0 * (0.999 ** i) for i in range(140)]),
			}
			frames = run_mysterious_spiral_backtest(
				assets=assets,
				start_date="2023-01-02",
				end_date="2023-07-20",
				initial_cash=500_000.0,
				rps_window=20,
				td_lookback=10,
				td_bonus=25.0,
				top_n=2,
				output_dir=out,
				price_data=price_data,
			)
			self.assertEqual(frames.metrics["策略"].tolist(), ["神秘螺旋策略", "等权重组合"])
			self.assertTrue(frames.metrics["score"].between(0, 100).all())
			self.assertFalse(frames.cumulative.empty)
			self.assertFalse(frames.drawdown.empty)
			reloaded = load_mysterious_spiral_results(out)
			self.assertIsNotNone(reloaded)
			self.assertEqual(reloaded.metrics["策略"].tolist(), ["神秘螺旋策略", "等权重组合"])

	def test_small_cap_page_backtest_and_reload(self):
		"""Small2 页面回测服务应生成指标、净值、回撤并落盘复用。"""
		with tempfile.TemporaryDirectory() as tmp:
			out = Path(tmp)
			as_of = pd.Timestamp("2024-03-01")
			snapshot = StockUniverseSnapshot(
				as_of,
				pd.DataFrame(
					[
						{
							"code": "600001.SH",
							"name": "小盘A",
							"listing_date": "20200101",
							"is_st": False,
							"is_suspended": False,
							"is_delisted": False,
							"float_shares": 1e8,
							"float_market_cap": 10.0,
						},
						{
							"code": "600002.SH",
							"name": "小盘B",
							"listing_date": "20200101",
							"is_st": False,
							"is_suspended": False,
							"is_delisted": False,
							"float_shares": 1e8,
							"float_market_cap": 18.0,
						},
					]
				),
			)
			price_data = {
				"600001.SH": _make_small_cap_bar(10.0, 0.002, periods=80),
				"600002.SH": _make_small_cap_bar(12.0, 0.001, periods=80),
			}
			frames = run_small_cap_page_backtest(
				start_date="2024-03-01",
				end_date="2024-04-25",
				initial_cash=200_000.0,
				stock_num=1,
				pool_num=10,
				rebalance_days=5,
				min_cap=5.0,
				max_cap=50.0,
				output_dir=out,
				price_data=price_data,
				snapshots={as_of: snapshot},
			)
			self.assertEqual(len(frames.metrics), 1)
			self.assertFalse(frames.cumulative.empty)
			self.assertTrue((out / "performance_metrics.csv").exists())
			reloaded = load_small_cap_results(out)
			self.assertIsNotNone(reloaded)
			self.assertFalse(reloaded.universe_snapshot.empty)

	def test_research_loaders_with_synthetic_files(self):
		"""验证 6 个研究型策略的结果加载与评分补算逻辑（完全使用临时模拟文件）。"""
		dates = pd.bdate_range("2024-01-02", periods=60)
		nav_a = np.cumprod(np.full(len(dates), 1.002))
		nav_b = np.cumprod(np.full(len(dates), 1.001))

		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)

			# 1. SectorRotationDual
			dual_dir = root / "dual"
			dual_dir.mkdir()
			pd.DataFrame({"策略": ["双轮配置"], "总收益": [0.2], "年化收益": [0.1], "最大回撤": [-0.1], "夏普": [1.0]}).to_csv(
				dual_dir / "summary.csv", index=False
			)
			pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "双轮配置": nav_a}).to_csv(dual_dir / "nav.csv", index=False)
			pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "w": 0.5, "heat_active": 1.0}).to_csv(
				dual_dir / "weights.csv", index=False
			)
			dual = load_sector_rotation_dual_results(dual_dir)
			self.assertIsNotNone(dual)
			self.assertIn("score", dual.metrics.columns)

			# 2. FreeCashFlow + Account
			fcf_dir = root / "fcf"
			fcf_dir.mkdir()
			pd.DataFrame({"Unnamed: 0": ["增强-FCF加权"], "年化收益": [0.15], "最大回撤": [0.2], "夏普比率": [1.1], "卡玛比率": [0.75]}).to_csv(
				fcf_dir / "performance_metrics.csv", index=False
			)
			pd.DataFrame({"trade_date": dates.strftime("%Y-%m-%d"), "增强-FCF加权": nav_a}).to_csv(
				fcf_dir / "cumulative_returns.csv", index=False
			)
			fcf = load_free_cash_flow_results(fcf_dir)
			self.assertIsNotNone(fcf)
			self.assertTrue(fcf.metrics["score"].notna().all())

			acc_dir = fcf_dir / "account_sim"
			acc_dir.mkdir()
			pd.DataFrame({"scenario": ["25只-约束"], "年化收益": [0.14], "最大回撤": [0.2], "夏普比率": [1.0], "卡玛比率": [0.7]}).to_csv(
				acc_dir / "metrics.csv", index=False
			)
			pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "scenario": "25只-约束", "nav": nav_a * 200_000}).to_csv(
				acc_dir / "daily.csv", index=False
			)
			acc = load_free_cash_flow_account_results(acc_dir)
			self.assertIsNotNone(acc)
			self.assertIn("25只-约束", acc.cumulative.columns)

			# 3. MicroCapTimingPlus
			micro_dir = root / "micro"
			micro_dir.mkdir()
			pd.DataFrame({"Unnamed: 0": ["MA15+底部+顶部"], "年化收益": [0.2], "最大回撤": [0.15], "夏普比率": [1.3], "卡玛比率": [1.3]}).to_csv(
				micro_dir / "performance_metrics.csv", index=False
			)
			pd.DataFrame({"trade_date": dates.strftime("%Y-%m-%d"), "MA15+底部+顶部": nav_a}).to_csv(
				micro_dir / "cumulative_returns.csv", index=False
			)
			micro = load_micro_cap_timing_results(micro_dir)
			self.assertIsNotNone(micro)
			self.assertTrue(micro.metrics["score"].notna().all())

			# 4. TurnoverStability
			turn_dir = root / "turnover"
			turn_dir.mkdir()
			pd.DataFrame(
				{"组合": ["全A_SCR_Top10%"], "区间": ["全区间(2013-2026)"], "年化收益": [0.25], "最大回撤": [0.3], "夏普比率": [1.0], "卡玛比率": [0.83]}
			).to_csv(turn_dir / "performance_metrics.csv", index=False)
			pd.DataFrame({"trade_date": dates.strftime("%Y-%m-%d"), "全A_SCR_Top10%": nav_a}).to_csv(
				turn_dir / "cumulative_returns.csv", index=False
			)
			turn = load_turnover_stability_results(turn_dir)
			self.assertIsNotNone(turn)
			self.assertTrue(turn.metrics["score"].notna().all())

			# 5. IntradayAllFactor
			intra_root = root / "intraday"
			bt_dir = intra_root / "refresh_20261124" / "backtest"
			bt_dir.mkdir(parents=True)
			pd.DataFrame(
				{"date": dates.strftime("%Y-%m-%d"), "nav": nav_a, "benchmark_nav": nav_b, "relative_nav": nav_a / nav_b}
			).to_csv(bt_dir / "nav.csv", index=False)
			(bt_dir / "metrics.json").write_text(json.dumps({"rebalance_count": 12, "total_commission": 120.0}), encoding="utf-8")
			discovered = discover_intraday_result_dirs(intra_root)
			self.assertEqual(discovered, [bt_dir])
			intra = load_intraday_all_factor_results(bt_dir)
			self.assertIsNotNone(intra)
			self.assertEqual(intra.metrics["策略"].tolist(), ["46因子策略", "中证500基准"])

			# 6. IndexTiming (load + run with injected synthetic bars)
			idx_dir = root / "index_timing"
			idx_dir.mkdir()
			bars = pd.DataFrame(
				{
					"open": 3000.0 * nav_a,
					"high": 3030.0 * nav_a,
					"low": 2970.0 * nav_a,
					"close": 3005.0 * nav_a,
				},
				index=pd.bdate_range("2023-01-02", periods=len(dates)),
			)
			run_res = run_index_timing_backtest(
				symbol="000300.SH",
				start_date=str(bars.index[25].date()),
				end_date=str(bars.index[-1].date()),
				ma_window=10,
				fast_ma=5,
				rsrs_window=10,
				zscore_window=15,
				bars=bars,
			)
			self.assertEqual(len(run_res.periods), 1)
			bundle = next(iter(run_res.periods.values()))
			self.assertIn("RSRS_zscore", bundle["cumulative"].columns)
			self.assertTrue(bundle["metrics"]["score"].notna().all())

			# Verify loader reads summary.json + daily.parquet
			(idx_dir / "summary.json").write_text(
				json.dumps({"data": {"symbol": "000300.SH"}, "periods": {"sample": {"strategies": {"MA20": {"annual_return": 0.1, "score": 70.0}}}}}),
				encoding="utf-8",
			)
			pd.DataFrame({"date": dates, "period": "sample", "nav_MA20": nav_a}).to_parquet(idx_dir / "daily.parquet", index=False)
			loaded_idx = load_index_timing_results(idx_dir)
			self.assertIsNotNone(loaded_idx)
			self.assertIn("sample", loaded_idx.periods)


if __name__ == "__main__":
	unittest.main()
