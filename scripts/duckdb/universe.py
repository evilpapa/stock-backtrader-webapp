"""Discover and normalise Tushare security universes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.datahub import TickerMapper
from src.utils.datahub_client import DataHubClient


ASSET_PRIORITY = {
    "stock": 10,
    "index": 20,
    "fund": 30,
    "bond": 40,
    "repo": 50,
    "warrant": 60,
    "etf": 70,
}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: str
    asset_type: str
    source_sectors: str


class UniverseDiscovery:
    """通过 DataHub 读取证券分组，并保留来源信息。"""

    def __init__(
        self,
        timeout: float = 30.0,
        xtdata_client: Any | None = None,
        qmt_client: DataHubClient | None = None,
    ) -> None:
        self.data_client = qmt_client or DataHubClient(timeout=timeout, xtdata_client=xtdata_client)

    def list_sectors(self) -> list[str]:
        return self.data_client.sector_list()

    def discover(
        self,
        sector_map: dict[str, list[str]],
        *,
        asset_types: set[str] | None = None,
        limit: int | None = None,
    ) -> tuple[pd.DataFrame, list[dict[str, str]]]:
        selected_types = asset_types or set(sector_map)
        records: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, str]] = []

        for asset_type, sectors in sector_map.items():
            if asset_type not in selected_types:
                continue
            for sector in sectors:
                try:
                    data = self.data_client.stock_list_in_sector(sector)
                except Exception as exc:  # a missing broker-specific sector is actionable
                    failures.append({"asset_type": asset_type, "sector": sector, "error": str(exc)})
                    continue

                for raw_symbol in data:
                    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
                        continue
                    symbol = TickerMapper.normalize(raw_symbol)
                    market = symbol.rsplit(".", maxsplit=1)[-1] if "." in symbol else ""
                    current = records.get(symbol)
                    if current is None or ASSET_PRIORITY.get(asset_type, 0) > current["priority"]:
                        records[symbol] = {
                            "symbol": symbol,
                            "market": market,
                            "asset_type": asset_type,
                            "source_sectors": {sector},
                            "priority": ASSET_PRIORITY.get(asset_type, 0),
                        }
                    else:
                        current["source_sectors"].add(sector)

        rows = []
        for item in records.values():
            rows.append({
                "symbol": item["symbol"],
                "market": item["market"],
                "asset_type": item["asset_type"],
                "source_sectors": ",".join(sorted(item["source_sectors"])),
            })
        frame = pd.DataFrame(rows, columns=["symbol", "market", "asset_type", "source_sectors"])
        if not frame.empty:
            frame = frame.sort_values(["asset_type", "market", "symbol"]).reset_index(drop=True)
        if limit is not None:
            frame = frame.head(max(0, limit)).copy()
        return frame, failures
