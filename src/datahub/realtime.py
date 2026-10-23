"""RealtimeDataService：Observer 事件分发和共享底层订阅。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .exceptions import SubscriptionError
from .models import DataKind, RealtimeEvent
from .provider import Callback, RealtimeProvider
from .ticker import TickerMapper


@dataclass
class _LogicalSubscription:
    kind: DataKind
    symbols: tuple[str, ...]
    callback: Callback


class RealtimeDataService:
    """多个策略共享 per-symbol 底层订阅，并向 Observer 广播统一事件。"""

    def __init__(self, provider: RealtimeProvider, ticker_mapper: TickerMapper | None = None) -> None:
        self.provider = provider
        self.ticker_mapper = ticker_mapper or TickerMapper()
        self._logical: dict[str, _LogicalSubscription] = {}
        self._underlying: dict[tuple[DataKind, str], tuple[str, int]] = {}
        self._closed = False

    def subscribe_quote(self, symbols: list[str] | tuple[str, ...], callback: Callback) -> str:
        return self._subscribe(DataKind.REALTIME, symbols, callback)

    def subscribe_tick(self, symbols: list[str] | tuple[str, ...], callback: Callback) -> str:
        return self._subscribe(DataKind.TICK, symbols, callback)

    def _subscribe(self, kind: DataKind, symbols: list[str] | tuple[str, ...], callback: Callback) -> str:
        if self._closed:
            raise SubscriptionError("RealtimeDataService 已关闭")
        if not callable(callback):
            raise SubscriptionError("callback 必须可调用")
        normalized = tuple(dict.fromkeys(self.ticker_mapper.normalize(item) for item in symbols))
        if not normalized:
            raise SubscriptionError("订阅列表不能为空")
        logical_id = uuid.uuid4().hex
        self._logical[logical_id] = _LogicalSubscription(kind, normalized, callback)
        for symbol in normalized:
            key = (kind, symbol)
            if key in self._underlying:
                self._underlying[key] = (self._underlying[key][0], self._underlying[key][1] + 1)
                continue
            subscribe = self.provider.subscribe_quote if kind == DataKind.REALTIME else self.provider.subscribe_tick
            provider_id = subscribe([symbol], self._on_provider_event)
            self._underlying[key] = (provider_id, 1)
        return logical_id

    def unsubscribe(self, subscription_id: str) -> None:
        subscription = self._logical.pop(subscription_id, None)
        if subscription is None:
            return
        for symbol in subscription.symbols:
            key = (subscription.kind, symbol)
            provider_id, count = self._underlying[key]
            if count > 1:
                self._underlying[key] = (provider_id, count - 1)
                continue
            cancel = self.provider.unsubscribe_quote if subscription.kind == DataKind.REALTIME else self.provider.unsubscribe_tick
            cancel(provider_id)
            self._underlying.pop(key, None)

    def _on_provider_event(self, payload: Any) -> None:
        for event in self._events(payload):
            for logical_id, subscription in tuple(self._logical.items()):
                if event.symbol in subscription.symbols and event.data_kind in {subscription.kind, DataKind.REALTIME, DataKind.TICK}:
                    subscription.callback(RealtimeEvent(event.symbol, event.data_kind, event.datetime, event.payload, event.source, logical_id))

    def _events(self, payload: Any) -> list[RealtimeEvent]:
        values = payload.items() if isinstance(payload, dict) else [(None, payload)]
        events = []
        for symbol, value in values:
            if symbol is None:
                continue
            normalized = self.ticker_mapper.normalize(symbol)
            item = dict(value) if isinstance(value, dict) else {"value": value}
            timestamp = item.get("time") or item.get("datetime") or pd.Timestamp.now(tz="Asia/Shanghai")
            parsed = pd.to_datetime(timestamp, unit="ms", utc=True, errors="coerce") if isinstance(timestamp, (int, float)) else pd.to_datetime(timestamp, errors="coerce")
            if pd.isna(parsed):
                parsed = pd.Timestamp.now(tz="Asia/Shanghai")
            if parsed.tzinfo is None:
                parsed = parsed.tz_localize("Asia/Shanghai")
            else:
                parsed = parsed.tz_convert("Asia/Shanghai")
            kind = DataKind.TICK if "lastPrice" in item or "bidPrice" in item else DataKind.REALTIME
            events.append(RealtimeEvent(normalized, kind, parsed, item, "xtquant"))
        return events

    def reconnect(self) -> None:
        """连接断开后的安全重建：只重建当前仍被引用的底层订阅。"""

        active = [(key, count) for key, (_, count) in self._underlying.items()]
        for key, _ in active:
            provider_id, _ = self._underlying.pop(key)
            try:
                (self.provider.unsubscribe_quote if key[0] == DataKind.REALTIME else self.provider.unsubscribe_tick)(provider_id)
            except Exception:
                pass
        for key, count in active:
            kind, symbol = key
            subscribe = self.provider.subscribe_quote if kind == DataKind.REALTIME else self.provider.subscribe_tick
            self._underlying[key] = (subscribe([symbol], self._on_provider_event), count)

    def close(self) -> None:
        for subscription_id in tuple(self._logical):
            self.unsubscribe(subscription_id)
        self.provider.close()
        self._closed = True

