"""Shared target protocol for QMT market-data synchronisation."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class MarketDataTarget(Protocol):
    """Minimal interface implemented by DuckDB and KDB-X sinks."""

    name: str

    def initialize(self) -> None: ...

    def upsert_instruments(self, frame: pd.DataFrame) -> None: ...

    def write_bars(self, frame: pd.DataFrame, *, period: str = "1d") -> int: ...

    def latest_bar_time(self, period: str = "1d"): ...

    def close(self) -> None: ...


def parse_targets(value: str) -> list[str]:
    targets = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = sorted(set(targets).difference({"duckdb", "kdb"}))
    if unknown:
        raise ValueError(f"不支持的同步目标: {', '.join(unknown)}；可选 duckdb,kdb")
    if not targets:
        raise ValueError("至少指定一个同步目标：duckdb 或 kdb")
    return list(dict.fromkeys(targets))
