"""DataHub 默认组装入口。"""

from __future__ import annotations

from pathlib import Path

from .config import DataHubConfig, load_config
from .factory import ProviderFactory
from .normalizer import Normalizer
from .router import DataRouter
from .service import MarketDataService
from .storage import DataRepository, MemoryCache


def create_service(
    config: DataHubConfig | None = None,
    *,
    config_path: str | Path | None = None,
    repository: DataRepository | None = None,
) -> MarketDataService:
    """按 YAML 创建生产 Facade；真实 SDK 仍在 Provider 内延迟加载。"""

    config = config or load_config(config_path)
    providers = ProviderFactory.create_enabled(config)
    router = DataRouter(providers, config.routing)
    normalizer = Normalizer(unit_configs={**Normalizer().unit_configs, **config.units}, ticker_mapper=config.ticker_mapper)
    cache = MemoryCache(float(config.cache.get("ttl_seconds", 3600))) if config.cache.get("enabled", True) else None
    return MarketDataService(router, normalizer, repository, cache, config.ticker_mapper)
