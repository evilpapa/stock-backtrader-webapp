"""Market-data client backed by the ``xtquant-big-convert`` Big QMT RPC bridge."""

from __future__ import annotations

import os
from typing import Any, Callable

import pandas as pd

DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]


class BigQmtApiError(RuntimeError):
    """Raised when the Big QMT bridge cannot return usable OHLCV data."""


def normalize_qmt_symbol(symbol: str) -> str:
    """Convert common ticker formats to the Big QMT ``code.market`` format."""
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
        raise BigQmtApiError(f"Unsupported Big QMT dividend_type: {value}")
    return mapping[key]


def fetch_history_ohlcv(
    symbol: str,
    start_date: Any,
    end_date: Any,
    period: str = "1d",
    dividend_type: str = "front",
    fields: list[str] | None = None,
    account_id: str | None = None,
    timeout: float = 10.0,
    redis_client: Any | None = None,
    rpc_call: Callable[..., dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """通过 Big QMT Redis RPC 代理 获取 OHLCV 数据

    Redis 连接设置通过  ``BIGQMT_REDIS_*`` 环境变量读取；
    账户 ID 在未提供时通过 ``BIGQMT_ACCOUNT_ID`` 读取。
    """
    qmt_symbol = normalize_qmt_symbol(symbol)
    account_id = account_id or os.getenv("BIGQMT_ACCOUNT_ID", "")
    if not account_id:
        raise BigQmtApiError("BIGQMT_ACCOUNT_ID is required for the Big QMT bridge")

    field_list = fields or DEFAULT_OHLCV_FIELDS
    call = rpc_call or _call_redis_rpc
    client = redis_client or _create_redis_client()
    try:
        response = call(
            client,
            account_id,
            "get_market_data_ex",
            {
                "field_list": field_list,
                "stock_list": [qmt_symbol],
                "period": period,
                "start_time": format_qmt_date(start_date),
                "end_time": format_qmt_date(end_date),
                "count": -1,
                "dividend_type": normalize_dividend_type(dividend_type),
            },
            timeout_seconds=timeout,
        )
    except Exception as exc:
        raise BigQmtApiError(f"Big QMT RPC request failed: {exc}") from exc

    if not response.get("ok"):
        raise BigQmtApiError(str(response.get("error") or "Big QMT RPC request failed"))
    return market_data_payload_to_ohlcv(response.get("data"), qmt_symbol, field_list)


def _create_redis_client() -> Any:
    try:
        import redis
    except ImportError as exc:  # pragma: no cover - package dependency guard
        raise BigQmtApiError("xtquant-big-convert[redis] is required") from exc
    return redis.Redis(
        host=os.getenv("BIGQMT_REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("BIGQMT_REDIS_PORT", "6379")),
        db=int(os.getenv("BIGQMT_REDIS_DB", "5")),
        username=os.getenv("BIGQMT_REDIS_USERNAME") or None,
        password=os.getenv("BIGQMT_REDIS_PASSWORD") or None,
    )


def _call_redis_rpc(*args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        from bigqmt_signal_trader.redis_rpc import call_redis_rpc
    except ImportError as exc:  # pragma: no cover - package dependency guard
        raise BigQmtApiError("xtquant-big-convert is required") from exc
    return call_redis_rpc(*args, **kwargs)


def market_data_payload_to_ohlcv(data: Any, symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    """Normalize Big QMT RPC market-data payloads into standard OHLCV columns."""
    field_list = fields or DEFAULT_OHLCV_FIELDS
    if data is None:
        raise BigQmtApiError("Big QMT RPC response missing data")
    if isinstance(data, dict):
        if data.get("__bigqmt_type__") == "DataFrame":
            return _frame_to_ohlcv(pd.DataFrame(data.get("records", [])), field_list)
        if {"index", "columns", "data"}.issubset(data):
            return _frame_to_ohlcv(pd.DataFrame(data["data"], index=data["index"], columns=data["columns"]), field_list)
        if all(field in data for field in field_list):
            frame = pd.DataFrame({field: _field_payload_to_series(data[field], symbol) for field in field_list})
            frame.index.name = "date"
            return _frame_to_ohlcv(frame.reset_index(), field_list)
        if symbol in data:
            return market_data_payload_to_ohlcv(data[symbol], symbol, field_list)
        if _looks_like_index_orient(data, field_list):
            return _frame_to_ohlcv(pd.DataFrame.from_dict(data, orient="index"), field_list)
    if isinstance(data, list):
        return _frame_to_ohlcv(pd.DataFrame(data), field_list)
    raise BigQmtApiError("Unsupported Big QMT market data payload shape")


def _field_payload_to_series(value: Any, symbol: str) -> pd.Series:
    if isinstance(value, dict):
        if symbol in value and isinstance(value[symbol], dict):
            return pd.Series(value[symbol])
        return pd.Series({key: item.get(symbol, next(iter(item.values()))) if isinstance(item, dict) and item else item for key, item in value.items()})
    return pd.Series(value if isinstance(value, list) else [value])


def _looks_like_index_orient(data: dict[str, Any], fields: list[str]) -> bool:
    return bool(data) and isinstance(next(iter(data.values())), dict) and any(field in next(iter(data.values())) for field in fields)


def _frame_to_ohlcv(frame: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", *fields])
    frame = frame.copy()
    frame.columns = [str(column) for column in frame.columns]
    column_map = {column.lower(): column for column in frame.columns}
    date_column = next((column_map[name] for name in ("date", "datetime", "time", "timetag", "index") if name in column_map), None)
    frame["date"] = _normalize_time_values(frame[date_column] if date_column else pd.Series(frame.index, index=frame.index))
    missing = [field for field in fields if field not in column_map]
    if missing:
        raise BigQmtApiError(f"Big QMT RPC response missing fields: {', '.join(missing)}")
    for field in fields:
        frame[field] = pd.to_numeric(frame[column_map[field]], errors="coerce")
    return frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)[["date", *fields]]


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.rename(columns={"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"})[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]


def to_title_case_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"])
    return frame.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})[["Open", "High", "Low", "Close", "Volume"]]


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
