"""Target-weight rebalance engine, independent of signals and broker SDKs."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timedelta
from queue import Empty, SimpleQueue
from time import monotonic
from zoneinfo import ZoneInfo

from src.datahub.ticker import TickerMapper
from .models import Broker, BrokerEvent, OrderDisabled, OrderRequest, Quote, TERMINAL, iso_day, positive
from .portfolio import PortfolioLedger

SHANGHAI = ZoneInfo("Asia/Shanghai")


def order_request(row: dict) -> OrderRequest:
    return OrderRequest(row["client_id"], row["account"], row["strategy"], row["batch_id"],
                        row["symbol"], row["side"], row["quantity"], row["limit_price"], row["trade_date"])


class ExecutionEngine:
    def __init__(self, ledger: PortfolioLedger, broker: Broker, strategy_id: str):
        self.ledger, self.broker, self.strategy_id = ledger, broker, strategy_id
        self.account_id = broker.account_id
        self.queue = SimpleQueue()
        broker.start(self.queue.put)

    def sync(self):
        events = list(self.broker.poll())
        while True:
            try:
                events.append(self.queue.get_nowait())
            except Empty:
                break
        for event in events:
            self.ledger.record_event(event)
            if event.kind == "adapter_error":
                raise RuntimeError(f"broker event normalization/connection error: {event.detail}")
            row = self.ledger.resolve_event(event)
            if not row:
                continue  # Do not attribute manual or other strategies' trades.
            if event.kind == "trade":
                if event.broker_id:
                    self.ledger.update_status(row["client_id"], row["status"], event.broker_id)
                self.ledger.apply_fill(event, row["client_id"])
            elif event.kind == "order":
                self.ledger.update_status(row["client_id"], event.status, event.broker_id, event.filled_quantity, event.detail)
            elif event.kind == "order_error":
                self.ledger.update_status(row["client_id"],
                                          "rejected" if event.status == "rejected" and event.broker_id else "unknown",
                                          event.broker_id, detail=event.detail)
            elif event.kind == "cancel_error":
                self.ledger.update_status(row["client_id"], row["status"], detail=event.detail)
        return len(events)

    def _validate_live(self, quotes, signal_date, trade_date, now):
        if not self.broker.requires_fresh_quotes:
            return
        local = now.astimezone(SHANGHAI)
        if local.date().isoformat() != trade_date or signal_date is not None and not 0 < (local.date() - datetime.fromisoformat(signal_date).date()).days <= 7:
            raise ValueError("live execution requires today's date and a signal within 7 days")
        if local.weekday() >= 5 or not (time(9, 30) <= local.time().replace(tzinfo=None) <= time(11, 30) or
                                        time(13) <= local.time().replace(tzinfo=None) < time(14, 57)):
            raise ValueError("outside continuous trading session")
        for quote in quotes.values():
            age = (local - quote.timestamp.astimezone(SHANGHAI)).total_seconds()
            if not -2 <= age <= 30 or quote.source != "xtquant":
                raise ValueError(f"stale/unverified live quote: {quote.symbol}")
            if quote.upper_limit is None or quote.lower_limit is None:
                raise ValueError(f"missing exchange price limits: {quote.symbol}")
        reconciliation = self.ledger.reconciliation(self.account_id, self.broker.snapshot())
        if not reconciliation["ok"]:
            raise RuntimeError(f"account reconciliation blocked execution: {reconciliation}")

    def _dispatch(self, request):
        """Reserve once, commit locally, then dispatch once; never retry a write."""
        if not self.ledger.reserve(request):
            return
        try:
            broker_id = self.broker.submit(request)
            if not broker_id or str(broker_id) in {"-1", "0"}:
                raise RuntimeError("broker returned no confirmed order identity")
            self.ledger.update_status(request.client_id, "submitted", str(broker_id))
        except OrderDisabled as exc:
            self.ledger.update_status(request.client_id, "rejected", detail=str(exc))
        except Exception as exc:
            self.ledger.update_status(request.client_id, "unknown", detail=str(exc))

    def submit_order(self, *, client_id: str, symbol: str, side: str, quantity: int,
                     limit_price: float, quote: Quote, now: datetime):
        """Strategy-neutral explicit limit order with a caller's durable identity.

        Rebalance and explicit orders share reservation, dispatch, fills and cancel.
        A repeated identity is a read/recovery operation, never a second submit.
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone aware")
        if not client_id or len(client_id) > 24 or not client_id.isascii() or not client_id.isalnum():
            raise ValueError("client_id must be 1..24 ASCII letters/digits")
        symbol = TickerMapper.normalize(symbol)
        day = now.astimezone(SHANGHAI).date().isoformat()
        request = OrderRequest(client_id, self.account_id, self.strategy_id, "explicit",
                               symbol, side, quantity, positive(limit_price, "limit price"), day)
        self.sync()
        existing = self.ledger.order(client_id)
        if existing:
            self.ledger.validate_identity(request, existing)
            return self.order_status(client_id)
        if side not in {"buy", "sell"} or type(quantity) is not int or quantity <= 0:
            raise ValueError("invalid side/quantity")
        if quote.symbol != symbol or not quote.tradable:
            raise ValueError("instrument is not tradable or quote symbol differs")
        ticks = limit_price / quote.price_tick
        if not math.isclose(ticks, round(ticks), rel_tol=0, abs_tol=1e-7):
            raise ValueError("limit price violates exchange tick")
        if quote.lower_limit is not None and limit_price < quote.lower_limit - 1e-8 or quote.upper_limit is not None and limit_price > quote.upper_limit + 1e-8:
            raise ValueError("limit price outside exchange limits")
        if side == "buy" and quote.buy_quantity(quantity) != quantity:
            raise ValueError("buy quantity violates exchange lot")
        if self.ledger.unresolved(self.account_id, self.strategy_id):
            raise RuntimeError("strategy has unresolved orders; reconcile before another submission")
        self.ledger.advance_day(self.account_id, self.strategy_id, day)
        self._validate_live({symbol: quote}, None, day, now)
        if hasattr(self.broker, "set_quotes"):
            self.broker.set_quotes({symbol: quote})
        self._dispatch(request)
        return self.order_status(client_id)

    def order_status(self, client_id: str, *, refresh=False):
        if refresh:
            self.sync()
        row = self.ledger.order(client_id)
        if not row or row["account"] != self.account_id or row["strategy"] != self.strategy_id:
            raise ValueError("order is not owned by this strategy")
        settled = row["status"] in TERMINAL and not self.ledger.pending(row)
        outcome = ("filled" if settled and row["filled"] == row["quantity"] else
                   "partially_filled_canceled" if settled and row["status"] == "canceled" and row["filled"] else
                   row["status"] if settled else "awaiting_trades" if row["status"] in TERMINAL else
                   "unknown" if row["status"] in {"sending", "unknown"} else "pending")
        return {**row, "accepted": bool(row["broker_id"]) and row["status"] != "rejected",
                "settled": settled, "success": settled and row["filled"] == row["quantity"],
                "failed": settled and row["status"] == "rejected",
                "outcome": outcome, "cancellation": self.ledger.cancellation(client_id)}

    def rebalance(self, targets: dict[str, float], quotes: dict[str, Quote], *,
                  signal_date: str, trade_date: str, now: datetime):
        if now.tzinfo is None:
            raise ValueError("now must be timezone aware")
        started = monotonic()
        signal_date, trade_date = iso_day(signal_date), iso_day(trade_date)
        normalized = {TickerMapper.normalize(s): float(w) for s, w in targets.items()}
        if len(normalized) != len(targets) or any(not math.isfinite(w) or w < 0 for w in normalized.values()) or sum(normalized.values()) > 1 + 1e-8:
            raise ValueError("invalid/duplicate target weights")
        self.sync()
        self.ledger.advance_day(self.account_id, self.strategy_id, trade_date)
        positions = self.ledger.positions(self.account_id, self.strategy_id)
        required = set(normalized) | set(positions)
        if required - set(quotes):
            raise ValueError(f"missing quotes/marks: {sorted(required - set(quotes))}")
        for symbol in required:
            if quotes[symbol].symbol != symbol:
                raise ValueError("quote symbol mismatch")
        self._validate_live({s: quotes[s] for s in required}, signal_date, trade_date, now)
        if hasattr(self.broker, "set_quotes"):
            self.broker.set_quotes(quotes)
        # Recover the original fixed target share counts after a process restart.
        batch = self.ledger.get_batch(self.account_id, self.strategy_id, trade_date)
        if batch:
            payload = json.loads(batch["payload"])
            if payload["weights"] != normalized or batch["signal_date"] != signal_date:
                raise ValueError("rebalance input changed after durable plan creation")
            batch_id = batch["id"]
        else:
            if self.ledger.unresolved(self.account_id, self.strategy_id):
                raise RuntimeError("previous rebalance has unresolved orders")
            equity = self.ledger.wallet(self.account_id, self.strategy_id)["cash"] + sum(
                p["quantity"] * quotes[s].price for s, p in positions.items())
            desired = {s: quotes[s].buy_quantity(equity * normalized.get(s, 0.) / quotes[s].price) for s in required}
            payload = {"weights": normalized, "desired": desired, "planning_equity": equity,
                       "price_sources": {s: {"price": quotes[s].price, "source": quotes[s].source,
                                             "timestamp": quotes[s].timestamp.isoformat()} for s in required}}
            batch_id = self.ledger.create_batch(self.account_id, self.strategy_id, signal_date, trade_date, payload)
        if any(r["status"] in {"sending", "unknown"} for r in self.ledger.orders(self.account_id, self.strategy_id)):
            return {"batch_id": batch_id, "status": "unknown"}
        for side in ("sell", "buy"):
            if side == "buy":
                if any(r["side"] == "sell" and (r["status"] != "filled" or r["filled"] != r["quantity"])
                       for r in self.ledger.orders(self.account_id, self.strategy_id) if r["batch_id"] == batch_id):
                    return {"batch_id": batch_id, "status": "waiting_sells"}
            for symbol in sorted(payload["desired"]):
                quote = quotes[symbol]
                if not quote.tradable:
                    continue
                p = self.ledger.positions(self.account_id, self.strategy_id).get(symbol, {})
                current, desired = p.get("quantity", 0), payload["desired"][symbol]
                diff = desired - current
                if (side == "sell" and diff >= 0) or (side == "buy" and diff <= 0):
                    continue
                client_id = hashlib.sha256(f"{batch_id}:{side}:{symbol}".encode()).hexdigest()[:24]
                if self.ledger.order(client_id):
                    continue
                price = round(round(quote.price / quote.price_tick) * quote.price_tick, 8)
                if quote.upper_limit is not None and price >= quote.upper_limit - 1e-8 and side == "buy":
                    continue
                if quote.lower_limit is not None and price <= quote.lower_limit + 1e-8 and side == "sell":
                    continue
                if side == "sell":
                    available = self.ledger.available_shares(self.account_id, self.strategy_id, symbol)
                    quantity = min(-diff, available) if desired == 0 else quote.buy_quantity(min(-diff, available))
                else:
                    available = self.ledger.available_cash(self.account_id, self.strategy_id)
                    quantity = quote.buy_quantity(diff)
                    while quantity > 0 and quantity * price + self.ledger.fee(quantity * price) > available + 1e-7:
                        quantity = quote.buy_quantity(quantity - quote.buy_step)
                if quantity <= 0:
                    continue
                # A long sequence of broker acknowledgements can outlive the
                # quote TTL. Recheck at dispatch, including physical balances
                # after the preceding fills, rather than only at batch entry.
                if self.broker.requires_fresh_quotes:
                    self._validate_live({symbol: quote}, signal_date, trade_date,
                                        now + timedelta(seconds=monotonic() - started))
                request = OrderRequest(client_id, self.account_id, self.strategy_id, batch_id,
                                       symbol, side, quantity, price, trade_date)
                self._dispatch(request)
                dispatch_status = self.ledger.order(client_id)["status"]
                if dispatch_status == "rejected":
                    return {"batch_id": batch_id, "status": "rejected"}
                if dispatch_status in {"sending", "unknown"}:
                    return {"batch_id": batch_id, "status": "unknown"}
            self.sync()
        orders = [r for r in self.ledger.orders(self.account_id, self.strategy_id) if r["batch_id"] == batch_id]
        unresolved = [r for r in orders if r["status"] not in TERMINAL or self.ledger.pending(r)]
        failed = [r for r in orders if r["status"] in {"rejected", "canceled"}]
        owned = self.ledger.positions(self.account_id, self.strategy_id)
        deviations = {s: {"target": qty, "actual": owned.get(s, {}).get("quantity", 0)}
                      for s, qty in payload["desired"].items() if qty != owned.get(s, {}).get("quantity", 0)}
        status = ("pending" if unresolved else "incomplete" if failed
                  else "completed_with_deviation" if deviations else "completed")
        return {"batch_id": batch_id, "status": status, "quantity_deviations": deviations}

    def cancel(self, client_id: str):
        self.sync()
        row = self.ledger.order(client_id)
        if not row or row["account"] != self.account_id or row["strategy"] != self.strategy_id:
            raise ValueError("order is not owned by this strategy")
        if not self.ledger.claim_cancel(client_id, self.account_id, self.strategy_id):
            return self.order_status(client_id)
        try:
            self.broker.cancel(order_request(row), row["broker_id"])
        except Exception as exc:
            self.ledger.cancel_result(client_id, "unknown", str(exc))
            self.ledger.update_status(client_id, "cancel_pending", detail=f"cancel outcome unknown: {exc}")
            raise
        # A cancel acknowledgement is not a canceled order: wait for push/poll.
        self.ledger.cancel_result(client_id, "acknowledged")
        self.sync()
        return self.order_status(client_id)

    def snapshot(self, quotes: dict[str, Quote]):
        positions = self.ledger.positions(self.account_id, self.strategy_id)
        if set(positions) - set(quotes):
            raise ValueError("missing position valuation")
        cash = self.ledger.wallet(self.account_id, self.strategy_id)["cash"]
        equity = cash + sum(p["quantity"] * quotes[s].price for s, p in positions.items())
        return {"cash": cash, "available_cash": self.ledger.available_cash(self.account_id, self.strategy_id),
                "equity": equity, "positions": [
                    {**p, "price": quotes[s].price, "market_value": p["quantity"] * quotes[s].price,
                     "weight": p["quantity"] * quotes[s].price / equity if equity else 0.,
                     "available": self.ledger.available_shares(self.account_id, self.strategy_id, s)}
                    for s, p in sorted(positions.items())]}

    def close(self):
        self.broker.close()
