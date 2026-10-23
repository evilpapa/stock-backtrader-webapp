"""ProviderFactory：集中创建和注入 Provider。"""

from __future__ import annotations

from typing import Any, Mapping

from .config import DataHubConfig
from .provider import MarketDataProvider
from .providers.tushare import TushareProvider
from .providers.xtquant import XtQuantProvider


class ProviderFactory:
    """Provider 注册表工厂，扩展数据源只需注册新的构造器。"""

    _constructors: dict[str, Any] = {
        "tushare": TushareProvider,
        "xtquant": XtQuantProvider,
    }

    @classmethod
    def register(cls, name: str, constructor: Any) -> None:
        cls._constructors[name.lower()] = constructor

    @classmethod
    def create(cls, name: str, config: DataHubConfig | Mapping[str, Any] | None = None, **overrides: Any) -> MarketDataProvider:
        key = name.lower()
        if key not in cls._constructors:
            raise ValueError(f"未知 Provider: {name}")
        if isinstance(config, DataHubConfig):
            kwargs = dict(config.providers.get(key, {}))
            kwargs.pop("enabled", None)
            kwargs.pop("qmt_path", None)
            if key == "xtquant":
                kwargs.pop("timeout", None)
            if key == "tushare":
                kwargs["ticker_mapper"] = config.ticker_mapper
            if key == "xtquant":
                kwargs["ticker_mapper"] = config.ticker_mapper
        else:
            kwargs = dict((config or {}).get(key, {}))
        kwargs.pop("enabled", None)
        kwargs.pop("qmt_path", None)
        if key == "xtquant":
            kwargs.pop("timeout", None)
        kwargs.update(overrides)
        return cls._constructors[key](**kwargs)

    @classmethod
    def create_enabled(cls, config: DataHubConfig) -> dict[str, MarketDataProvider]:
        result = {}
        for name, values in config.providers.items():
            if values.get("enabled", True):
                result[name] = cls.create(name, config)
        return result
