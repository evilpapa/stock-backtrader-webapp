"""Helpers for loading OHLCV data with xtquant.xtdata."""

from __future__ import annotations

from typing import Any

import pandas as pd

# xtdata 默认返回的字段列表
DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]


class XtDataError(RuntimeError):
    """Raised when xtdata cannot return a usable market-data payload."""


"""Helpers for loading OHLCV data with xtquant.xtdata."""
def import_xtdata() -> Any:
    try:
        from xtquant import xtdata
    except ImportError as exc:
        raise XtDataError("xtquant 未安装或 MiniQmt xtdata 环境不可用") from exc
    return xtdata


def normalize_xt_symbol(symbol: str) -> str:
    """转换常见的 Akshare/Yahoo 股票代码为 xtdata code.market 格式。"""
    symbol = symbol.strip().upper()
    if symbol.endswith((".SH", ".SZ", ".BJ")):
        return symbol
    if len(symbol) == 6 and symbol.startswith(("5", "6", "9")):
        return symbol + ".SH"
    if len(symbol) == 6 and symbol.startswith(("0", "1", "2", "3")):
        return symbol + ".SZ"
    if len(symbol) == 6 and symbol.startswith(("4", "8")):
        return symbol + ".BJ"
    return symbol


def format_xt_date(value: Any) -> str:
    """转换 YYYY-MM-DD/日期类型 值为 xtdata YYYYMMDD 字符串。"""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")


def normalize_dividend_type(value: str | None) -> str:
    mapping = {
        None: "none",
        "": "none",
        "none": "none",
        "qfq": "front",
        "hfq": "back",
        "front": "front",
        "back": "back",
        "front_ratio": "front_ratio",
        "back_ratio": "back_ratio",
    }
    key = value.lower() if isinstance(value, str) else value
    if key not in mapping:
        raise XtDataError(f"Unsupported xtdata dividend_type: {value}")
    return mapping[key]


def fetch_history_ohlcv(
    symbol: str,
    start_date: Any,
    end_date: Any,
    period: str = "1d",
    dividend_type: str = "front",
    fields: list[str] | None = None,
    download: bool = True,
    xtdata_module: Any | None = None,
) -> pd.DataFrame:
    """
    获取历史 K 线数据，返回包含 date/open/high/low/close/volume 列的 DataFrame。
    通过 xtdata.get_market_data 下载并读取数据，支持前复权、后复权和不复权选项。
    ohlcv 代表：Open High Low Close Volume / 开盘价 最高价 最低价 收盘价 成交量
    """
    xt_symbol = normalize_xt_symbol(symbol)
    start_time = format_xt_date(start_date)
    end_time = format_xt_date(end_date)
    dividend_type = normalize_dividend_type(dividend_type)
    field_list = fields or DEFAULT_OHLCV_FIELDS
    xtdata = xtdata_module or import_xtdata()

    if download:
        xtdata.download_history_data(xt_symbol, period, start_time, end_time)

    data = xtdata.get_market_data(
        field_list=field_list,
        stock_list=[xt_symbol],
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=-1,
        dividend_type=dividend_type,
        fill_data=True,
    )
    return market_data_to_ohlcv(data, xt_symbol, field_list)


def market_data_to_ohlcv(data: dict[str, pd.DataFrame], symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    """
    将 xtdata 的 `dict[field] -> DataFrame` 结构转换为逐行的 OHLCV 数据格式。
    """
    field_list = fields or DEFAULT_OHLCV_FIELDS
    if not isinstance(data, dict):
        raise XtDataError("xtdata.get_market_data 未返回字段字典")

    series_by_field = {}
    for field in field_list:
        field_frame = data.get(field)
        if field_frame is None or field_frame.empty:
            raise XtDataError(f"xtdata 响应缺少字段: {field}")
        if symbol in field_frame.index:
            series = field_frame.loc[symbol]
        elif len(field_frame.index) == 1:
            series = field_frame.iloc[0]
        else:
            raise XtDataError(f"xtdata 响应不包含股票代码: {symbol}")
        series_by_field[field] = pd.to_numeric(series, errors="coerce")

    frame = pd.DataFrame(series_by_field)
    frame.index.name = "date"
    frame = frame.reset_index()
    frame["date"] = _normalize_time_values(frame["date"])
    frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return frame[["date", *field_list]]


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.rename(
        columns={
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
        }
    )[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]


def to_title_case_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    """
    保持已有策略示例与 Open/High/Low/Close/Volume 列兼容。
    """
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"])
    return frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )[["Open", "High", "Low", "Close", "Volume"]]


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
