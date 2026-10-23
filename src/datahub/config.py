"""YAML/环境变量配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .normalizer import UnitConfig
from .router import RoutePolicy
from .ticker import TickerMapper


@dataclass
class DataHubConfig:
    """DataHub 运行配置，敏感信息只从环境变量读取。"""

    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    routing: dict[str, RoutePolicy] = field(default_factory=dict)
    storage: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)
    xtquant_formats: dict[str, dict[str, str]] = field(default_factory=dict)
    units: dict[str, UnitConfig] = field(default_factory=dict)
    retry: dict[str, Any] = field(default_factory=dict)

    @property
    def ticker_mapper(self) -> TickerMapper:
        return TickerMapper(self.xtquant_formats)


def load_config(path: str | Path | None = None) -> DataHubConfig:
    """读取 YAML 并注入 Token/QMT 路径等环境变量。"""

    config_path = Path(path) if path else Path(__file__).with_name("config") / "datahub.yaml"
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    providers = dict(raw.get("providers", {}))
    providers.setdefault("tushare", {})["token"] = os.getenv("TUSHARE_TOKEN", providers.get("tushare", {}).get("token", ""))
    providers.setdefault("xtquant", {})["qmt_path"] = os.getenv("QMT_PATH", providers.get("xtquant", {}).get("qmt_path", ""))
    routing = {}
    for key, value in raw.get("routing", {}).items():
        routing[key] = RoutePolicy(
            tuple(value.get("providers", ())), int(value.get("retries", raw.get("retry", {}).get("count", 0))), bool(value.get("fallback_on_empty", False))
        )
    units = {name: UnitConfig(**values) for name, values in raw.get("units", {}).items()}
    return DataHubConfig(
        providers=providers, routing=routing, storage=dict(raw.get("storage", {})),
        cache=dict(raw.get("cache", {})), xtquant_formats=dict(raw.get("ticker", {}).get("xtquant_formats", {})),
        units=units, retry=dict(raw.get("retry", {})),
    )
