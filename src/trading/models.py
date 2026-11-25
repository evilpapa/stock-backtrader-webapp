"""Broker-independent contracts shared by strategies, simulation and execution."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Protocol

from src.datahub.ticker import TickerMapper


TERMINAL = frozenset({"filled", "canceled", "rejected"})


def positive(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    timestamp: datetime
    source: str
    buy_min: int = 100
    buy_step: int = 100
    price_tick: float = .01
    upper_limit: float | None = None
    lower_limit: float | None = None
    tradable: bool = True

    def __post_init__(self):
        object.__setattr__(self, "symbol", TickerMapper.normalize(self.symbol))
        positive(self.price, "price")
        positive(self.price_tick, "price_tick")
        if self.timestamp.tzinfo is None or self.buy_min <= 0 or self.buy_step <= 0:
            raise ValueError("quote needs an aware timestamp and positive lot rules")

    def buy_quantity(self, quantity: float) -> int:
        if quantity < self.buy_min:
            return 0
        return self.buy_min + int((quantity - self.buy_min + 1e-9) // self.buy_step) * self.buy_step


@dataclass(frozen=True)
class OrderRequest:
    client_id: str
    account_id: str
    strategy_id: str
    batch_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: float
    trade_date: str


@dataclass(frozen=True)
class BrokerEvent:
    kind: str
    account_id: str
    timestamp: datetime
    client_id: str = ""
    broker_id: str = ""
    symbol: str = ""
    side: str = ""
    status: str = ""
    quantity: int = 0
    price: float = 0.
    trade_id: str = ""
    filled_quantity: int = 0
    detail: str = ""


class OrderDisabled(RuntimeError):
    """A definite refusal before dispatch, not an ambiguous network failure."""


class Broker(Protocol):
    account_id: str
    requires_fresh_quotes: bool

    def start(self, callback: Callable[[BrokerEvent], None]) -> None: ...
    def submit(self, order: OrderRequest) -> str: ...
    def cancel(self, order: OrderRequest, broker_id: str) -> None: ...
    def poll(self) -> list[BrokerEvent]: ...
    def snapshot(self) -> dict: ...
    def close(self) -> None: ...


def iso_day(value: str | date) -> str:
    return date.fromisoformat(str(value)).isoformat()
