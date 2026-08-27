"""HTTP client for the QMT Python API market-data bridge."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib import request
from urllib.error import HTTPError, URLError

import pandas as pd

DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]


UrlOpen = Callable[[request.Request, float], Any]


class QmtApiError(RuntimeError):
    """Raised when the QMT API bridge cannot return usable OHLCV data."""


def normalize_qmt_symbol(symbol: str) -> str:
    """Convert common ticker formats to the QMT ``code.market`` format."""
    symbol = symbol.strip().upper()
    if symbol.endswith(".SS"):
        return symbol[:-3] + ".SH"
    if symbol.endswith((".SH", ".SZ", ".BJ")):
        return symbol
    if len(symbol) == 6 and symbol.startswith(("5", "6", "9")):
        return symbol + ".SH"
    if len(symbol) == 6 and symbol.startswith(("0", "1", "2", "3")):
        return symbol + ".SZ"
    if len(symbol) == 6 and symbol.startswith(("4", "8")):
        return symbol + ".BJ"
    return symbol


def format_qmt_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")


def normalize_dividend_type(value: str | None) -> str:
    mapping = {
        None: "none", "": "none", "none": "none", "qfq": "front", "hfq": "back",
        "front": "front", "back": "back", "front_ratio": "front_ratio", "back_ratio": "back_ratio",
    }
    key = value.lower() if isinstance(value, str) else value
    if key not in mapping:
        raise QmtApiError(f"Unsupported QMT dividend_type: {value}")
    return mapping[key]


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
    qmt_symbol = normalize_qmt_symbol(symbol)
    start_time = format_qmt_date(start_date)
    end_time = format_qmt_date(end_date)
    field_list = fields or DEFAULT_OHLCV_FIELDS
    payload = {
        "fields": ",".join(field_list),
        "stock_code": qmt_symbol,
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
        raise QmtApiError(str(response["error"]))
    return market_data_payload_to_ohlcv(response.get("data"), qmt_symbol, field_list)


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
        raise QmtApiError(f"QMT API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise QmtApiError(f"QMT API connection failed: {exc.reason}") from exc
    except OSError as exc:
        raise QmtApiError(f"QMT API request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise QmtApiError("QMT API returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise QmtApiError("QMT API response is not a JSON object")
    return parsed


def market_data_payload_to_ohlcv(data: Any, symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    """Normalize common QMT DataFrame.to_dict payloads into date/open/high/low/close/volume."""
    field_list = fields or DEFAULT_OHLCV_FIELDS
    if data is None:
        raise QmtApiError("QMT API response missing data")

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

    raise QmtApiError("Unsupported QMT market data payload shape")


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
        raise QmtApiError(f"QMT API response missing fields: {', '.join(missing)}")
    for field in fields:
        frame[field] = pd.to_numeric(frame[column_map[field]], errors="coerce")

    frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return frame[["date", *fields]]


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.rename(columns={"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"})[
        ["日期", "开盘", "收盘", "最高", "最低", "成交量"]
    ]


def to_title_case_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"])
    return frame.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})[
        ["Open", "High", "Low", "Close", "Volume"]
    ]


def _normalize_time_values(values: pd.Series) -> pd.Series:
    raw = values.astype(str).str.replace(r"\.0$", "", regex=True)
    lengths = raw.str.len()
    if lengths.ge(13).all():
        return pd.to_datetime(raw.astype("int64"), unit="ms", errors="coerce")
    if lengths.eq(8).all():
        return pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    if lengths.eq(14).all():
        return pd.to_datetime(raw, format="%Y%m%d%H%M%S", errors="coerce")
    return pd.to_datetime(raw, errors="coerce")
