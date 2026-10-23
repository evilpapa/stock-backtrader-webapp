"""Provider 抽象接口（Adapter 模式的目标接口）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any

from .models import DataKind, DataRequest, DataResult


Callback = Callable[[Any], None]


class MarketDataProvider(ABC):
    """所有数据源必须实现的统一接口。"""

    name: str

    @abstractmethod
    def supports(self, data_kind: DataKind) -> bool:
        """返回 Provider 是否具备该数据能力。"""

    @abstractmethod
    def is_available(self) -> bool:
        """检查 SDK/连接/权限是否可用，不应发起破坏性操作。"""

    @abstractmethod
    def get_daily(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_minute(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_tick(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_realtime(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_stock_basic(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_trade_calendar(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_financial(self, request: DataRequest) -> DataResult:
        pass

    @abstractmethod
    def get_adj_factor(self, request: DataRequest) -> DataResult:
        pass

    def get_level2(self, request: DataRequest) -> DataResult:
        raise NotImplementedError(f"Provider {self.name} 不支持 level2")

    def get_extension(self, data_kind: DataKind, request: DataRequest) -> DataResult:
        """获取 Provider 专用但仍由 DataHub 管理的扩展数据。

        扩展能力不改变业务层依赖关系：调用方只传递统一的
        :class:`DataRequest`，第三方 API 名称和参数仍被限制在 Adapter 内。
        """

        raise NotImplementedError(f"Provider {self.name} 不支持 {data_kind.value}")

    def close(self) -> None:
        """释放 Provider 资源。默认无资源。"""

    def fetch(self, data_kind: DataKind, request: DataRequest) -> DataResult:
        """按数据类型分发到统一方法。"""

        method = {
            DataKind.DAILY: self.get_daily,
            DataKind.MINUTE: self.get_minute,
            DataKind.TICK: self.get_tick,
            DataKind.REALTIME: self.get_realtime,
            DataKind.STOCK_BASIC: self.get_stock_basic,
            DataKind.TRADE_CALENDAR: self.get_trade_calendar,
            DataKind.FINANCIAL: self.get_financial,
            DataKind.ADJ_FACTOR: self.get_adj_factor,
            DataKind.LEVEL2: self.get_level2,
        }.get(data_kind)
        if method is None and self.supports(data_kind):
            return self.get_extension(data_kind, request)
        if method is None or not self.supports(data_kind):
            raise NotImplementedError(f"Provider {self.name} 不支持 {data_kind.value}")
        return method(request)


class RealtimeProvider(ABC):
    """Observer/订阅能力的独立接口。"""

    @abstractmethod
    def subscribe_quote(self, symbols: Sequence[str], callback: Callback | None = None) -> str:
        pass

    @abstractmethod
    def unsubscribe_quote(self, subscription_id: str) -> None:
        pass

    @abstractmethod
    def subscribe_tick(self, symbols: Sequence[str], callback: Callback | None = None) -> str:
        pass

    @abstractmethod
    def unsubscribe_tick(self, subscription_id: str) -> None:
        pass

    @abstractmethod
    def register_callback(self, callback: Callback) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

