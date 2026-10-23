"""统一多数据源金融数据访问基础设施。

业务代码只应依赖 :class:`MarketDataService`、请求模型和统一数据模型。
Tushare Pro 与 XtQuant 的 SDK 只在 ``providers`` 适配器中出现。
"""

from .config import DataHubConfig, load_config
from .bootstrap import create_service
from .exceptions import (
    DataHubError,
    DataSourceTimeout,
    DataValidationError,
    ProviderPermissionError,
    ProviderUnavailable,
    StorageError,
    SubscriptionError,
    TickerMappingError,
    UnsupportedDataKind,
)
from .factory import ProviderFactory
from .models import (
    Adjust,
    BarTimestamp,
    DataKind,
    DataRequest,
    DataResult,
    FinancialRequest,
    RealtimeEvent,
)
from .mock import MockProvider
from .realtime import RealtimeDataService
from .router import DataRouter
from .service import MarketDataService
from .normalizer import Normalizer
from .provider import MarketDataProvider, RealtimeProvider
from .storage import MemoryCache, ParquetRepository, SQLiteRepository
from .providers.local_cache import DuckDBCacheProvider
from .ticker import TickerMapper

__all__ = [
    "Adjust",
    "BarTimestamp",
    "DataHubConfig",
    "DataHubError",
    "DataKind",
    "DataRequest",
    "DataResult",
    "DataRouter",
    "DataSourceTimeout",
    "DataValidationError",
    "DuckDBCacheProvider",
    "FinancialRequest",
    "MarketDataService",
    "MarketDataProvider",
    "MemoryCache",
    "MockProvider",
    "Normalizer",
    "ParquetRepository",
    "ProviderFactory",
    "ProviderPermissionError",
    "ProviderUnavailable",
    "RealtimeDataService",
    "RealtimeProvider",
    "RealtimeEvent",
    "StorageError",
    "SQLiteRepository",
    "SubscriptionError",
    "TickerMapper",
    "TickerMappingError",
    "UnsupportedDataKind",
    "load_config",
    "create_service",
]
