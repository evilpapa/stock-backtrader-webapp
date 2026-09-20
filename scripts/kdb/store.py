"""KDB-X target for minute and tick market data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


KDB_COLUMNS = [
    "symbol", "market", "asset_type", "period", "bar_time", "open", "high", "low", "close",
    "last", "volume", "amount", "bid", "ask", "bid_volume", "ask_volume", "dividend_type",
    "source", "ingested_at",
]


class KdbStore:
    """Write shared synchronisation frames into a keyed KDB-X table."""

    name = "kdb"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        *,
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
    ) -> None:
        try:
            import pykx as kx
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("KDB-X 目标需要 pykx，请先执行 uv sync") from exc
        self._kx = kx
        self.host = host
        self.port = port
        self.connection = kx.QConnection(
            host=host,
            port=port,
            username=username,
            password=password,
            timeout=timeout,
        )

    def initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.q")
        self.connection(schema_path.read_text(encoding="utf-8"))

    def close(self) -> None:
        close = getattr(self.connection, "close", None)
        if close is not None:
            close()

    def upsert_instruments(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        now = pd.Timestamp.utcnow().tz_localize(None)
        values = frame.copy()
        values["first_seen_at"] = now
        values["last_seen_at"] = now
        values = values[["symbol", "market", "asset_type", "source_sectors", "first_seen_at", "last_seen_at"]]
        self.connection(
            "{.q.set[`instrument_master; instrument_master upsert x]; 0b}",
            self._to_q_table(values),
        )

    def latest_bar_time(self, period: str = "1d") -> Any | None:
        result = self.connection("{max select bar_time from market_bars where period = x}", period)
        try:
            value = result.py()
        except AttributeError:
            value = result
        if isinstance(value, dict):
            value = next(iter(value.values()), None)
        if isinstance(value, pd.DataFrame):
            value = value.iloc[0, 0] if not value.empty else None
        elif isinstance(value, pd.Series):
            value = value.iloc[0] if not value.empty else None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if pd.isna(value):
            return None
        return value

    def write_bars(self, frame: pd.DataFrame, *, period: str = "1d") -> int:
        if frame.empty:
            return 0
        values = frame.copy()
        if "bar_time" not in values.columns:
            if "trade_date" not in values.columns:
                raise ValueError("KDB-X 行情数据缺少 bar_time")
            values["bar_time"] = values.pop("trade_date")
        values["period"] = period
        values["bar_time"] = pd.to_datetime(values["bar_time"], errors="coerce")
        values = values.dropna(subset=["bar_time"])
        for column in KDB_COLUMNS:
            if column not in values.columns:
                values[column] = float("nan") if column not in {"symbol", "market", "asset_type", "period", "dividend_type", "source"} else ""
        values = values[KDB_COLUMNS]
        self.connection(
            "{.q.set[`market_bars; market_bars upsert x]; 0b}",
            self._to_q_table(values),
        )
        return len(values)

    def _to_q_table(self, frame: pd.DataFrame) -> Any:
        values = frame.copy()
        for column in ["bar_time", "first_seen_at", "last_seen_at", "ingested_at"]:
            if column in values.columns:
                values[column] = pd.to_datetime(values[column], errors="coerce").dt.tz_localize(None)
        return self._kx.toq(values)
