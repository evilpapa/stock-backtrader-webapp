"""无第三方账号即可使用的 Mock Provider，供单元测试和示例使用。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .models import DataKind, DataRequest, DataResult
from .provider import MarketDataProvider


class MockProvider(MarketDataProvider):
    """用静态 DataFrame 模拟任意数据源。"""

    def __init__(self, name: str = "mock", frames: dict[DataKind | str, pd.DataFrame] | None = None, available: bool = True) -> None:
        self.name = name
        self.frames = {DataKind(str(key)): value.copy() for key, value in (frames or {}).items()}
        self.available = available
        self.calls: list[DataKind] = []

    def supports(self, data_kind: DataKind) -> bool:
        return data_kind in self.frames

    def is_available(self) -> bool:
        return self.available

    def _get(self, kind: DataKind, request: DataRequest) -> DataResult:
        self.calls.append(kind)
        return DataResult(self.frames.get(kind, pd.DataFrame()).copy(), self.name, kind, request.request_id)

    def get_daily(self, request: DataRequest) -> DataResult: return self._get(DataKind.DAILY, request)
    def get_minute(self, request: DataRequest) -> DataResult: return self._get(DataKind.MINUTE, request)
    def get_tick(self, request: DataRequest) -> DataResult: return self._get(DataKind.TICK, request)
    def get_realtime(self, request: DataRequest) -> DataResult: return self._get(DataKind.REALTIME, request)
    def get_stock_basic(self, request: DataRequest) -> DataResult: return self._get(DataKind.STOCK_BASIC, request)
    def get_trade_calendar(self, request: DataRequest) -> DataResult: return self._get(DataKind.TRADE_CALENDAR, request)
    def get_financial(self, request: DataRequest) -> DataResult: return self._get(DataKind.FINANCIAL, request)
    def get_adj_factor(self, request: DataRequest) -> DataResult: return self._get(DataKind.ADJ_FACTOR, request)

    def get_extension(self, data_kind: DataKind, request: DataRequest) -> DataResult:
        return self._get(data_kind, request)
