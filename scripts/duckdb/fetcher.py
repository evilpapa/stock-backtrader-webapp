"""Batch QMT daily-bar fetching and normalisation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterator

import pandas as pd

from src.utils.bigqmt_client import QmtDataClient
from .universe import Instrument


@dataclass
class BatchResult:
    bars: pd.DataFrame
    errors: list[dict[str, str]]


def chunks(items: list[Instrument], size: int) -> Iterator[list[Instrument]]:
    for offset in range(0, len(items), size):
        yield items[offset:offset + size]


def fetch_batches(
    qmt: QmtDataClient,
    instruments: pd.DataFrame,
    start_date: date | str,
    end_date: date | str,
    *,
    batch_size: int,
    period: str = "1d",
    dividend_type: str,
    download_missing: bool = False,
) -> Iterator[BatchResult]:
    records = [Instrument(**row) for row in instruments.to_dict(orient="records")]
    for batch in chunks(records, batch_size):
        symbols = [item.symbol for item in batch]
        metadata = {item.symbol: item for item in batch}
        try:
            payloads = qmt.market_bars(
                symbols,
                start_date,
                end_date,
                period=period,
                dividend_type=dividend_type,
                download_missing=download_missing,
            )
        except Exception as exc:
            yield BatchResult(
                pd.DataFrame(),
                [{"symbol": symbol, "error_type": "batch_request", "error": str(exc)} for symbol in symbols],
            )
            continue

        frames: list[pd.DataFrame] = []
        errors: list[dict[str, str]] = []
        ingested_at = pd.Timestamp.utcnow().tz_localize(None)
        for symbol in symbols:
            frame = payloads.get(symbol, pd.DataFrame())
            if frame.empty:
                errors.append({"symbol": symbol, "error_type": "empty_data", "error": "QMT 未返回行情数据"})
                continue
            item = metadata[symbol]
            frame = frame.copy()
            frame["bar_time"] = pd.to_datetime(frame.pop("bar_time"), errors="coerce")
            frame["symbol"] = item.symbol
            frame["market"] = item.market
            frame["asset_type"] = item.asset_type
            frame["period"] = period
            frame["dividend_type"] = dividend_type
            frame["source"] = "bigqmt"
            frame["ingested_at"] = ingested_at
            frame = frame.dropna(subset=["bar_time"])
            frames.append(frame[
                [
                    "symbol", "market", "asset_type", "period", "bar_time", "open", "high", "low",
                    "close", "last", "volume", "amount", "bid", "ask", "bid_volume", "ask_volume",
                    "dividend_type", "source", "ingested_at",
                ]
            ])
        yield BatchResult(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), errors)
