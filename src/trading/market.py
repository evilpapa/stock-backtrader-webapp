"""Execution quotes through MarketDataService, with traceable raw-price inputs."""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.datahub import DataRequest
from src.datahub.models import DataKind
from src.datahub.ticker import TickerMapper
from .models import Quote, positive

SHANGHAI = ZoneInfo("Asia/Shanghai")


def stock_lot(symbol):
    """Cash A-share defaults; STAR buys start at 200, increment 1."""
    code = TickerMapper.normalize(symbol)
    if code.startswith("688"):
        return 200, 1
    if TickerMapper.to_exchange(code) == "BJ":
        return 100, 1
    return 100, 100


def live_quotes(service, symbols, now: datetime) -> dict[str, Quote]:
    symbols = tuple(sorted({TickerMapper.normalize(s) for s in symbols}))
    if not symbols:
        return {}
    day = now.astimezone(SHANGHAI).date().isoformat()
    calendar = service.get_trade_calendar(DataRequest(start=day, end=day, exchange="SH"), use_cache=False)
    dates = pd.to_datetime(calendar.trade_date).dt.date.astype(str)
    if not (dates.eq(day) & calendar.is_open.eq(1)).any():
        raise ValueError("QMT calendar does not confirm an open trading day")
    request = DataRequest(symbols=symbols, frequency="tick", adjust="none")
    ticks = service.get_realtime(request, use_cache=False)
    details = service.query(DataKind.INSTRUMENT, request, use_cache=False)
    if ticks.attrs.get("source") != "xtquant" or details.attrs.get("source") != "xtquant":
        raise ValueError("execution requires XtQuant metadata and quotes")
    if ticks.symbol.duplicated().any() or details.symbol.duplicated().any():
        raise ValueError("ambiguous execution quote/metadata")
    metadata = details.set_index("symbol")
    result = {}
    for row in ticks.itertuples(index=False):
        if row.symbol not in metadata.index:
            raise ValueError(f"missing instrument: {row.symbol}")
        detail = metadata.loc[row.symbol]
        upper = positive(detail.get("UpStopPrice", 0), "upper exchange limit")
        lower = positive(detail.get("DownStopPrice", 0), "lower exchange limit")
        tick = positive(detail.get("PriceTick", .01), "price tick")
        price = positive(row.close, "latest price")
        if not lower <= price <= upper:
            raise ValueError("latest quote outside exchange price limits")
        lot, step = stock_lot(row.symbol)
        stamp = pd.Timestamp(row.datetime)
        if stamp.tzinfo is None:
            raise ValueError("execution quote timezone missing")
        state = ticks.attrs.get("execution_state", {}).get(row.symbol, {})
        status = state.get("security_status")
        if status is not None and not pd.isna(status):
            # Prefer the current tick's exchange phase to static contract
            # IsTrading, which Big QMT reports False even for active ETFs.
            tradable = int(status) == 13
        else:
            tradable = detail.get("IsTrading", True)
            if pd.isna(tradable):
                tradable = False
        result[row.symbol] = Quote(row.symbol, price, stamp.to_pydatetime(), "xtquant", lot, step,
                                   tick, upper, lower, bool(tradable))
    if set(result) != set(symbols):
        raise ValueError("incomplete execution quotes")
    return result
