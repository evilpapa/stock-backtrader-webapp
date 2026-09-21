"""Configuration and universe defaults for the daily synchroniser."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SECTOR_MAP: dict[str, list[str]] = {
    "stock": ["沪深A股", "北证A股"],
    "index": ["沪深指数"],
    "fund": ["沪深基金"],
    "bond": ["沪深债券"],
    "repo": ["沪深回购"],
    "warrant": ["沪深权证"],
    "etf": ["沪深ETF"],
}


@dataclass(frozen=True)
class SyncConfig:
    """Runtime settings. Environment variables are intentionally QMT-compatible."""

    account_id: str = ""
    timeout: float = 30.0
    batch_size: int = 100
    duckdb_path: Path = Path("data/market.duckdb")
    kdb_host: str = "127.0.0.1"
    kdb_port: int = 5000
    kdb_username: str = ""
    kdb_password: str = ""
    qmt_start_date: str = "20000101"
    overlap_days: int = 7
    dividend_type: str = "none"
    sector_map: dict[str, list[str]] = field(default_factory=lambda: {
        key: list(value) for key, value in DEFAULT_SECTOR_MAP.items()
    })

    @classmethod
    def from_env(
        cls,
        *,
        duckdb_path: str | Path | None = None,
        duckdb_dir: str | Path | None = None,
        sector_map: dict[str, list[str]] | None = None,
    ) -> "SyncConfig":
        configured_path = duckdb_path or os.getenv("DUCKDB_PATH")
        if configured_path is None:
            configured_path = duckdb_dir or os.getenv("DUCKDB_DIR", "data/market.duckdb")
        return cls(
            account_id=os.getenv("BIGQMT_ACCOUNT_ID", ""),
            timeout=float(os.getenv("BIGQMT_RPC_TIMEOUT_SECONDS", "30")),
            batch_size=max(1, int(os.getenv("QMT_SYNC_BATCH_SIZE", "100"))),
            duckdb_path=Path(configured_path),
            kdb_host=os.getenv("KDB_HOST", "127.0.0.1"),
            kdb_port=int(os.getenv("KDB_PORT", "5000")),
            kdb_username=os.getenv("KDB_USERNAME", ""),
            kdb_password=os.getenv("KDB_PASSWORD", ""),
            qmt_start_date=os.getenv("QMT_SYNC_START_DATE", "20000101"),
            overlap_days=max(0, int(os.getenv("QMT_SYNC_OVERLAP_DAYS", "7"))),
            dividend_type=os.getenv("QMT_SYNC_DIVIDEND_TYPE", "none"),
            sector_map=sector_map or {
                key: list(value) for key, value in DEFAULT_SECTOR_MAP.items()
            },
        )

    @property
    def database_dir(self) -> Path:
        """Return the directory containing one DuckDB file per asset type.

        ``duckdb_path`` remains accepted for compatibility. A legacy file path
        such as ``data/market.duckdb`` uses its parent directory; a directory
        path is used directly.
        """
        path = Path(self.duckdb_path)
        return path.parent if path.suffix.lower() == ".duckdb" else path

    @property
    def legacy_database_path(self) -> Path:
        """Return the old combined database path used by migration."""
        path = Path(self.duckdb_path)
        return path if path.suffix.lower() == ".duckdb" else path / "market.duckdb"

    def database_path(self, asset_type: str) -> Path:
        """Return the split database path for one configured asset type."""
        name = str(asset_type).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"非法资产类型，不能用作数据库文件名: {asset_type}")
        return self.database_dir / f"{name}.duckdb"


def load_sector_map(path: str | Path | None) -> dict[str, list[str]]:
    """Load a YAML mapping and merge it with the built-in candidates."""
    if path is None:
        return {key: list(value) for key, value in DEFAULT_SECTOR_MAP.items()}

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise RuntimeError("读取板块配置需要 PyYAML") from exc

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"板块配置不存在: {config_path}")
    payload: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    groups = payload.get("asset_groups", payload) if isinstance(payload, dict) else {}
    result = {key: list(value) for key, value in DEFAULT_SECTOR_MAP.items()}
    for asset_type, sectors in groups.items():
        if isinstance(sectors, str):
            sectors = [sectors]
        if not isinstance(sectors, list) or not all(isinstance(item, str) for item in sectors):
            raise ValueError(f"asset_groups.{asset_type} 必须是字符串列表")
        result[str(asset_type)] = list(dict.fromkeys(sectors))
    return result
