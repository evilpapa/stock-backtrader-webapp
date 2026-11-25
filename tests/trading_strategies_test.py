"""Native strategy signals -> actual shared paper fills; only synthetic data."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import backtrader as bt
import numpy as np
import pandas as pd

from examples.strategy_execution import main, read_weights
from src.strategy import BaseStrategy
from src.strategy.sector_rotation_dual import SectorRotationDualStrategy, make_mock_data
from src.trading import ExecutionEngine, PaperBroker, PortfolioLedger, Quote
from src.trading.strategies import (
    STRATEGIES, backtrader_targets, dual_rotation_latest_target, dual_rotation_targets, next_trade_date,
    run_backtrader_signals, timing_targets, to_backtrader_ohlcv, weight_targets, write_native_weights,
)
from src.trading.targets import target_weights
from src.utils.datahub_universe import StockUniverseSnapshot


class StrategyAdapterTest(unittest.TestCase):
    def setUp(self):
        self.days = pd.bdate_range("2024-02-01", periods=101)
        self.prices = {}
        for symbol, drift in (("000001.SZ", .03), ("600000.SH", .01)):
            close = 10 + np.arange(100) * drift + .1 * np.sin(np.arange(100))
            self.prices[symbol] = pd.DataFrame({"open": close, "close": close, "high": close * 1.01,
                "low": close * .99, "volume": 1_000_000, "amount": 10_000_000}, index=self.days[:-1])

    def test_all_backtrader_strategies_generate_executable_native_signals(self):
        snapshot = StockUniverseSnapshot(self.days[0], pd.DataFrame([
            {"code": code, "name": code, "listing_date": "2020-01-01", "is_st": False,
             "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": cap}
            for code, cap in (("000001.SZ", 8.), ("600000.SH", 12.))]))
        params = {
            "ma": {"maperiod": 3},
            "macross": {"fast_length": 3, "slow_length": 6},
            "etf_momentum": {"momentum_window": 5},
            "qb_etf_momentum": {"period": 5, "top_n": 1, "high_return_mode": True},
            "leading_rotation": {"momentum_window": 5, "top_l": 1},
            "sector_rotation": {"momentum_window": 5, "top_l": 1},
            "mysterious_spiral": {"rps_window": 10, "td_lookback": 5, "top_n": 1},
            "turtle_trading": {"allow_short": False, "entry_period": 5, "exit_period": 3,
                               "atr_period": 3, "risk_pct": .001, "max_units": 1},
            "small_cap": {"universe_snapshot": snapshot, "stock_num": 1, "pool_num": 2,
                "rebalance_days": 2, "avoid_months": (), "market_guard": False,
                "vol_days": 5, "rev_days": 5, "amt_days": 5, "shape_days": 5,
                "atr_days": 5, "amount_z_days": 5},
        }
        generated = set()
        for spec in STRATEGIES.values():
            if spec.kind != "backtrader":
                continue
            with self.subTest(strategy=spec.strategy_id):
                signals = run_backtrader_signals(spec.strategy_id, self.prices, self.days,
                                                params=params.get(spec.strategy_id), initial_cash=100_000.)
                self.assertTrue(signals, spec.strategy_id)
                for signal in signals:
                    self.assertEqual(next_trade_date(signal.signal_date, self.days), signal.trade_date)
                    self.assertLessEqual(sum(target_weights(signal.to_frame()).values()), 1 + 1e-8)
                # Submit the first positive native portfolio to the real public engine.
                signal = next((s for s in signals if sum(s.weights.values()) > 0), signals[0])
                with tempfile.TemporaryDirectory() as directory:
                    ledger = PortfolioLedger(Path(directory) / "portfolio.sqlite")
                    broker = PaperBroker("synthetic")
                    engine = ExecutionEngine(ledger, broker, spec.strategy_id)
                    now = datetime.fromisoformat(signal.trade_date).replace(hour=10, tzinfo=ZoneInfo("Asia/Shanghai"))
                    quotes = {s: Quote(s, 10., now, "mock") for s in signal.weights}
                    try:
                        ledger.create_portfolio("synthetic", spec.strategy_id, 100_000., signal.trade_date)
                        result = signal.execute(engine, quotes, now=now)
                        self.assertIn(result["status"], {"completed", "completed_with_deviation"})
                        if sum(signal.weights.values()) > .01:
                            self.assertTrue(ledger.orders("synthetic", spec.strategy_id))
                    finally:
                        engine.close()
                        ledger.close()
                generated.add(spec.strategy_id)
        self.assertEqual(generated, {s.strategy_id for s in STRATEGIES.values() if s.kind == "backtrader"})

    def test_actual_calendar_holidays_and_short_rejection(self):
        calendar = pd.to_datetime(["2026-09-30", "2026-10-08"])
        self.assertEqual(next_trade_date("2026-09-30", calendar), "2026-10-08")
        with self.assertRaisesRegex(ValueError, "after signal"):
            next_trade_date("2026-10-08", calendar)
        with self.assertRaisesRegex(ValueError, "allow_short"):
            run_backtrader_signals("turtle_trading", self.prices, self.days)
        with self.assertRaisesRegex(ValueError, "short"):
            weight_targets("ma", {self.days[0]: {"000001.SZ": -.2}}, self.days)
        with self.assertRaisesRegex(ValueError, "leveraged"):
            weight_targets("ma", {self.days[0]: {"000001.SZ": 1.2}}, self.days)

    def test_order_intents_include_risk_liquidation_without_future_fill(self):
        class ForcedExit(BaseStrategy):
            def next(self):
                if len(self) == 1:
                    self._track_order(self.buy(size=100))
                elif len(self) == 3:
                    self._track_order(self.close())
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(10_000.)
        cerebro.adddata(bt.feeds.PandasData(dataname=self.prices["000001.SZ"].iloc[:3]), name="000001.SZ")
        cerebro.addstrategy(ForcedExit)
        strategy = cerebro.run()[0]
        # Last exit has no future bar/fill, but must still be captured as cash.
        self.assertEqual(strategy.execution_order_history[str(self.days[2].date())]["sizes"]["000001.SZ"], 0)
        self.assertEqual(strategy.getposition().size, 100)

    def test_dual_native_overlap_is_added(self):
        day = self.days[0]
        result = SimpleNamespace(weights=pd.DataFrame({"w": [.6]}, index=[day]),
                                 holdings={day: {"pos": ["000001.SZ", "600000.SH"], "rev": ["000001.SZ"]}})
        target = dual_rotation_targets(result, self.days)[0]
        self.assertAlmostEqual(target.weights["000001.SZ"], .7)
        self.assertAlmostEqual(target.weights["600000.SH"], .3)

    def test_dual_uses_original_strategy_result(self):
        data = make_mock_data(n_etf=6, n_industry=3, n_days=100)
        symbols = {name: f"51000{i}.SH" for i, name in enumerate(data.close.columns)}
        result = SectorRotationDualStrategy(use_dtw=False, top_n=2).run(data)
        signals = dual_rotation_targets(result, data.close.index, symbol_map=symbols)
        self.assertTrue(signals)
        self.assertGreater(sum(signals[-1].weights.values()), 0.)
        self.assertLessEqual(sum(signals[-1].weights.values()), 1.)

    def test_timing_uses_unshifted_exposure_and_explicit_basket(self):
        positions = pd.Series([1., 0., .5], index=self.days[:3])
        baskets = {self.days[0]: {"000001.SZ": .5, "600000.SH": .5},
                   self.days[2]: {"600000.SH": 1.}}
        signals = timing_targets(positions, baskets, self.days)
        self.assertEqual(signals[0].trade_date, str(self.days[1].date()))
        self.assertEqual(signals[1].weights, {})
        self.assertEqual(signals[2].weights, {"600000.SH": .5})
        with self.assertRaisesRegex(ValueError, "constituent"):
            timing_targets(positions, {}, self.days)

    def test_fcf_native_export_roundtrip_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for strategy in ("free_cash_flow", "free_cash_flow_account"):
                write_native_weights({self.days[0]: pd.Series({"000001.SZ": .6}),
                                      self.days[1]: pd.Series(dtype=float)}, root / "native.csv")
                weights = read_weights(root / "native.csv")
                self.assertEqual(weights[self.days[1]], {})
                pd.DataFrame({"trade_date": self.days[:3], "is_open": [1, 1, 1]}).to_csv(root / "calendar.csv", index=False)
                with contextlib.redirect_stdout(io.StringIO()):
                    main(["generate", "--strategy", strategy, "--input", str(root / "native.csv"),
                          "--calendar", str(root / "calendar.csv"), "--output", str(root / "targets.csv")])
                frame = pd.read_csv(root / "targets.csv")
                self.assertEqual(set(frame.strategy_id), {strategy})
                self.assertEqual(frame.trade_date.nunique(), 2)

    def test_datahub_datetime_feed_preserves_metadata_amount_and_session(self):
        frame = self.prices["000001.SZ"].iloc[:3].reset_index(names="datetime")
        frame["datetime"] = pd.to_datetime(frame.datetime).dt.tz_localize("Asia/Shanghai")
        frame.attrs = {"source": "mock", "adjust": "none", "frequency": "1d", "data_version": "v1"}
        converted = to_backtrader_ohlcv(frame)
        self.assertEqual(list(converted.columns), ["date", "open", "high", "low", "close", "volume", "amount"])
        self.assertEqual(converted.attrs, frame.attrs)
        self.assertEqual(list(converted.index), list(self.days[:3]))
        signals = run_backtrader_signals("just_buy_hold", {"000001.SZ": frame}, self.days)
        self.assertTrue(signals)
        integer_dates = frame.drop(columns="datetime").assign(date=[20240201, 20240202, 20240205])
        self.assertEqual(list(to_backtrader_ohlcv(integer_dates).index), list(self.days[:3]))

    def test_catalog_covers_concrete_exported_backtrader_classes(self):
        import src.strategy as strategies
        concrete = {name for name in strategies.__all__ if name.endswith("Strategy") and name != "BaseStrategy"}
        registered = {spec.class_name for spec in STRATEGIES.values() if spec.kind == "backtrader"}
        self.assertEqual(concrete, registered)

    def test_month_open_signal_is_not_shifted_twice(self):
        signals = run_backtrader_signals("mysterious_spiral", self.prices, self.days,
            params={"rps_window": 10, "td_lookback": 5, "top_n": 1}, initial_cash=100_000.)
        self.assertTrue(signals)
        self.assertEqual(signals[0].signal_date, "2024-02-29")
        self.assertEqual(signals[0].trade_date, "2024-03-01")
        self.assertEqual(len(signals), 4)

    def test_dual_latest_requires_week_end_and_preserves_original_target(self):
        native = {"signal_date": pd.Timestamp("2026-11-13"), "target": {"510300.SH": .7}}
        strategy = SimpleNamespace(latest_target=lambda data: native)
        signal = dual_rotation_latest_target(strategy, None, pd.to_datetime(["2026-11-13", "2026-11-16"]))
        self.assertEqual(signal.trade_date, "2026-11-16")
        self.assertEqual(signal.weights, native["target"])
        native["signal_date"] = pd.Timestamp("2026-11-12")
        with self.assertRaisesRegex(ValueError, "final trading session"):
            dual_rotation_latest_target(strategy, None, pd.to_datetime(["2026-11-12", "2026-11-13"]))

    def test_generic_cli_replay_uses_selected_strategy_and_cash_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prices = root / "reference/raw/daily"
            prices.mkdir(parents=True)
            for day in ("20261113", "20261116"):
                pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": day, "open": 10.,
                               "close": 10., "pre_close": 10., "vol": 1000}]).to_parquet(prices / f"{day}.parquet")
            from src.trading.targets import write_targets
            write_targets(weight_targets("ma", {pd.Timestamp("2026-11-12"): {"000001.SZ": .8},
                                                pd.Timestamp("2026-11-13"): {}},
                          pd.to_datetime(["2026-11-12", "2026-11-13", "2026-11-16"])), root / "targets.csv")
            with contextlib.redirect_stdout(io.StringIO()):
                main(["backtest", "--strategy", "ma", "--targets", str(root / "targets.csv"),
                      "--reference-dir", str(root / "reference"), "--output-dir", str(root / "out"),
                      "--capital", "10000"])
            metrics = json.loads((root / "out/metrics.json").read_text())
            self.assertEqual(metrics["strategy"], "ma")
            self.assertEqual(metrics["fills"], 2)
            self.assertEqual(metrics["final_holdings"], 0)

    def test_timing_manifest_runs_original_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prices["000001.SZ"].rename_axis("date").to_csv(root / "index.csv")
            index = self.days[:-1]
            pd.DataFrame({"flow_breadth": .6, "main_net_ratio": .01, "diffusion": .6}, index=index).rename_axis("date").to_csv(root / "factors.csv")
            pd.DataFrame({"style_gap": 0.}, index=index).rename_axis("date").to_csv(root / "gap.csv")
            write_native_weights({day: {"000001.SZ": 1.} for day in index}, root / "basket.csv")
            pd.DataFrame({"date": self.days}).to_csv(root / "calendar.csv", index=False)
            (root / "manifest.json").write_text(json.dumps({"index": "index.csv", "factors": "factors.csv",
                "style_gap": "gap.csv", "constituents": "basket.csv"}))
            with contextlib.redirect_stdout(io.StringIO()):
                main(["generate", "--strategy", "micro_cap_timing_plus", "--input", str(root / "manifest.json"),
                      "--calendar", str(root / "calendar.csv"), "--output", str(root / "targets.csv")])
            frame = pd.read_csv(root / "targets.csv")
            self.assertEqual(frame.trade_date.nunique(), len(index))
            self.assertTrue(frame.symbol.isna().any())
            self.assertTrue(frame.target_weight.gt(0).any())

    def test_dual_manifest_runs_original_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = make_mock_data(n_etf=6, n_industry=3, n_days=100)
            manifest = {"params": {"use_dtw": False, "top_n": 2},
                        "symbol_map": {name: f"51000{i}.SH" for i, name in enumerate(data.close.columns)}}
            for key in ("open", "close", "shares", "index_heat"):
                getattr(data, key).rename_axis("date").to_csv(root / f"{key}.csv")
                manifest[key] = f"{key}.csv"
            data.industry.rename("industry").rename_axis("symbol").to_csv(root / "industry.csv")
            manifest["industry"] = "industry.csv"
            pd.DataFrame({"date": data.close.index}).to_csv(root / "calendar.csv", index=False)
            (root / "manifest.json").write_text(json.dumps(manifest))
            with contextlib.redirect_stdout(io.StringIO()):
                main(["generate", "--strategy", "sector_rotation_dual", "--input", str(root / "manifest.json"),
                      "--calendar", str(root / "calendar.csv"), "--output", str(root / "targets.csv")])
            frame = pd.read_csv(root / "targets.csv")
            self.assertEqual(set(frame.strategy_id), {"sector_rotation_dual"})
            self.assertGreater(frame.trade_date.nunique(), 1)

    def test_small_cap_manifest_reads_point_in_time_universe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"prices": {}, "universe_snapshots": {str(self.days[0].date()): "universe.csv"},
                "params": {"stock_num": 1, "pool_num": 2, "rebalance_days": 2,
                    "avoid_months": [], "market_guard": False, "vol_days": 5, "rev_days": 5,
                    "amt_days": 5, "shape_days": 5, "atr_days": 5, "amount_z_days": 5}}
            for code, frame in self.prices.items():
                name = f"{code}.csv"
                frame.rename_axis("date").to_csv(root / name)
                manifest["prices"][code] = name
            pd.DataFrame([{"code": code, "name": code, "listing_date": "2020-01-01", "is_st": False,
                "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 8.}
                for code in self.prices]).to_csv(root / "universe.csv", index=False)
            pd.DataFrame({"date": self.days}).to_csv(root / "calendar.csv", index=False)
            (root / "manifest.json").write_text(json.dumps(manifest))
            with contextlib.redirect_stdout(io.StringIO()):
                main(["generate", "--strategy", "small_cap", "--input", str(root / "manifest.json"),
                      "--calendar", str(root / "calendar.csv"), "--output", str(root / "targets.csv")])
            frame = pd.read_csv(root / "targets.csv")
            self.assertTrue(frame.target_weight.gt(0).any())
            self.assertEqual(set(frame.strategy_id), {"small_cap"})

    def test_all_commands_expose_help_without_strategy_or_broker(self):
        for command in ("generate", "plan", "execute", "backtest", "paper", "watch", "status", "cancel"):
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main([command, "--help"])
                self.assertEqual(raised.exception.code, 0)

    def test_intraday_import_preserves_original_execution_date(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pd.DataFrame([{"signal_date": "2026-11-13", "trade_date": "2026-11-16",
                "symbol": "000001.SZ", "target_weight": .5}]).to_csv(root / "native.csv", index=False)
            pd.DataFrame({"date": ["2026-11-13", "2026-11-16"]}).to_csv(root / "calendar.csv", index=False)
            with contextlib.redirect_stdout(io.StringIO()):
                main(["generate", "--strategy", "intraday46", "--input", str(root / "native.csv"),
                      "--calendar", str(root / "calendar.csv"), "--output", str(root / "targets.csv")])
            frame = pd.read_csv(root / "targets.csv")
            self.assertEqual(frame.trade_date.iloc[0], "2026-11-16")
            self.assertEqual(frame.strategy_id.iloc[0], "intraday46")

    def test_manifest_cli_runs_original_ma(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.prices["000001.SZ"].rename_axis("date").to_csv(root / "price.csv")
            pd.DataFrame({"date": self.days}).to_csv(root / "calendar.csv", index=False)
            (root / "manifest.json").write_text(json.dumps({"prices": {"000001.SZ": "price.csv"}, "params": {"maperiod": 3}}))
            with contextlib.redirect_stdout(io.StringIO()):
                main(["generate", "--strategy", "ma", "--input", str(root / "manifest.json"),
                      "--calendar", str(root / "calendar.csv"), "--output", str(root / "targets.csv")])
            frame = pd.read_csv(root / "targets.csv")
            self.assertTrue(frame.symbol.eq("000001.SZ").all())
            self.assertTrue(frame.signal_date.lt(frame.trade_date).all())


if __name__ == "__main__":
    unittest.main()
