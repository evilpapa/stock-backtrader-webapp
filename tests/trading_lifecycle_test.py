"""Offline safety tests for shared explicit orders and the one-shot example."""
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import pandas as pd

from src.datahub.models import DataRequest
from src.datahub.normalizer import Normalizer
from src.datahub.providers.xtquant import XtQuantProvider
from src.trading.market import live_quotes
from tests import trading_execution_test as fixtures

NOW, SYMBOL = fixtures.NOW, fixtures.SYMBOL


class LifecycleTest(unittest.TestCase):
    setUp = fixtures.ExecutionTest.setUp
    tearDown = fixtures.ExecutionTest.tearDown
    reserve = fixtures.ExecutionTest.reserve

    def submit(self, **kwargs):
        args = dict(client_id="explicit1", symbol=SYMBOL, side="buy", quantity=100,
                    limit_price=10., quote=self.quote, now=NOW)
        args.update(kwargs)
        return self.engine.submit_order(**args)

    def test_explicit_fill_and_repeated_identity(self):
        result = self.submit()
        self.assertTrue(result["accepted"])
        self.assertFalse(result["success"])
        result = self.engine.order_status("explicit1", refresh=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["filled"], 100)
        self.submit()
        self.assertEqual(len(self.broker.requests), 1)
        with self.assertRaisesRegex(ValueError, "different order parameters"):
            self.submit(quantity=200)

    def test_unknown_submit_is_not_repeated_after_reopen(self):
        self.broker.submit = Mock(side_effect=TimeoutError("lost response"))
        result = self.submit()
        self.assertEqual(result["outcome"], "unknown")
        self.assertLess(self.ledger.available_cash("test", "alpha"), 100000.)
        self.submit()
        self.assertEqual(self.broker.submit.call_count, 1)

    def test_passive_order_cancels_without_fill(self):
        self.submit(limit_price=9.)
        result = self.engine.cancel("explicit1")
        self.assertEqual(result["outcome"], "canceled")
        self.assertTrue(result["settled"])
        self.assertFalse(result["success"])
        self.assertEqual(self.ledger.available_cash("test", "alpha"), 100000.)

    def test_cancel_timeout_survives_reopen_and_never_resends(self):
        self.submit(limit_price=9.)
        self.broker.cancel = Mock(side_effect=TimeoutError("lost cancel ack"))
        with self.assertRaises(TimeoutError):
            self.engine.cancel("explicit1")
        other = type(self.ledger)(self.path)
        try:
            self.assertFalse(other.claim_cancel("explicit1", "test", "alpha"))
        finally:
            other.close()
        result = self.engine.cancel("explicit1")
        self.assertEqual(result["cancellation"]["state"], "unknown")
        self.assertFalse(result["settled"])
        self.assertEqual(self.broker.cancel.call_count, 1)
        self.assertLess(self.ledger.available_cash("test", "alpha"), 100000.)

    def test_delayed_ack_does_not_undo_partial_or_cancel(self):
        self.submit(limit_price=9.)
        self.ledger.update_status("explicit1", "partial", reported=20)
        self.ledger.update_status("explicit1", "submitted")
        self.assertEqual(self.ledger.order("explicit1")["status"], "partial")
        self.ledger.claim_cancel("explicit1", "test", "alpha")
        self.ledger.update_status("explicit1", "submitted")
        self.assertEqual(self.ledger.order("explicit1")["status"], "cancel_pending")

    def test_status_waits_for_missing_fill_rows(self):
        self.submit(limit_price=10.)
        self.ledger.update_status("explicit1", "filled", reported=100)
        result = self.engine.order_status("explicit1")
        self.assertEqual(result["outcome"], "awaiting_trades")
        self.assertFalse(result["success"])

    def test_preflight_failures_do_not_dispatch(self):
        for kwargs in ({"side": "bad"}, {"quantity": 101}, {"limit_price": 10.005},
                       {"quote": replace(self.quote, tradable=False)},
                       {"quote": replace(self.quote, upper_limit=9.)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.submit(**kwargs)
        self.assertFalse(self.broker.requests)

    def test_durable_reserve_payload_conflict(self):
        request = self.reserve(quantity=100)
        with self.assertRaisesRegex(ValueError, "different order parameters"):
            self.ledger.reserve(replace(request, side="sell"))

    def test_definite_refusal_callback_is_failed_not_unknown(self):
        from src.trading.models import BrokerEvent
        self.submit(limit_price=9.)
        self.engine.queue.put(BrokerEvent("order_error", "test", NOW, "explicit1", "paper:explicit1",
                                          status="rejected", detail="counter refused"))
        state = self.engine.order_status("explicit1", refresh=True)
        self.assertTrue(state["failed"])
        self.assertEqual(state["outcome"], "rejected")
        self.assertEqual(self.ledger.available_cash("test", "alpha"), 100000.)

    def test_bridge_lookup_timeout_is_unknown_even_with_status_57(self):
        from types import SimpleNamespace
        from src.datahub.providers.qmt_trading import QmtTradingProvider
        self.submit(limit_price=9.)
        provider = QmtTradingProvider(trader=fixtures.FakeTrader(), clock=lambda: NOW)
        event = provider.normalize("order_error", SimpleNamespace(
            account_id="test", order_remark="explicit1", stock_code=SYMBOL, status=57,
            error_msg="passorder submitted but order not found in system"))
        self.engine.queue.put(event)
        state = self.engine.order_status("explicit1", refresh=True)
        self.assertEqual(state["outcome"], "unknown")
        self.assertFalse(state["failed"])
        self.assertFalse(state["settled"])
        self.assertLess(self.ledger.available_cash("test", "alpha"), 100000.)

    def test_example_executes_one_order_and_recovery_never_resubmits(self):
        from examples import qmt_order_lifecycle as example
        self.engine.close()
        self.broker.health = lambda: {"account_type": "STOCK", "allow_order_methods": True}
        self.broker.snapshot = lambda: {"account_id": "test", "cash": 100000.,
                                        "frozen_cash": 0., "positions": [], "orders": []}
        original_submit = self.broker.submit
        original_cancel = self.broker.cancel
        self.broker.submit = Mock(wraps=original_submit)
        self.broker.cancel = Mock(wraps=original_cancel)
        def quotes(service, symbols, now):
            return {"510300.SH": replace(self.quote, symbol="510300.SH", timestamp=now,
                                         lower_limit=9., upper_limit=11.)}
        with patch.object(example, "QmtTradingProvider", return_value=self.broker), \
             patch.object(example, "create_service", return_value=Mock()), \
             patch.object(example, "live_quotes", side_effect=quotes), patch("builtins.print"):
            argv = ["--execute", "--enable-orders", "--ledger", str(self.path.parent / "demo.sqlite"),
                    "--output-dir", str(self.path.parent / "report")]
            first = example.main(argv)
            second = example.main(argv)
        self.assertTrue(first["workflow_completed"])
        self.assertEqual(first["final_order"]["outcome"], "canceled")
        self.assertEqual(second["client_id"], first["client_id"])
        self.assertEqual(self.broker.submit.call_count, 1)
        self.assertEqual(self.broker.cancel.call_count, 1)


class ExecutionStateTest(unittest.TestCase):
    def test_cli_exit_codes_distinguish_unknown_rejected_and_completed(self):
        from examples.qmt_order_lifecycle import exit_code
        self.assertEqual(exit_code({"mode": "preflight"}), 0)
        self.assertEqual(exit_code({"mode": "execute", "final_order": {"settled": False}}), 3)
        self.assertEqual(exit_code({"mode": "execute", "final_order": {"failed": True}}), 2)
        self.assertEqual(exit_code({"mode": "execute", "final_order": {"settled": True},
                                    "reconciliation": {"ok": True}}), 0)
        self.assertEqual(exit_code({"mode": "execute", "final_order": {"settled": True},
                                    "reconciliation": {"ok": False}}), 4)

    def test_bigqmt_tick_phase_survives_normalization_and_overrides_static_flag(self):
        class SDK:
            def get_full_tick(self, symbols):
                return {s: {"time": int(NOW.timestamp() * 1000), "lastPrice": 10.,
                            "open": 10., "high": 10., "low": 10., "volume": 1,
                            "amount": 100., "openInt": 13, "stockStatus": 3} for s in symbols}

        request = DataRequest(symbols=(SYMBOL,), frequency="tick", adjust="none")
        provider = XtQuantProvider(SDK())
        ticks = Normalizer().normalize(provider.get_realtime(request), request).data
        self.assertEqual(ticks.attrs["execution_state"][SYMBOL]["security_status"], 13)
        calendar = pd.DataFrame({"trade_date": ["2026-11-16"], "is_open": [1]})
        details = pd.DataFrame([{"symbol": SYMBOL, "UpStopPrice": 11., "DownStopPrice": 9.,
                                 "PriceTick": .01, "IsTrading": False}])
        details.attrs["source"] = "xtquant"
        service = Mock()
        service.get_trade_calendar.return_value = calendar
        service.get_realtime.return_value = ticks
        service.query.return_value = details
        self.assertTrue(live_quotes(service, [SYMBOL], NOW)[SYMBOL].tradable)
        ticks.attrs["execution_state"][SYMBOL]["security_status"] = 17
        self.assertFalse(live_quotes(service, [SYMBOL], NOW)[SYMBOL].tradable)


if __name__ == "__main__":
    unittest.main()
