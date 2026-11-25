"""Synthetic target interchange and strategy-isolated execution checks."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.trading import ExecutionEngine, PaperBroker, PortfolioLedger, Quote
from src.trading.replay import read_targets, run_replay
from src.trading.targets import TargetPortfolio, target_weights, validate_targets, write_targets


class TargetPortfolioTest(unittest.TestCase):
    def test_export_roundtrip_preserves_cash_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.csv"
            write_targets([
                TargetPortfolio("ma", "2026-11-12", "2026-11-13", {"000001.SZ": .7}),
                TargetPortfolio("ma", "2026-11-13", "2026-11-16", {}),
            ], path)
            frame = read_targets(path)
            self.assertEqual(set(frame.strategy_id), {"ma"})
            self.assertEqual(target_weights(frame[frame.trade_date.eq("2026-11-16")]), {})
            self.assertEqual(target_weights(frame[frame.trade_date.eq("2026-11-13")]), {"000001.SZ": .7})

    def test_reject_bad_signals_before_orders(self):
        for weights in ({"000001.SZ": float("inf")}, {"000001.SZ": -.1},
                        {"000001.SZ": .6, "600000.SH": .6}):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                TargetPortfolio("ma", "2026-11-13", "2026-11-16", weights).to_frame()
        with self.assertRaises(ValueError):
            TargetPortfolio("ma", "2026-11-16", "2026-11-16", {}).to_frame()
        with self.assertRaises(ValueError):
            TargetPortfolio("ma", "2026-11-13", "2026-11-16", {"": .3}).to_frame()
        frame = TargetPortfolio("ma", "2026-11-13", "2026-11-16", {}).to_frame()
        frame.loc[1] = ["2026-11-13", "2026-11-16", "000001.SZ", .5, "ma"]
        with self.assertRaises(ValueError):
            validate_targets(frame)

    def test_empty_targets_sell_only_owned_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PortfolioLedger(Path(directory) / "test.sqlite")
            broker = PaperBroker("mock")
            engine = ExecutionEngine(ledger, broker, "ma")
            now = datetime(2026, 11, 16, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
            quote = Quote("000001.SZ", 10., now, "synthetic")
            try:
                for strategy in ("ma", "macross"):
                    ledger.create_portfolio("mock", strategy, 10_000., "2026-11-16")
                    ledger.seed_position("mock", strategy, quote.symbol, 100, 100, 10.)
                signal = TargetPortfolio("ma", "2026-11-13", "2026-11-16", {})
                self.assertEqual(signal.execute(engine, {quote.symbol: quote}, now=now)["status"], "completed")
                self.assertFalse(ledger.positions("mock", "ma"))
                self.assertEqual(ledger.positions("mock", "macross")[quote.symbol]["quantity"], 100)
                with self.assertRaisesRegex(ValueError, "strategy"):
                    TargetPortfolio("macross", "2026-11-13", "2026-11-16", {}).execute(
                        engine, {quote.symbol: quote}, now=now)
            finally:
                engine.close()
                ledger.close()

    def test_replay_liquidates_on_explicit_cash_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prices = root / "prices/raw/daily"
            prices.mkdir(parents=True)
            for day in ("20261113", "20261116"):
                pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": day, "open": 10.,
                               "close": 10., "pre_close": 10., "vol": 1000}]).to_parquet(prices / f"{day}.parquet")
            write_targets([
                TargetPortfolio("ma", "2026-11-12", "2026-11-13", {"000001.SZ": .9}),
                TargetPortfolio("ma", "2026-11-13", "2026-11-16", {}),
            ], root / "targets.csv")
            metrics = run_replay(root / "targets.csv", root / "prices", root / "out",
                                 strategy_id="ma", initial_cash=10_000.)
            self.assertEqual(metrics["fills"], 2)
            self.assertEqual(metrics["final_holdings"], 0)
            self.assertEqual(metrics["rebalance_count"], 2)


if __name__ == "__main__":
    unittest.main()
