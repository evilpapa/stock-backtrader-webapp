"""Discover and normalise QMT security universes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from src.utils.bigqmt_client import normalize_qmt_symbol


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
    """Use QMT sectors as the source of truth, while retaining sector provenance."""

    def __init__(
        self,
        rpc_call: Callable[..., dict[str, Any]],
        client: Any,
        account_id: str,
        timeout: float = 30.0,
    ) -> None:
        self.rpc_call = rpc_call
        self.client = client
        self.account_id = account_id
        self.timeout = timeout

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        response = self.rpc_call(
            self.client,
            self.account_id,
            method,
            params,
            timeout_seconds=self.timeout,
        )
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or f"QMT {method} 请求失败"))
        return response.get("data")

    def list_sectors(self) -> list[str]:
        data = self._call("get_sector_list", {})
        if isinstance(data, dict):
            data = data.get("sectors", data.get("data", data))
        if not isinstance(data, list):
            raise RuntimeError("get_sector_list 返回格式错误")
        return sorted({str(item) for item in data if item})

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
                    data = self._call("get_stock_list_in_sector", {"sector_name": sector})
                    if not isinstance(data, list):
                        raise RuntimeError("返回结果不是代码列表")
                except Exception as exc:  # a missing broker-specific sector is actionable
                    failures.append({"asset_type": asset_type, "sector": sector, "error": str(exc)})
                    continue

                for raw_symbol in data:
                    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
                        continue
                    symbol = normalize_qmt_symbol(raw_symbol)
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
