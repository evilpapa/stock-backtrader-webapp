"""统一的原生 ``xtquant.xtdata`` 行情客户端。

本模块集中处理原生 xtdata 调用、参数、异常和载荷解析。股票池、回测和
DuckDB/KDB-X 等上层模块都通过 :class:`QmtDataClient` 复用这些能力。
历史调用方仍可使用 ``fetch_history_ohlcv`` 等兼容入口。
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from xtquant import xtdata


DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]
DAILY_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
REQUIRED_DAILY_FIELDS = ["open", "high", "low", "close", "volume"]
TICK_FIELDS = ["lastPrice", "volume", "amount", "bidPrice", "askPrice", "bidVol", "askVol"]
INTRADAY_PERIODS = {"1m", "5m", "15m", "30m", "60m"}


class QmtDataError(RuntimeError):
    """原生 QMT 行情请求失败或返回了无法识别的数据。"""


BigQmtApiError = QmtDataError


def normalize_qmt_symbol(symbol: str) -> str:
    """将常见证券代码格式规范化为 ``code.market``。"""
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
    """将日期、时间或字符串转换为 ``YYYYMMDD``。"""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")


def normalize_dividend_type(value: str | None) -> str:
    """将页面配置的复权选项转换为 xtdata 参数。"""
    mapping = {
        None: "none", "": "none", "none": "none", "qfq": "front", "hfq": "back",
        "front": "front", "back": "back", "front_ratio": "front_ratio",
        "back_ratio": "back_ratio",
    }
    key = value.lower() if isinstance(value, str) else value
    if key not in mapping:
        raise QmtDataError(f"Unsupported xtdata dividend_type: {value}")
    return mapping[key]


class QmtDataClient:
    """原生 xtdata 的统一、可注入客户端。"""

    def __init__(self, *, timeout: float = 30.0, xtdata_client: Any | None = None) -> None:
        self.timeout = timeout
        self.xtdata = xtdata_client or xtdata

    def history_ohlcv(
        self,
        symbol: str,
        start_date: Any,
        end_date: Any,
        *,
        period: str = "1d",
        dividend_type: str = "front",
        fields: list[str] | None = None,
    ) -> pd.DataFrame:
        qmt_symbol = normalize_qmt_symbol(symbol)
        field_list = fields or DEFAULT_OHLCV_FIELDS
        try:
            response = self.xtdata.get_market_data_ex(
                field_list=field_list,
                stock_list=[qmt_symbol],
                period=period,
                start_time=format_qmt_date(start_date),
                end_time=format_qmt_date(end_date),
                count=-1,
                dividend_type=normalize_dividend_type(dividend_type),
                fill_data=True,
            )
        except Exception as exc:
            raise QmtDataError(f"QMT get_market_data_ex 请求失败: {exc}") from exc
        return market_data_payload_to_frame(response, qmt_symbol, field_list, numeric_fields=field_list)

    def daily_bars(
        self,
        symbols: list[str],
        start_date: Any,
        end_date: Any,
        *,
        dividend_type: str = "none",
        download_missing: bool = False,
    ) -> dict[str, pd.DataFrame]:
        result = self.market_bars(
            symbols,
            start_date,
            end_date,
            period="1d",
            dividend_type=dividend_type,
            download_missing=download_missing,
        )
        return {symbol: self._bar_frame_to_daily(frame) for symbol, frame in result.items()}

    def market_bars(
        self,
        symbols: list[str],
        start_date: Any,
        end_date: Any,
        *,
        period: str = "1d",
        dividend_type: str = "none",
        download_missing: bool = False,
    ) -> dict[str, pd.DataFrame]:
        if period not in {"1d", *INTRADAY_PERIODS, "tick"}:
            raise ValueError(f"不支持的 QMT 周期: {period}")
        fields = TICK_FIELDS if period == "tick" else DAILY_FIELDS
        data = self._get_market_data(symbols, start_date, end_date, period, fields, dividend_type)
        result = self._parse_market_payload(data, symbols, fields, period)
        if download_missing and not any(not frame.empty for frame in result.values()):
            try:
                self.xtdata.download_history_data2(
                    stock_list=symbols,
                    period=period,
                    start_time=format_qmt_date(start_date),
                    end_time=format_qmt_date(end_date),
                )
            except Exception as exc:
                raise QmtDataError(f"QMT download_history_data2 请求失败: {exc}") from exc
            data = self._get_market_data(symbols, start_date, end_date, period, fields, dividend_type)
            result = self._parse_market_payload(data, symbols, fields, period)
        return result

    def sector_list(self, *, allow_fallback: bool = False) -> list[str]:
        try:
            data = self.xtdata.get_sector_list(allow_fallback=allow_fallback)
        except Exception as exc:
            raise QmtDataError(f"QMT get_sector_list 请求失败: {exc}") from exc
        if isinstance(data, dict):
            data = data.get("sectors", data.get("data", data))
        if not isinstance(data, list):
            raise QmtDataError("get_sector_list 返回格式错误")
        return sorted(str(item) for item in data if item)

    def stock_list_in_sector(self, sector_name: str) -> list[str]:
        try:
            data = self.xtdata.get_stock_list_in_sector(sector_name)
        except Exception as exc:
            raise QmtDataError(f"QMT get_stock_list_in_sector 请求失败: {exc}") from exc
        if not isinstance(data, list):
            raise QmtDataError("get_stock_list_in_sector 返回格式错误")
        return [str(item) for item in data if item]

    def instrument_detail(self, symbol: str, *, is_detail: bool = True) -> dict[str, Any] | None:
        try:
            try:
                detail = self.xtdata.get_instrument_detail(symbol, is_detail=is_detail)
            except TypeError as exc:
                if "is_detail" not in str(exc):
                    raise
                detail = self.xtdata.get_instrument_detail(symbol, iscomplete=is_detail)
        except Exception as exc:
            raise QmtDataError(f"QMT get_instrument_detail 请求失败: {exc}") from exc
        return detail if isinstance(detail, dict) else None

    def historical_st_data(self, symbol: str) -> Any:
        try:
            return self.xtdata.get_his_st_data(symbol)
        except Exception as exc:
            raise QmtDataError(f"QMT get_his_st_data 请求失败: {exc}") from exc

    def financial_data(self, symbols: list[str], *, tables: list[str], end_date: Any) -> Any:
        try:
            return self.xtdata.get_financial_data(
                stock_list=symbols,
                table_list=tables,
                start_time="",
                end_time=format_qmt_date(end_date),
            )
        except Exception as exc:
            raise QmtDataError(f"QMT get_financial_data 请求失败: {exc}") from exc

    def local_data(self, **params: Any) -> Any:
        try:
            return self.xtdata.get_local_data(**params)
        except Exception as exc:
            raise QmtDataError(f"QMT get_local_data 请求失败: {exc}") from exc

    def _get_market_data(
        self,
        symbols: list[str],
        start_date: Any,
        end_date: Any,
        period: str,
        fields: list[str],
        dividend_type: str,
    ) -> Any:
        try:
            return self.xtdata.get_market_data_ex(
                field_list=fields,
                stock_list=symbols,
                period=period,
                start_time=format_qmt_date(start_date),
                end_time=format_qmt_date(end_date),
                count=-1,
                dividend_type=dividend_type,
                fill_data=False,
            )
        except Exception as exc:
            raise QmtDataError(f"QMT get_market_data_ex 请求失败: {exc}") from exc

    @staticmethod
    def _bar_frame_to_daily(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["date", *DAILY_FIELDS])
        result = frame.rename(columns={"bar_time": "date"}).copy()
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        for field in DAILY_FIELDS:
            if field not in result:
                result[field] = float("nan")
        return result[["date", *DAILY_FIELDS]]

    @staticmethod
    def _parse_market_payload(data: Any, symbols: list[str], fields: list[str], period: str) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            try:
                frame = market_data_payload_to_frame(data, symbol, fields, numeric_fields=fields)
            except QmtDataError as exc:
                if "amount" not in fields or "amount" not in str(exc):
                    result[symbol] = pd.DataFrame(columns=["date", *fields])
                    continue
                fallback_fields = [field for field in fields if field != "amount"]
                try:
                    frame = market_data_payload_to_frame(data, symbol, fallback_fields, numeric_fields=fallback_fields)
                except QmtDataError:
                    result[symbol] = pd.DataFrame(columns=["date", *fields])
                    continue
                frame["amount"] = float("nan")
            frame = frame.rename(columns={
                "lastPrice": "last", "bidPrice": "bid", "askPrice": "ask",
                "bidVol": "bid_volume", "askVol": "ask_volume",
            })
            for column in ["open", "high", "low", "close", "last", "volume", "amount", "bid", "ask", "bid_volume", "ask_volume"]:
                if column not in frame.columns:
                    frame[column] = float("nan")
            frame["bar_time"] = (
                pd.to_datetime(frame.pop("date"), errors="coerce").dt.normalize()
                if period == "1d"
                else pd.to_datetime(frame.pop("date"), errors="coerce")
            )
            result[symbol] = frame[[
                "bar_time", "open", "high", "low", "close", "last", "volume", "amount",
                "bid", "ask", "bid_volume", "ask_volume",
            ]]
        return result


def market_data_payload_to_ohlcv(data: Any, symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    field_list = fields or DEFAULT_OHLCV_FIELDS
    return market_data_payload_to_frame(data, symbol, field_list, numeric_fields=field_list)


def market_data_payload_to_frame(data: Any, symbol: str, fields: list[str], *, numeric_fields: list[str] | None = None) -> pd.DataFrame:
    field_list = list(fields)
    if data is None:
        raise QmtDataError("QMT response missing data")
    if isinstance(data, pd.DataFrame):
        return _frame_to_fields(data, field_list, numeric_fields)
    if isinstance(data, dict):
        if data.get("__bigqmt_type__") == "DataFrame":
            return _frame_to_fields(pd.DataFrame(data.get("records", [])), field_list, numeric_fields)
        if {"index", "columns", "data"}.issubset(data):
            return _frame_to_fields(pd.DataFrame(data["data"], index=data["index"], columns=data["columns"]), field_list, numeric_fields)
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
    raise QmtDataError("Unsupported QMT market data payload shape")


def _field_payload_to_series(value: Any, symbol: str) -> pd.Series:
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return pd.Series(dtype=float)
        if symbol in value.index:
            row = value.loc[symbol]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
        elif len(value.index) == 1:
            row = value.iloc[0]
        else:
            raise QmtDataError(f"QMT response missing symbol: {symbol}")
        return pd.Series(row.to_numpy(), index=row.index)
    if isinstance(value, dict):
        if symbol in value and isinstance(value[symbol], dict):
            return pd.Series(value[symbol])
        return pd.Series({key: item.get(symbol, next(iter(item.values()))) if isinstance(item, dict) and item else item for key, item in value.items()})
    return pd.Series(value if isinstance(value, list) else [value])


def _looks_like_index_orient(data: dict[str, Any], fields: list[str]) -> bool:
    return bool(data) and isinstance(next(iter(data.values())), dict) and any(field in next(iter(data.values())) for field in fields)


def _frame_to_fields(frame: pd.DataFrame, fields: list[str], numeric_fields: list[str] | None = None) -> pd.DataFrame:
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
        raise QmtDataError(f"QMT response missing fields: {', '.join(missing)}")
    for field in numeric_fields or fields:
        if field in field_columns:
            frame[field] = pd.to_numeric(frame[field_columns[field]], errors="coerce")
    for field, column in field_columns.items():
        if field not in frame.columns:
            frame[field] = frame[column]
    return frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)[["date", *fields]]


def _normalize_time_values(values: pd.Series) -> pd.Series:
    raw = values.astype(str).str.replace(r"\.0$", "", regex=True)
    lengths = raw.str.len()
    if lengths.eq(8).all():
        return pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    if lengths.eq(14).all():
        return pd.to_datetime(raw, format="%Y%m%d%H%M%S", errors="coerce")
    numeric = pd.to_numeric(raw, errors="coerce")
    if numeric.notna().all() and not numeric.empty:
        magnitude = numeric.abs().median()
        if magnitude >= 1e11:
            return pd.to_datetime(numeric, unit="ms", errors="coerce")
        if magnitude >= 1e9:
            return pd.to_datetime(numeric, unit="s", errors="coerce")
    return pd.to_datetime(raw, errors="coerce")


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.rename(columns={"date": "日期", "open": "开盘", "close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"})[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]


def to_title_case_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"])
    return frame.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})[["Open", "High", "Low", "Close", "Volume"]]


def get_xtdata(*, timeout: float | None = None, xtdata_client: Any | None = None) -> Any:
    """兼容旧入口，返回原生 xtdata 模块。"""
    return QmtDataClient(timeout=timeout or 30.0, xtdata_client=xtdata_client).xtdata


def fetch_history_ohlcv(
    symbol: str,
    start_date: Any,
    end_date: Any,
    period: str = "1d",
    dividend_type: str = "front",
    fields: list[str] | None = None,
    timeout: float = 10.0,
    xtdata_client: Any | None = None,
) -> pd.DataFrame:
    """兼容旧入口，委托给统一的原生 xtdata 客户端。"""
    return QmtDataClient(timeout=timeout, xtdata_client=xtdata_client).history_ohlcv(
        symbol, start_date, end_date, period=period, dividend_type=dividend_type, fields=fields,
    )


__all__ = [
    "BigQmtApiError", "DAILY_FIELDS", "DEFAULT_OHLCV_FIELDS", "INTRADAY_PERIODS",
    "QmtDataClient", "QmtDataError", "REQUIRED_DAILY_FIELDS", "TICK_FIELDS",
    "fetch_history_ohlcv", "format_qmt_date", "get_xtdata", "market_data_payload_to_frame",
    "market_data_payload_to_ohlcv", "normalize_dividend_type", "normalize_qmt_symbol",
    "to_chinese_ohlcv", "to_title_case_ohlcv",
]
