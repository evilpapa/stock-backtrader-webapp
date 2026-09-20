"""
基于 ``xtquant-big-convert`` 大 QMT RPC 桥接服务的行情数据客户端。
"""

from __future__ import annotations

import os
from typing import Any, Callable

import pandas as pd

DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]


class BigQmtApiError(RuntimeError):
    """大 QMT 桥接服务无法返回可用 OHLCV 数据时抛出的异常。"""


def normalize_qmt_symbol(symbol: str) -> str:
    """将常见证券代码格式规范化为大 QMT 使用的 ``code.market`` 格式。"""
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
    """将日期、时间或字符串转换为大 QMT 接口需要的 ``YYYYMMDD`` 风格字符串。"""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")


def normalize_dividend_type(value: str | None) -> str:
    """将页面或配置里的复权选项转换为大 QMT RPC 支持的复权参数。"""
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
    """通过 Big QMT Redis RPC 代理获取标准 OHLCV 行情数据。

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
    """根据环境变量创建连接大 QMT 桥接服务的 Redis 客户端。"""
    try:
        import redis
    except ImportError as exc:  # pragma: no cover - 依赖缺失保护
        raise BigQmtApiError("xtquant-big-convert[redis] is required") from exc
    return redis.Redis(
        host=os.getenv("BIGQMT_REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("BIGQMT_REDIS_PORT", "6379")),
        db=int(os.getenv("BIGQMT_REDIS_DB", "5")),
        username=os.getenv("BIGQMT_REDIS_USERNAME") or None,
        password=os.getenv("BIGQMT_REDIS_PASSWORD") or None,
    )


def _call_redis_rpc(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """延迟导入桥接库并发起 Redis RPC 调用，便于测试时替换调用函数。"""
    try:
        from bigqmt_signal_trader.redis_rpc import call_redis_rpc
    except ImportError as exc:  # pragma: no cover - 依赖缺失保护
        raise BigQmtApiError("xtquant-big-convert is required") from exc
    return call_redis_rpc(*args, **kwargs)


def market_data_payload_to_ohlcv(data: Any, symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    """将大 QMT RPC 返回的多种行情载荷格式统一转换为标准 OHLCV 列。"""
    field_list = fields or DEFAULT_OHLCV_FIELDS
    return market_data_payload_to_frame(data, symbol, field_list, numeric_fields=field_list)


def market_data_payload_to_frame(
    data: Any,
    symbol: str,
    fields: list[str],
    *,
    numeric_fields: list[str] | None = None,
) -> pd.DataFrame:
    """将 QMT 行情载荷转换为任意字段组成的时间序列表。

    日线 OHLCV 和分钟/tick 行情共用同一套 QMT 返回载荷格式；该函数把
    原先仅支持 OHLCV 的解析逻辑抽象出来，允许 KDB-X 保存盘口字段。
    """
    field_list = list(fields)
    if data is None:
        raise BigQmtApiError("Big QMT RPC response missing data")
    if isinstance(data, dict):
        if data.get("__bigqmt_type__") == "DataFrame":
            return _frame_to_fields(pd.DataFrame(data.get("records", [])), field_list, numeric_fields)
        if {"index", "columns", "data"}.issubset(data):
            return _frame_to_fields(
                pd.DataFrame(data["data"], index=data["index"], columns=data["columns"]),
                field_list,
                numeric_fields,
            )
        if all(field in data for field in field_list):
            frame = pd.DataFrame({field: _field_payload_to_series(data[field], symbol) for field in field_list})
            frame.index.name = "date"
            return _frame_to_fields(frame.reset_index(), field_list, numeric_fields)
        if symbol in data:
            return market_data_payload_to_frame(data[symbol], symbol, field_list, numeric_fields=numeric_fields)
        if _looks_like_index_orient(data, field_list):
            return _frame_to_fields(pd.DataFrame.from_dict(data, orient="index"), field_list, numeric_fields)
    if isinstance(data, list):
        return _frame_to_fields(pd.DataFrame(data), field_list, numeric_fields)
    raise BigQmtApiError("Unsupported Big QMT market data payload shape")


def _field_payload_to_series(value: Any, symbol: str) -> pd.Series:
    """把单个行情字段的嵌套载荷提取为按时间索引的序列。"""
    if isinstance(value, dict):
        if symbol in value and isinstance(value[symbol], dict):
            return pd.Series(value[symbol])
        return pd.Series({key: item.get(symbol, next(iter(item.values()))) if isinstance(item, dict) and item else item for key, item in value.items()})
    return pd.Series(value if isinstance(value, list) else [value])


def _looks_like_index_orient(data: dict[str, Any], fields: list[str]) -> bool:
    """判断载荷是否接近 pandas ``orient='index'`` 的字典结构。"""
    return bool(data) and isinstance(next(iter(data.values())), dict) and any(field in next(iter(data.values())) for field in fields)


def _frame_to_fields(
    frame: pd.DataFrame,
    fields: list[str],
    numeric_fields: list[str] | None = None,
) -> pd.DataFrame:
    """将已构造的 DataFrame 清洗为按时间排序的行情字段数据。"""
    if frame.empty:
        return pd.DataFrame(columns=["date", *fields])
    frame = frame.copy()
    frame.columns = [str(column) for column in frame.columns]
    column_map = {column.lower(): column for column in frame.columns}
    date_column = next((column_map[name] for name in ("date", "datetime", "time", "timetag", "index") if name in column_map), None)
    frame["date"] = _normalize_time_values(frame[date_column] if date_column else pd.Series(frame.index, index=frame.index))
    field_columns = {field: column_map.get(field.lower()) for field in fields}
    missing = [field for field, column in field_columns.items() if column is None]
    if missing:
        raise BigQmtApiError(f"Big QMT RPC response missing fields: {', '.join(missing)}")
    numeric_fields = numeric_fields or fields
    for field in numeric_fields:
        if field in field_columns:
            frame[field] = pd.to_numeric(frame[field_columns[field]], errors="coerce")
    for field, column in field_columns.items():
        if field not in frame.columns:
            frame[field] = frame[column]
    return frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)[["date", *fields]]


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    """将标准英文 OHLCV 列转换为页面展示使用的中文列名。"""
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.rename(columns={"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"})[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]


def to_title_case_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    """将标准 OHLCV 列转换为 Backtrader/PandasData 常用的首字母大写列名。"""
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"])
    return frame.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})[["Open", "High", "Low", "Close", "Volume"]]


def _normalize_time_values(values: pd.Series) -> pd.Series:
    """识别毫秒时间戳、日期串和普通时间文本，并统一转换为 pandas 时间类型。"""
    raw = values.astype(str).str.replace(r"\.0$", "", regex=True)
    lengths = raw.str.len()
    if lengths.ge(13).all():
        return pd.to_datetime(raw.astype("int64"), unit="ms", errors="coerce")
    if lengths.eq(8).all():
        return pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    if lengths.eq(14).all():
        return pd.to_datetime(raw, format="%Y%m%d%H%M%S", errors="coerce")
    return pd.to_datetime(raw, errors="coerce")
