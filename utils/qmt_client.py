"""HTTP client for the QMT.py proxy market-data API."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib import request
from urllib.error import HTTPError, URLError

import pandas as pd

from .xtdata_client import (
    DEFAULT_OHLCV_FIELDS,
    _normalize_time_values,
    format_xt_date,
    normalize_dividend_type,
    normalize_xt_symbol,
)


UrlOpen = Callable[[request.Request, float], Any]


class QmtProxyError(RuntimeError):
    """Raised when the QMT HTTP proxy cannot return usable OHLCV data."""


def fetch_history_ohlcv(
    symbol: str,
    start_date: Any,
    end_date: Any,
    period: str = "1d",
    dividend_type: str = "front",
    fields: list[str] | None = None,
    base_url: str = "http://127.0.0.1:10086",
    token: str = "123456789",
    timeout: float = 10.0,
    urlopen_func: UrlOpen | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV data through the QMT.py HTTP proxy."""
    xt_symbol = normalize_xt_symbol(symbol)
    start_time = format_xt_date(start_date)
    end_time = format_xt_date(end_date)
    field_list = fields or DEFAULT_OHLCV_FIELDS
    payload = {
        "fields": ",".join(field_list),
        "stock_code": xt_symbol,
        "start_time": start_time,
        "end_time": end_time,
        "period": period,
        "dividend_type": normalize_dividend_type(dividend_type),
        "count": "-1",
    }
    response = _post_json(
        f"{base_url.rstrip('/')}/api/data/market_data",
        payload,
        token=token,
        timeout=timeout,
        urlopen_func=urlopen_func,
    )
    if "error" in response:
        raise QmtProxyError(str(response["error"]))
    return market_data_payload_to_ohlcv(response.get("data"), xt_symbol, field_list)


def _post_json(
    url: str,
    payload: dict[str, Any],
    token: str,
    timeout: float,
    urlopen_func: UrlOpen | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Token"] = token
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    opener = urlopen_func or request.urlopen
    try:
        with opener(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise QmtProxyError(f"QMT proxy HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise QmtProxyError(f"QMT proxy connection failed: {exc.reason}") from exc
    except OSError as exc:
        raise QmtProxyError(f"QMT proxy request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise QmtProxyError("QMT proxy returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise QmtProxyError("QMT proxy response is not a JSON object")
    return parsed


def market_data_payload_to_ohlcv(data: Any, symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    """Normalize common QMT DataFrame.to_dict payloads into date/open/high/low/close/volume."""
    field_list = fields or DEFAULT_OHLCV_FIELDS
    if data is None:
        raise QmtProxyError("QMT proxy response missing data")

    if isinstance(data, dict):
        if {"index", "columns", "data"}.issubset(data):
            frame = pd.DataFrame(data["data"], index=data["index"], columns=data["columns"])
            return _frame_to_ohlcv(frame, field_list)
        if all(field in data for field in field_list):
            series_by_field = {
                field: _field_payload_to_series(data[field], symbol)
                for field in field_list
            }
            frame = pd.DataFrame(series_by_field)
            frame.index.name = "date"
            return _frame_to_ohlcv(frame.reset_index(), field_list)
        if symbol in data:
            return market_data_payload_to_ohlcv(data[symbol], symbol, field_list)
        if _looks_like_index_orient(data, field_list):
            return _frame_to_ohlcv(pd.DataFrame.from_dict(data, orient="index"), field_list)

    if isinstance(data, list):
        return _frame_to_ohlcv(pd.DataFrame(data), field_list)

    raise QmtProxyError("Unsupported QMT market data payload shape")


def _field_payload_to_series(value: Any, symbol: str) -> pd.Series:
    if isinstance(value, dict):
        if symbol in value and isinstance(value[symbol], dict):
            return pd.Series(value[symbol])
        normalized = {}
        for key, item in value.items():
            if isinstance(item, dict):
                if symbol in item:
                    normalized[key] = item[symbol]
                elif len(item) == 1:
                    normalized[key] = next(iter(item.values()))
            else:
                normalized[key] = item
        return pd.Series(normalized)
    if isinstance(value, list):
        return pd.Series(value)
    return pd.Series([value])


def _looks_like_index_orient(data: dict[str, Any], fields: list[str]) -> bool:
    if not data:
        return False
    first = next(iter(data.values()))
    return isinstance(first, dict) and any(field in first for field in fields)


def _frame_to_ohlcv(frame: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", *fields])

    frame = frame.copy()
    frame.columns = [str(column) for column in frame.columns]
    column_map = {column.lower(): column for column in frame.columns}
    date_column = next(
        (column_map[name] for name in ["date", "datetime", "time", "timetag", "index"] if name in column_map),
        None,
    )
    if date_column is not None:
        frame["date"] = _normalize_time_values(frame[date_column])
    else:
        frame["date"] = _normalize_time_values(pd.Series(frame.index, index=frame.index))

    missing = [field for field in fields if field not in column_map]
    if missing:
        raise QmtProxyError(f"QMT proxy response missing fields: {', '.join(missing)}")
    for field in fields:
        frame[field] = pd.to_numeric(frame[column_map[field]], errors="coerce")

    frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return frame[["date", *fields]]
