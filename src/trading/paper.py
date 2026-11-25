"""Deterministic limit-order broker used by historical and local paper runs."""
from __future__ import annotations

from collections import deque

from .models import BrokerEvent, OrderRequest, Quote


class PaperBroker:
    requires_fresh_quotes = False

    def __init__(self, account_id: str, *, max_fill: int | None = None):
        self.account_id = account_id
        self.max_fill = max_fill
        self.quotes: dict[str, Quote] = {}
        self.requests: dict[str, OrderRequest] = {}
        self.filled: dict[str, int] = {}
        self.canceled: set[str] = set()
        self.events = deque()
        self.callback = None
        self.sequence = 0

    def start(self, callback):
        self.callback = callback

    def set_quotes(self, quotes: dict[str, Quote]):
        self.quotes = quotes

    def submit(self, order: OrderRequest) -> str:
        if order.account_id != self.account_id:
            raise ValueError("paper broker account mismatch")
        if order.client_id in self.requests:
            raise RuntimeError("duplicate paper submission")
        self.requests[order.client_id] = order
        self.filled[order.client_id] = 0
        return "paper:" + order.client_id

    def poll(self):
        result = list(self.events)
        self.events.clear()
        for client_id, order in self.requests.items():
            remaining = order.quantity - self.filled[client_id]
            if remaining <= 0 or client_id in self.canceled:
                continue
            quote = self.quotes.get(order.symbol)
            if not quote or not quote.tradable or quote.timestamp.date().isoformat() != order.trade_date:
                continue
            if order.side == "buy" and (quote.price > order.limit_price + 1e-8 or
                                        quote.upper_limit is not None and quote.price >= quote.upper_limit - 1e-8):
                continue
            if order.side == "sell" and (quote.price < order.limit_price - 1e-8 or
                                         quote.lower_limit is not None and quote.price <= quote.lower_limit + 1e-8):
                continue
            qty = min(remaining, self.max_fill or remaining)
            self.sequence += 1
            self.filled[client_id] += qty
            fill = BrokerEvent("trade", self.account_id, quote.timestamp, client_id,
                               "paper:" + client_id, order.symbol, order.side, quantity=qty,
                               price=quote.price, trade_id=f"{order.trade_date}:{self.sequence}:{client_id}")
            status = BrokerEvent("order", self.account_id, quote.timestamp, client_id,
                                 "paper:" + client_id, order.symbol, order.side,
                                 status="filled" if self.filled[client_id] == order.quantity else "partial",
                                 filled_quantity=self.filled[client_id])
            result.extend([fill, status])
            if self.callback:
                # Deliberately deliver both push and poll copies. Ledger dedupes.
                self.callback(fill)
                self.callback(status)
        return result

    def cancel(self, order: OrderRequest, broker_id: str):
        self.canceled.add(order.client_id)
        quote = self.quotes[order.symbol]
        self.events.append(BrokerEvent("order", self.account_id, quote.timestamp,
                                      order.client_id, broker_id, order.symbol, order.side,
                                      status="canceled", filled_quantity=self.filled.get(order.client_id, 0)))

    def snapshot(self):
        return {"account_id": self.account_id, "simulation": True}

    def close(self):
        self.callback = None
