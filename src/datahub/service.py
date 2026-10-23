"""MarketDataService Facade：业务层唯一入口。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import DataKind, DataRequest, DataResult
from .normalizer import Normalizer
from .router import DataRouter
from .storage import DataRepository, MemoryCache
from .ticker import TickerMapper


@dataclass
class MarketDataService:
    """统一获取、标准化、缓存和持久化的 Facade。"""

    router: DataRouter
    normalizer: Normalizer | None = None
    repository: DataRepository | None = None
    cache: MemoryCache | None = None
    ticker_mapper: TickerMapper | None = None

    def __post_init__(self) -> None:
        self.normalizer = self.normalizer or Normalizer(ticker_mapper=self.ticker_mapper or TickerMapper())

    def get(self, data_kind: DataKind | str, request: DataRequest, *, use_cache: bool = True, persist: bool = False) -> pd.DataFrame:
        kind = data_kind if isinstance(data_kind, DataKind) else DataKind(str(data_kind))
        source_hint = self._cache_source(kind)
        # 数据类型必须参与 Key；相同 symbol/date 参数在 stock_basic 与 daily
        # 场景下不能共享缓存。
        key = f"{kind.value}:{request.cache_key(source_hint)}"
        if use_cache and self.cache:
            cached = self.cache.get(key)
            if cached is not None:
                if persist and self.repository:
                    self.repository.save(cached, request)
                return cached.data.copy()
        routed = self.router.route(kind, request)
        normalized = self.normalizer.normalize(routed, request)
        if use_cache and self.cache:
            actual_key = f"{kind.value}:{request.cache_key(normalized.source)}"
            self.cache.put(actual_key, normalized)
        if persist and self.repository:
            self.repository.save(normalized, request)
        return normalized.data.copy()

    def _cache_source(self, kind: DataKind) -> str | None:
        """选择当前可用的首选源，避免备用源结果污染首选源缓存。"""

        policy = self.router.policies.get(kind)
        if policy is None:
            return None
        for name in policy.providers:
            provider = self.router.providers.get(name)
            if provider is None or not provider.supports(kind):
                continue
            try:
                if provider.is_available():
                    return name
            except Exception:
                continue
        return policy.providers[0] if policy.providers else None

    def get_daily(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.DAILY, request, **kwargs)

    def get_minute(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.MINUTE, request, **kwargs)

    def get_tick(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.TICK, request, **kwargs)

    def get_realtime(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.REALTIME, request, **kwargs)

    def get_stock_basic(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.STOCK_BASIC, request, **kwargs)

    def get_trade_calendar(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.TRADE_CALENDAR, request, **kwargs)

    def get_financial(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.FINANCIAL, request, **kwargs)

    def get_adj_factor(self, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        return self.get(DataKind.ADJ_FACTOR, request, **kwargs)

    def query(self, data_kind: DataKind | str, request: DataRequest, **kwargs: bool) -> pd.DataFrame:
        """查询 DataHub 扩展能力，保持与标准数据相同的路由/缓存流程。"""

        return self.get(data_kind, request, **kwargs)

    def close(self) -> None:
        if self.repository:
            self.repository.close()
        for provider in self.router.providers.values():
            provider.close()
