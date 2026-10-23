"""DataRouter：按 Strategy 选择 Provider 并管理备用切换。"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from .exceptions import DataSourceTimeout, ProviderPermissionError, ProviderUnavailable, UnsupportedDataKind
from .models import DataKind, DataRequest, DataResult
from .provider import MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutePolicy:
    """单一数据类型的 Provider 优先级和容错策略。"""

    providers: tuple[str, ...]
    retries: int = 0
    fallback_on_empty: bool = False


@dataclass(frozen=True)
class RequestTrace:
    """一次请求实际尝试过的 Provider 及耗时。"""

    request_id: str
    data_kind: str
    provider: str
    started_at: float
    duration: float
    record_count: int
    status: str
    error: str | None = None


class DataRouter:
    """可配置的路由 Strategy。

    只有 Provider 不可用、超时或明确允许空结果切换时才使用备用源；参数错误、
    权限错误和标准化/质量错误不会被静默吞掉。
    """

    DEFAULT_POLICIES = {
        DataKind.DAILY: RoutePolicy(("tushare", "xtquant")),
        DataKind.MINUTE: RoutePolicy(("xtquant", "tushare")),
        DataKind.TICK: RoutePolicy(("xtquant",)),
        DataKind.REALTIME: RoutePolicy(("xtquant",)),
        DataKind.STOCK_BASIC: RoutePolicy(("tushare", "xtquant")),
        DataKind.TRADE_CALENDAR: RoutePolicy(("tushare", "xtquant")),
        DataKind.FINANCIAL: RoutePolicy(("tushare",)),
        DataKind.ADJ_FACTOR: RoutePolicy(("tushare", "xtquant")),
        DataKind.LEVEL2: RoutePolicy(("xtquant",)),
        DataKind.ETF_BASIC: RoutePolicy(("tushare",)),
        DataKind.ETF_SHARE: RoutePolicy(("tushare",)),
        DataKind.FUND_DAILY: RoutePolicy(("tushare",)),
        DataKind.FUND_ADJ: RoutePolicy(("tushare",)),
        DataKind.INDEX_DAILY: RoutePolicy(("tushare",)),
        DataKind.INDEX_MEMBER: RoutePolicy(("tushare",)),
        DataKind.INDEX_WEIGHT: RoutePolicy(("tushare",)),
        DataKind.CI_DAILY: RoutePolicy(("tushare",)),
        DataKind.DAILY_BASIC: RoutePolicy(("tushare",)),
        DataKind.MONEY_FLOW: RoutePolicy(("tushare",)),
        DataKind.ST: RoutePolicy(("tushare", "xtquant")),
        DataKind.HOT_RANK: RoutePolicy(("tushare",)),
        DataKind.BOARD_MEMBER: RoutePolicy(("tushare",)),
        DataKind.SECTOR_MEMBER: RoutePolicy(("xtquant", "tushare")),
        DataKind.DAILY_BULK: RoutePolicy(("tushare",)),
    }

    def __init__(
        self,
        providers: Mapping[str, MarketDataProvider],
        policies: Mapping[DataKind | str, RoutePolicy | Mapping[str, Any]] | None = None,
    ) -> None:
        self.providers = dict(providers)
        self.policies = dict(self.DEFAULT_POLICIES)
        for key, value in (policies or {}).items():
            kind = key if isinstance(key, DataKind) else DataKind(str(key))
            self.policies[kind] = value if isinstance(value, RoutePolicy) else RoutePolicy(
                tuple(value.get("providers", ())), int(value.get("retries", 0)), bool(value.get("fallback_on_empty", False))
            )
        self.traces: list[RequestTrace] = []

    def route(self, data_kind: DataKind | str, request: DataRequest) -> DataResult:
        kind = data_kind if isinstance(data_kind, DataKind) else DataKind(str(data_kind))
        policy = self.policies.get(kind)
        if policy is None:
            raise UnsupportedDataKind(f"没有为 {kind.value} 配置数据源路由")
        request_id = request.request_id or uuid.uuid4().hex
        last_retryable: Exception | None = None
        for provider_name in policy.providers:
            provider = self.providers.get(provider_name)
            if provider is None or not provider.supports(kind):
                continue
            try:
                if not provider.is_available():
                    raise ProviderUnavailable(f"Provider {provider_name} 不可用")
            except ProviderUnavailable as exc:
                last_retryable = exc
                self._trace(request_id, kind, provider_name, 0, 0, "unavailable", str(exc))
                continue
            for attempt in range(policy.retries + 1):
                started = time.perf_counter()
                try:
                    result = provider.fetch(kind, request)
                    result.request_id = request_id
                    if result.empty and not policy.fallback_on_empty:
                        self._trace(request_id, kind, provider_name, started, 0, "empty")
                        return result
                    if result.empty:
                        last_retryable = ProviderUnavailable(f"Provider {provider_name} 返回空数据")
                        self._trace(request_id, kind, provider_name, started, 0, "empty")
                        break
                    self._trace(request_id, kind, provider_name, started, len(result.data), "success")
                    return result
                except (ProviderUnavailable, DataSourceTimeout) as exc:
                    last_retryable = exc
                    self._trace(request_id, kind, provider_name, started, 0, "retryable_error", str(exc))
                    if attempt >= policy.retries:
                        break
                except (ProviderPermissionError, ValueError, TypeError):
                    self._trace(request_id, kind, provider_name, started, 0, "non_retryable_error")
                    raise
        if last_retryable is not None:
            raise last_retryable
        raise UnsupportedDataKind(f"没有可用 Provider 支持 {kind.value}")

    def _trace(self, request_id: str, kind: DataKind, provider: str, started: float, count: int, status: str, error: str | None = None) -> None:
        duration = time.perf_counter() - started if started else 0.0
        trace = RequestTrace(request_id, kind.value, provider, time.time(), duration, count, status, error)
        self.traces.append(trace)
        logger.info(
            "datahub request_id=%s data_kind=%s provider=%s duration=%.4f record_count=%d status=%s error=%s",
            trace.request_id, trace.data_kind, trace.provider, trace.duration, trace.record_count, trace.status, trace.error,
        )

