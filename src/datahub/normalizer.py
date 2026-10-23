"""统一数据标准化 Pipeline 和质量校验。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from .exceptions import DataValidationError
from .models import Adjust, BarTimestamp, DataKind, DataRequest, DataResult
from .ticker import TickerMapper


BAR_COLUMNS = [
    "symbol", "datetime", "open", "high", "low", "close", "volume", "amount",
    "pre_close", "adj_factor", "source", "frequency", "adjust",
]
BASIC_COLUMNS = [
    "symbol", "name", "exchange", "market", "security_type", "industry",
    "list_date", "delist_date", "status", "source",
]
FINANCIAL_REQUIRED_COLUMNS = ["symbol", "end_date", "ann_date", "f_ann_date", "report_type", "source"]


@dataclass(frozen=True)
class UnitConfig:
    """Provider 原始单位到统一单位的乘数。

    Tushare 的 ``vol`` 按接口文档是手、``amount`` 是千元，因此默认是
    ``100`` 和 ``1000``；XtQuant 单位由本地终端/桥接返回，默认显式配置为
    原值，同时允许在 YAML 中覆盖，避免把单位差异藏在业务代码里。
    """

    volume_factor: float = 1.0
    amount_factor: float = 1.0
    volume_unit: str = "share"
    amount_unit: str = "CNY"


@dataclass
class Normalizer:
    """按 Pipeline 顺序执行字段、时间、单位、类型、去重和校验。"""

    ticker_mapper: TickerMapper = field(default_factory=TickerMapper)
    unit_configs: Mapping[str, UnitConfig] = field(default_factory=lambda: {
        "tushare": UnitConfig(volume_factor=100.0, amount_factor=1000.0, volume_unit="share", amount_unit="CNY"),
        "xtquant": UnitConfig(),
        # QMT 同步到 DuckDB 后已经是股、元，不再做 Tushare 的手/千元换算。
        "cache": UnitConfig(),
        "mock": UnitConfig(),
    })
    timezone: str = "Asia/Shanghai"

    def normalize(self, result: DataResult, request: DataRequest) -> DataResult:
        frame = result.data.copy() if isinstance(result.data, pd.DataFrame) else pd.DataFrame(result.data)
        if result.data_kind in {DataKind.DAILY, DataKind.MINUTE, DataKind.TICK, DataKind.REALTIME, DataKind.LEVEL2}:
            frame = self._normalize_bars(frame, result, request)
        elif result.data_kind == DataKind.STOCK_BASIC:
            frame = self._normalize_basic(frame, result)
        elif result.data_kind == DataKind.TRADE_CALENDAR:
            frame = self._normalize_calendar(frame, result)
        elif result.data_kind == DataKind.FINANCIAL:
            frame = self._normalize_financial(frame, result, request)
        elif result.data_kind == DataKind.ADJ_FACTOR:
            frame = self._normalize_adj_factor(frame, result)
        frame.attrs.update(result.metadata)
        frame.attrs.update({
            "source": result.source,
            "data_kind": result.data_kind.value,
            "timestamp_semantics": result.timestamp_semantics.value,
            "request_id": result.request_id or request.request_id,
            "data_version": self.version(frame, result.source, request),
        })
        return DataResult(
            frame, result.source, result.data_kind, result.request_id or request.request_id,
            result.timestamp_semantics, dict(frame.attrs),
        )

    def _normalize_bars(self, frame: pd.DataFrame, result: DataResult, request: DataRequest) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=BAR_COLUMNS)
        frame = self._rename(frame, {
            "ts_code": "symbol", "code": "symbol", "ticker": "symbol",
            "trade_date": "datetime", "date": "datetime", "time": "datetime", "bar_time": "datetime",
            "vol": "volume", "lastPrice": "close", "lastClose": "pre_close",
            "preClose": "pre_close", "adj": "adj_factor",
        })
        if "symbol" not in frame:
            symbols = self.ticker_mapper.normalize_many(request.symbols)
            frame["symbol"] = symbols[0] if len(symbols) == 1 else None
        frame["symbol"] = frame["symbol"].map(self.ticker_mapper.normalize)
        if "datetime" not in frame:
            raise DataValidationError(f"{result.source} 行情缺少时间字段")
        frame["datetime"] = self._datetime(frame["datetime"])
        config = self.unit_configs.get(result.source, UnitConfig())
        for column in ("open", "high", "low", "close", "pre_close", "adj_factor", "volume", "amount"):
            if column not in frame:
                frame[column] = pd.NA
            if column not in {"volume", "amount"}:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") * config.volume_factor
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce") * config.amount_factor
        frame["source"] = result.source
        frame["frequency"] = request.frequency
        frame["adjust"] = Adjust(request.adjust).value
        frame = frame.drop_duplicates(subset=["symbol", "datetime"], keep="last")
        frame = frame.sort_values(["symbol", "datetime"]).reset_index(drop=True)
        self._validate_ohlc(frame, result.source)
        return frame[BAR_COLUMNS]

    def _normalize_basic(self, frame: pd.DataFrame, result: DataResult) -> pd.DataFrame:
        frame = self._rename(frame, {
            "ts_code": "symbol", "stock_code": "symbol", "market": "market",
            "InstrumentName": "name", "OpenDate": "list_date", "ExpireDate": "delist_date",
            "stock_type": "security_type", "list_date": "list_date", "delist_date": "delist_date",
        })
        if "symbol" in frame:
            frame["symbol"] = frame["symbol"].map(self.ticker_mapper.normalize)
        for column in BASIC_COLUMNS:
            if column not in frame:
                frame[column] = pd.NA
        frame["exchange"] = frame["exchange"].fillna(frame["symbol"].map(self.ticker_mapper.to_exchange))
        for column in ("list_date", "delist_date"):
            frame[column] = self._datetime(frame[column])
        frame["source"] = result.source
        return frame.drop_duplicates(subset=["symbol"], keep="last")[BASIC_COLUMNS]

    def _normalize_calendar(self, frame: pd.DataFrame, result: DataResult) -> pd.DataFrame:
        frame = self._rename(frame, {"cal_date": "trade_date", "pretrade_date": "pre_trade_date", "exchange": "exchange"})
        if "trade_date" not in frame:
            raise DataValidationError(f"{result.source} 交易日历缺少 trade_date")
        for column in ("exchange", "is_open", "pre_trade_date"):
            if column not in frame:
                frame[column] = pd.NA
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["pre_trade_date"] = pd.to_datetime(frame["pre_trade_date"], errors="coerce")
        frame["is_open"] = pd.to_numeric(frame["is_open"], errors="coerce").astype("Int64")
        frame["source"] = result.source
        return frame[["exchange", "trade_date", "is_open", "pre_trade_date", "source"]].drop_duplicates(
            ["exchange", "trade_date"], keep="last"
        ).sort_values(["exchange", "trade_date"]).reset_index(drop=True)

    def _normalize_financial(self, frame: pd.DataFrame, result: DataResult, request: DataRequest) -> pd.DataFrame:
        frame = self._rename(frame, {"ts_code": "symbol", "report_date": "end_date"})
        for column in FINANCIAL_REQUIRED_COLUMNS:
            if column not in frame:
                frame[column] = pd.NA
        frame["symbol"] = frame["symbol"].map(self.ticker_mapper.normalize)
        for column in ("end_date", "ann_date", "f_ann_date"):
            frame[column] = self._datetime(frame[column])
        if request.as_of is not None:
            as_of = self._datetime(pd.Series([request.as_of])).iloc[0]
            frame = frame[frame["ann_date"].isna() | (frame["ann_date"] <= as_of)]
        frame["source"] = result.source
        return frame.drop_duplicates(subset=["symbol", "end_date", "ann_date", "report_type"], keep="last").sort_values(
            ["symbol", "end_date"]
        ).reset_index(drop=True)

    def _normalize_adj_factor(self, frame: pd.DataFrame, result: DataResult) -> pd.DataFrame:
        frame = self._rename(frame, {"ts_code": "symbol", "trade_date": "datetime"})
        if "symbol" in frame:
            frame["symbol"] = frame["symbol"].map(self.ticker_mapper.normalize)
        frame["datetime"] = self._datetime(frame["datetime"])
        frame["adj_factor"] = pd.to_numeric(frame.get("adj_factor"), errors="coerce")
        frame["source"] = result.source
        return frame[["symbol", "datetime", "adj_factor", "source"]].drop_duplicates(
            ["symbol", "datetime"], keep="last"
        ).sort_values(["symbol", "datetime"]).reset_index(drop=True)

    @staticmethod
    def _rename(frame: pd.DataFrame, aliases: Mapping[str, str]) -> pd.DataFrame:
        existing = {key: value for key, value in aliases.items() if key in frame.columns and value not in frame.columns}
        return frame.rename(columns=existing)

    def _datetime(self, values: pd.Series) -> pd.Series:
        if values.empty:
            return pd.to_datetime(values)
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.notna().all() and numeric.abs().between(10_000_000, 99_999_999).all():
            return pd.to_datetime(numeric.astype("Int64").astype(str), format="%Y%m%d", errors="coerce").dt.tz_localize(self.timezone)
        # DuckDB/Pandas 读取 DATE/TIMESTAMP 可能暴露为微秒或纳秒整数；
        # 不能把它们误当成毫秒，否则会全部变成 NaT，并在去重时只剩一行。
        if numeric.notna().all() and numeric.abs().median() > 1e17:
            return pd.to_datetime(numeric, unit="ns", utc=True, errors="coerce").dt.tz_convert(self.timezone)
        if numeric.notna().all() and numeric.abs().median() > 1e14:
            return pd.to_datetime(numeric, unit="us", utc=True, errors="coerce").dt.tz_convert(self.timezone)
        if numeric.notna().all() and numeric.abs().median() > 1e10:
            return pd.to_datetime(numeric, unit="ms", utc=True, errors="coerce").dt.tz_convert(self.timezone)
        parsed = pd.to_datetime(values.astype(str).str.replace(r"\.0$", "", regex=True), errors="coerce")
        if getattr(parsed.dt, "tz", None) is None:
            return parsed.dt.tz_localize(self.timezone)
        return parsed.dt.tz_convert(self.timezone)

    @staticmethod
    def _validate_ohlc(frame: pd.DataFrame, source: str) -> None:
        numeric = frame[["open", "high", "low", "close"]].notna().all(axis=1)
        invalid = numeric & (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
            | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        )
        if invalid.any():
            raise DataValidationError(f"{source} 返回 {int(invalid.sum())} 条 OHLC 不合理记录")
        if frame.duplicated(["symbol", "datetime"]).any():
            raise DataValidationError(f"{source} 返回重复行情主键")

    @staticmethod
    def version(frame: pd.DataFrame, source: str, request: DataRequest) -> str:
        payload = frame.to_json(orient="split", date_format="iso", date_unit="ns")
        encoded = json.dumps({"source": source, "request": request.cache_key(source), "data": payload}, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()[:20]
