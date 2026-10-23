"""只读本地行情缓存 Provider。

项目的 QMT 同步任务将日线写入按资产类型拆分的 DuckDB 文件。这个适配器
把该文件视为 DataHub 的一个只读 Provider，使回测业务不需要知道 DuckDB
表结构，也不会在 ``cache`` 模式下意外访问远程数据源。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..exceptions import ProviderUnavailable
from ..models import DataKind, DataRequest, DataResult
from ..provider import MarketDataProvider
from ..ticker import TickerMapper


class DuckDBCacheProvider(MarketDataProvider):
    """读取项目 QMT 日线 DuckDB 缓存的 DataHub Adapter。"""

    name = "cache"
    _supported = {DataKind.DAILY}

    def __init__(self, path: str | Path, ticker_mapper: TickerMapper | None = None) -> None:
        self.path = Path(path)
        self.ticker_mapper = ticker_mapper or TickerMapper()
        self._connection: Any | None = None

    def supports(self, data_kind: DataKind) -> bool:
        return data_kind in self._supported

    def is_available(self) -> bool:
        return self.path.is_file()

    def _db(self) -> Any:
        if not self.path.is_file():
            raise ProviderUnavailable(f"本地行情缓存不存在: {self.path}")
        if self._connection is None:
            try:
                import duckdb

                self._connection = duckdb.connect(str(self.path), read_only=True)
            except Exception as exc:
                raise ProviderUnavailable(f"无法打开本地行情缓存 {self.path}: {exc}") from exc
        return self._connection

    def get_daily(self, request: DataRequest) -> DataResult:
        if request.adjust.value != "none":
            raise ValueError(
                "当前 QMT DuckDB 本地缓存仅保存不复权日线，请将 dividend_type/adjust 设置为 none"
            )
        symbols = tuple(self.ticker_mapper.normalize(symbol) for symbol in request.symbols)
        if not symbols:
            return DataResult(pd.DataFrame(), self.name, DataKind.DAILY, request.request_id)

        placeholders = ", ".join("?" for _ in symbols)
        clauses = [f"symbol IN ({placeholders})"]
        params: list[Any] = list(symbols)
        if request.start is not None:
            clauses.append("trade_date >= CAST(? AS DATE)")
            params.append(_date_value(request.start))
        if request.end is not None:
            clauses.append("trade_date <= CAST(? AS DATE)")
            params.append(_date_value(request.end))
        query = f"""
            SELECT symbol, trade_date AS datetime, open, high, low, close,
                   volume, amount, dividend_type, source
            FROM daily_bars
            WHERE {' AND '.join(clauses)}
            ORDER BY symbol, trade_date
        """
        try:
            frame = self._db().execute(query, params).fetch_df()
        except Exception as exc:
            raise ProviderUnavailable(f"读取本地行情缓存失败 {self.path}: {exc}") from exc
        return DataResult(
            frame,
            self.name,
            DataKind.DAILY,
            request.request_id,
            metadata={
                "cache_path": str(self.path),
                "underlying_source": sorted(frame["source"].dropna().unique().tolist())
                if "source" in frame
                else [],
                "provider_unit_contract": "duckdb-qmt-cache-share-cny",
            },
        )

    def get_minute(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存只保存日线")

    def get_tick(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存只保存日线")

    def get_realtime(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存不提供实时行情")

    def get_stock_basic(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存不提供证券主数据")

    def get_trade_calendar(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存不提供交易日历")

    def get_financial(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存不提供财务数据")

    def get_adj_factor(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("本地 DuckDB 缓存不提供复权因子")

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _date_value(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]
