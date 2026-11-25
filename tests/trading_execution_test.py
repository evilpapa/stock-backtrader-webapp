"""Offline execution tests. No account, market data, Redis or SDK connection."""
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from src.datahub.models import DataKind, DataRequest
from src.datahub.providers.qmt_trading import QmtTradingProvider
from src.datahub.providers.xtquant import XtQuantProvider
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.trading.execution import ExecutionEngine
from src.trading.market import live_quotes, stock_lot
from src.trading.models import BrokerEvent, OrderDisabled, OrderRequest, Quote
from src.trading.paper import PaperBroker
from src.trading.portfolio import PortfolioLedger
from src.trading.replay import run_replay

NOW = datetime(2026, 11, 16, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
SYMBOL = "000001.SZ"


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "portfolios.sqlite"
        self.ledger = PortfolioLedger(self.path)
        self.ledger.create_portfolio("test", "alpha", 100_000., "2026-11-16")
        self.broker = PaperBroker("test")
        self.engine = ExecutionEngine(self.ledger, self.broker, "alpha")
        self.quote = Quote(SYMBOL, 10., NOW, "mock")

    def tearDown(self):
        self.engine.close()
        self.ledger.close()
        self.temp.cleanup()

    def rebalance(self, targets=None, day="2026-11-16", signal="2026-11-13"):
        return self.engine.rebalance(targets or {SYMBOL: 1.}, {SYMBOL: replace(self.quote, timestamp=datetime.fromisoformat(day).replace(hour=10, tzinfo=NOW.tzinfo))},
                                     signal_date=signal, trade_date=day, now=NOW)

    def reserve(self, side="buy", quantity=1000, client="c1"):
        o = OrderRequest(client, "test", "alpha", "b1", SYMBOL, side, quantity, 10., "2026-11-16")
        self.ledger.reserve(o)
        return o

    def fill(self, client="c1", quantity=100, trade_id="t1", side="buy"):
        event = BrokerEvent("trade", "test", NOW, client, "00123", SYMBOL, side,
                            quantity=quantity, price=10., trade_id=trade_id)
        self.ledger.apply_fill(event, client)
        return event

    def test_end_to_end_buy_dedup_and_commission(self):
        result = self.rebalance()
        self.assertEqual(result["status"], "completed_with_deviation")
        state = self.engine.snapshot({SYMBOL: self.quote})
        self.assertEqual(state["positions"][0]["quantity"], 9900)
        self.assertEqual(state["positions"][0]["sellable"], 0)
        self.assertAlmostEqual(state["cash"], 1000 - 99000 * .0000854)
        self.engine.sync()
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 1)
        self.rebalance()
        self.assertEqual(len(self.broker.requests), 1)

    def test_partial_fills_minimum_commission_once_per_order(self):
        self.reserve(quantity=300)
        self.fill(quantity=100, trade_id="a")
        self.fill(quantity=200, trade_id="b")
        self.assertAlmostEqual(self.ledger.order("c1")["fee"], 5.)
        self.assertAlmostEqual(self.ledger.wallet("test", "alpha")["cash"], 96995.)

    def test_duplicate_fill_survives_database_reopen_and_conflicts_fail(self):
        self.reserve(quantity=100)
        event = self.fill()
        reopened = PortfolioLedger(self.path)
        try:
            self.assertFalse(reopened.apply_fill(event, "c1"))
            with self.assertRaisesRegex(ValueError, "conflicting"):
                reopened.apply_fill(replace(event, quantity=50), "c1")
            self.assertEqual(reopened.positions("test", "alpha")[SYMBOL]["quantity"], 100)
        finally:
            reopened.close()

    def test_t_plus_one_and_sell_cash(self):
        self.rebalance()
        self.assertEqual(self.ledger.available_shares("test", "alpha", SYMBOL), 0)
        with self.assertRaisesRegex(ValueError, "settled"):
            self.reserve(side="sell", quantity=100, client="sell")
        result = self.engine.rebalance({}, {SYMBOL: replace(self.quote, timestamp=NOW + timedelta(days=1))},
                                       signal_date="2026-11-16", trade_date="2026-11-17", now=NOW + timedelta(days=1))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.ledger.positions("test", "alpha"), {})
        self.assertAlmostEqual(self.ledger.wallet("test", "alpha")["cash"], 100000 - 2 * 99000 * .0000854)

    def test_strategy_isolation_on_same_symbol(self):
        self.ledger.create_portfolio("test", "beta", 10_000., "2026-11-16")
        self.ledger.seed_position("test", "beta", SYMBOL, 500, 500, 9.)
        self.rebalance()
        self.assertEqual(self.ledger.positions("test", "beta")[SYMBOL]["quantity"], 500)
        self.assertEqual(self.ledger.wallet("test", "beta")["cash"], 10_000)
        with self.assertRaisesRegex(ValueError, "owned"):
            beta = ExecutionEngine(self.ledger, PaperBroker("test"), "beta")
            beta.cancel(self.ledger.orders("test", "alpha")[0]["client_id"])

    def test_atomic_reservation_prevents_overallocation(self):
        self.reserve(quantity=9000)
        with self.assertRaisesRegex(ValueError, "cash"):
            self.reserve(quantity=2000, client="c2")
        self.assertLess(self.ledger.available_cash("test", "alpha"), 10_000.)

    def test_terminal_order_before_fill_preserves_reservations(self):
        self.reserve(quantity=1000)
        self.ledger.update_status("c1", "filled", "00123", reported=1000)
        self.assertTrue(self.ledger.unresolved("test", "alpha"))
        self.assertAlmostEqual(self.ledger.available_cash("test", "alpha"), 89995.)
        self.fill(quantity=1000)
        self.assertFalse(self.ledger.unresolved("test", "alpha"))
        self.ledger.update_status("c1", "submitted", "00123")
        self.assertEqual(self.ledger.order("c1")["status"], "filled")

    def test_partial_cancel_waits_for_late_trade_then_releases(self):
        self.reserve(quantity=1000)
        self.ledger.update_status("c1", "canceled", "00123", reported=200)
        self.assertAlmostEqual(self.ledger.available_cash("test", "alpha"), 97995.)
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            self.ledger.advance_day("test", "alpha", "2026-11-17")
        self.fill(quantity=200)
        self.assertFalse(self.ledger.unresolved("test", "alpha"))

    def test_timeout_never_resubmits_after_resume(self):
        def timeout(order):
            raise TimeoutError("lost acknowledgement")
        self.broker.submit = timeout
        self.assertEqual(self.rebalance()["status"], "unknown")
        self.broker.submit = lambda order: self.fail("must not resubmit")
        self.assertEqual(self.rebalance()["status"], "unknown")
        self.assertTrue(self.ledger.unresolved("test", "alpha"))

    def test_reject_releases_reservation(self):
        def disabled(order):
            raise OrderDisabled("ORDER_DISABLED")
        self.broker.submit = disabled
        self.assertEqual(self.rebalance()["status"], "rejected")
        self.assertEqual(self.ledger.available_cash("test", "alpha"), 100_000.)
        self.assertFalse(self.ledger.positions("test", "alpha"))

    def test_crash_after_reserving_intent_does_not_resend(self):
        self.reserve()
        self.broker.submit = lambda order: self.fail("must not submit")
        with self.assertRaisesRegex(RuntimeError, "unresolved"):
            self.rebalance()

    def test_sell_before_buy_and_wait_partial(self):
        self.ledger.seed_position("test", "alpha", SYMBOL, 1000, 1000, 10.)
        other = Quote("600000.SH", 10., NOW, "mock")
        self.broker.max_fill = 100
        result = self.engine.rebalance({other.symbol: 1.}, {SYMBOL: self.quote, other.symbol: other},
                                       signal_date="2026-11-13", trade_date="2026-11-16", now=NOW)
        self.assertEqual(result["status"], "waiting_sells")
        self.assertEqual({r.side for r in self.broker.requests.values()}, {"sell"})

    def test_cancel_waits_for_broker_terminal_status(self):
        self.broker.max_fill = 100
        self.rebalance()
        order = self.ledger.orders("test", "alpha")[0]
        self.engine.cancel(order["client_id"])
        self.assertEqual(self.ledger.order(order["client_id"])["status"], "canceled")
        self.assertFalse(self.ledger.unresolved("test", "alpha"))

    def test_odd_lot_liquidation_and_star_lot(self):
        self.ledger.seed_position("test", "alpha", SYMBOL, 137, 137, 10.)
        self.engine.rebalance({}, {SYMBOL: self.quote}, signal_date="2026-11-13", trade_date="2026-11-16", now=NOW)
        self.assertEqual(self.ledger.orders("test", "alpha")[0]["quantity"], 137)
        self.assertEqual(stock_lot("688425.SH"), (200, 1))
        q = replace(self.quote, symbol="688425.SH", buy_min=200, buy_step=1)
        self.assertEqual(q.buy_quantity(199), 0)
        self.assertEqual(q.buy_quantity(235.6), 235)

    def test_plan_input_immutable_and_invalid_weights(self):
        self.rebalance()
        with self.assertRaisesRegex(ValueError, "changed"):
            self.rebalance({SYMBOL: .5})
        with self.assertRaises(ValueError):
            self.rebalance({SYMBOL: float("nan")})

    def test_limit_up_does_not_create_fill(self):
        self.quote = replace(self.quote, upper_limit=10.)
        self.assertEqual(self.rebalance()["status"], "completed_with_deviation")
        self.assertEqual(len(self.ledger.orders("test", "alpha")), 0)

    def test_recover_unknown_partial_by_remark_and_preserve_broker_id(self):
        self.reserve(quantity=1000)
        self.ledger.update_status("c1", "unknown")
        fill = BrokerEvent("trade", "test", NOW, "c1", "00123", SYMBOL, "buy",
                           quantity=100, price=10., trade_id="late")
        self.broker.poll = lambda: [fill]
        self.engine.sync()
        self.assertEqual(self.ledger.order("c1")["broker_id"], "00123")
        self.assertEqual(self.ledger.order("c1")["filled"], 100)

    def test_callback_normalization_error_stops_consumer(self):
        self.engine.queue.put(BrokerEvent("adapter_error", "test", NOW, detail="missing trade timestamp"))
        with self.assertRaisesRegex(RuntimeError, "normalization"):
            self.engine.sync()

    def test_cancel_error_never_releases_pending_buy_cash(self):
        self.reserve(quantity=1000)
        self.ledger.update_status("c1", "submitted", "00123")
        self.engine.queue.put(BrokerEvent("cancel_error", "test", NOW, "c1", "00123",
                                          SYMBOL, "buy", detail="cancel rejected"))
        self.engine.sync()
        self.assertEqual(self.ledger.order("c1")["status"], "submitted")
        self.assertLess(self.ledger.available_cash("test", "alpha"), 90000.)

    def test_invalid_event_identity_cannot_modify_other_strategy(self):
        self.reserve()
        with self.assertRaisesRegex(ValueError, "identity"):
            self.ledger.resolve_event(BrokerEvent("trade", "other", NOW, "c1", "00123",
                                                  SYMBOL, "buy", quantity=100, price=10., trade_id="x"))

    def test_direct_public_fill_api_rejects_wrong_symbol_and_side(self):
        self.reserve()
        wrong = BrokerEvent("trade", "test", NOW, "c1", "00123", "600000.SH", "sell",
                            quantity=100, price=10., trade_id="wrong")
        with self.assertRaisesRegex(ValueError, "matching"):
            self.ledger.apply_fill(wrong, "c1")
        self.assertFalse(self.ledger.positions("test", "alpha"))

    def test_reconciliation_never_adopts_external_positions(self):
        report = self.ledger.reconciliation("test", {"account_id": "test", "cash": 100000.,
            "positions": [{"symbol": SYMBOL, "quantity": 1000, "sellable": 1000}], "orders": []})
        self.assertTrue(report["ok"])
        self.assertEqual(report["unallocated_positions"], {SYMBOL: 1000})
        self.assertFalse(self.ledger.positions("test", "alpha"))
        self.ledger.seed_position("test", "alpha", SYMBOL, 1500, 1500, 10.)
        self.assertFalse(self.ledger.reconciliation("test", {"account_id": "test", "cash": 100000.,
            "positions": [{"symbol": SYMBOL, "quantity": 1000, "sellable": 1000}], "orders": []})["ok"])

    def test_live_stale_signal_quote_and_account_guards(self):
        self.broker.requires_fresh_quotes = True
        with self.assertRaisesRegex(ValueError, "within 7"):
            self.rebalance(signal="2026-10-30")
        with self.assertRaisesRegex(ValueError, "stale"):
            self.rebalance()

    def test_live_checks_dispatch_through_fake_broker_with_fresh_market_data(self):
        self.broker.requires_fresh_quotes = True
        self.broker.snapshot = lambda: {"account_id": "test", "cash": 100000.,
                                       "positions": [], "orders": []}
        self.quote = replace(self.quote, source="xtquant", upper_limit=11., lower_limit=9.)
        self.assertEqual(self.rebalance()["status"], "completed_with_deviation")
        self.assertEqual(len(self.broker.requests), 1)

    def test_reservation_shared_across_database_connections(self):
        self.reserve(quantity=6000)
        other = PortfolioLedger(self.path)
        try:
            with self.assertRaisesRegex(ValueError, "cash"):
                other.reserve(OrderRequest("c2", "test", "alpha", "b1", SYMBOL, "buy", 5000, 10., "2026-11-16"))
        finally:
            other.close()

    def test_corporate_proxy_preserves_value_and_is_idempotent(self):
        self.ledger.seed_position("test", "alpha", SYMBOL, 101, 101, 10.)
        self.ledger.corporate_action_proxy("test", "alpha", "2026-11-16", {SYMBOL: (10., 8.)})
        pos = self.ledger.positions("test", "alpha")[SYMBOL]
        self.assertEqual(pos["quantity"], 126)
        self.assertAlmostEqual(self.ledger.wallet("test", "alpha")["cash"] + pos["quantity"] * 8, 101010.)
        self.ledger.corporate_action_proxy("test", "alpha", "2026-11-16", {SYMBOL: (10., 8.)})
        self.assertEqual(self.ledger.positions("test", "alpha")[SYMBOL]["quantity"], 126)


class FakeTrader:
    def __init__(self):
        self.client = SimpleNamespace(account_id="test", call=lambda *a: {"ok": True})
        self.calls = []
        self.callback = None
        self.asset = SimpleNamespace(account_id="test", cash=100000., frozen_cash=0.)

    def register_callback(self, callback): self.callback = callback
    def start(self): pass
    def subscribe(self, account): return 0
    def stop(self): pass
    def query_stock_orders(self, account, **kwargs):
        self.calls.append(("orders", kwargs))
        return []
    def query_stock_trades(self, account, **kwargs):
        self.calls.append(("trades", kwargs))
        return []
    def query_stock_asset(self, account): return self.asset
    def query_stock_positions(self, account): return []
    def order_stock_result(self, *args):
        self.calls.append(("submit", args))
        return {"order_sys_id": "0000123"}
    def cancel_order_stock_sysid(self, *args):
        self.calls.append(("cancel", args))
        return 0


class QmtAdapterTest(unittest.TestCase):
    def setUp(self):
        self.trader = FakeTrader()
        self.provider = QmtTradingProvider("test", trader=self.trader, clock=lambda: NOW)
        self.order = OrderRequest("abc", "test", "alpha", "b", SYMBOL, "buy", 100, 10., "2026-11-16")

    def test_dispatch_disabled_but_listener_and_query_work(self):
        events = []
        self.provider.start(events.append)
        self.provider.poll()
        with self.assertRaises(OrderDisabled):
            self.provider.submit(self.order)
        self.assertTrue(all(c[0] != "submit" for c in self.trader.calls))
        self.assertTrue(all(c[1]["strategy_name"] == "" for c in self.trader.calls))
        self.provider.close()

    def test_actual_string_broker_id_and_cancel_zero_contract(self):
        self.provider.enable_orders = True
        self.assertEqual(self.provider.submit(self.order), "0000123")
        self.provider.cancel(self.order, "0000123")
        args = self.trader.calls[-1][1]
        self.assertEqual(args[-1], "0000123")

    def test_normalize_push_fields_and_bad_trade_identity(self):
        raw = SimpleNamespace(account_id="test", stock_code=SYMBOL, order_type=23, order_sysid="0000123",
                              order_remark="abc", trade_id="fill1", traded_time=NOW.timestamp(),
                              traded_volume=100, traded_price=10.)
        event = self.provider.normalize("trade", raw)
        self.assertEqual((event.client_id, event.trade_id, event.broker_id), ("abc", "fill1", "0000123"))
        self.assertEqual(event.timestamp, NOW)
        raw.account_id = "other"
        with self.assertRaises(ValueError):
            self.provider.normalize("trade", raw)

    def test_server_order_disabled_is_definite_refusal(self):
        self.provider.enable_orders = True
        def disabled(*args):
            raise RuntimeError("ORDER_DISABLED")
        self.trader.order_stock_result = disabled
        with self.assertRaises(OrderDisabled):
            self.provider.submit(self.order)

    def test_account_mismatch_and_none_cash_fail(self):
        with self.assertRaises(ValueError):
            QmtTradingProvider("other", trader=self.trader)
        self.trader.asset.cash = None
        with self.assertRaises((TypeError, ValueError)):
            self.provider.snapshot()


class DataHubExecutionTest(unittest.TestCase):
    def test_instrument_extension_preserves_limits_with_separate_cache_key(self):
        class SDK:
            def get_instrument_detail(self, code):
                return {"InstrumentName": "test", "UpStopPrice": 11., "DownStopPrice": 9., "PriceTick": .01}
        service = MarketDataService(DataRouter({"xtquant": XtQuantProvider(SDK())}))
        data = service.query(DataKind.INSTRUMENT, DataRequest(symbols=(SYMBOL,)))
        self.assertEqual(data.iloc[0].UpStopPrice, 11.)
        self.assertEqual(data.attrs["source"], "xtquant")
        self.assertTrue(data.attrs["data_version"])
        self.assertEqual(data.attrs["data_kind"], "instrument")

    def test_replay_with_fake_cached_daily_data_uses_same_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "prices/raw/daily").mkdir(parents=True)
            pd.DataFrame([{"ts_code": SYMBOL, "trade_date": "20261116", "open": 10., "close": 10.,
                           "pre_close": 10., "vol": 1000}]).to_parquet(root / "prices/raw/daily/20261116.parquet")
            pd.DataFrame([{"signal_date": "2026-11-13", "trade_date": "2026-11-16",
                           "symbol": SYMBOL, "target_weight": 1.}]).to_csv(root / "targets.csv", index=False)
            metrics = run_replay(root / "targets.csv", root / "prices", root / "out", initial_cash=10000.)
            self.assertEqual(metrics["fills"], 1)
            self.assertEqual(metrics["unresolved_orders"], 0)
            self.assertAlmostEqual(metrics["final_equity"], 9995.)
            with self.assertRaisesRegex(ValueError, "already"):
                run_replay(root / "targets.csv", root / "prices", root / "out")


if __name__ == "__main__":
    unittest.main()
