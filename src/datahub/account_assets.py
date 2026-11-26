"""资产管理页的账户快照及本地历史。"""

import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .ticker import TickerMapper

SHANGHAI = ZoneInfo("Asia/Shanghai")
ASSET_DB = Path(__file__).resolve().parents[2] / "data" / "asset_management" / "accounts.sqlite3"
AssetSource = Literal["live", "test"]


class AssetModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class Holding(AssetModel):
    symbol: str
    name: str = ""
    quantity: Decimal
    sellable: Decimal | None = None
    cost_price: Decimal | None = None
    price: Decimal | None = None
    market_value: Decimal | None = None
    profit: Decimal | None = None
    return_rate: Decimal | None = None


class AssetPoint(AssetModel):
    day: date
    net_asset: Decimal
    net_value_index: Decimal | None = None


class AccountAssets(AssetModel):
    source: AssetSource
    account_key: str
    name: str
    fetched_at: AwareDatetime
    source_as_of: AwareDatetime | None = None
    total_asset: Decimal
    net_asset: Decimal | None = None
    cash: Decimal | None = None
    frozen_cash: Decimal | None = None
    market_value: Decimal | None = None
    liabilities: Decimal | None = None
    holdings: list[Holding]
    history: list[AssetPoint] = Field(default_factory=list)
    period_start: date | None = None
    period_end: date | None = None
    period_profit: Decimal | None = None
    period_return: Decimal | None = None


def holding_symbol(value: str) -> str:
    return TickerMapper.normalize(value) if TickerMapper.validate(value) else value


def save_account_assets(accounts: list[AccountAssets], path: Path = ASSET_DB) -> None:
    if not accounts:
        return
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS account_assets (
                source TEXT, account_key TEXT, fetched_at TEXT, payload TEXT,
                PRIMARY KEY (source, account_key)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS asset_history (
                source TEXT, account_key TEXT, day TEXT, fetched_at TEXT, payload TEXT,
                PRIMARY KEY (source, account_key, day)
            )
        """)
        for account in accounts:
            fetched_at = account.fetched_at.astimezone(SHANGHAI).isoformat()
            key = (account.source, account.account_key)
            connection.execute("""
                INSERT INTO account_assets VALUES (?, ?, ?, ?)
                ON CONFLICT (source, account_key) DO UPDATE SET
                    fetched_at = excluded.fetched_at, payload = excluded.payload
                WHERE excluded.fetched_at >= account_assets.fetched_at
            """, (*key, fetched_at, account.model_dump_json(exclude={"history"})))
            connection.executemany("""
                INSERT INTO asset_history VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (source, account_key, day) DO UPDATE SET
                    fetched_at = excluded.fetched_at, payload = excluded.payload
                WHERE excluded.fetched_at >= asset_history.fetched_at
            """, [(*key, point.day.isoformat(), fetched_at, point.model_dump_json())
                  for point in account.history])


def load_account_assets(source: AssetSource, path: Path = ASSET_DB) -> list[AccountAssets]:
    if not path.is_file() or not path.stat().st_size:
        return []
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        rows = connection.execute(
            "SELECT account_key, payload FROM account_assets WHERE source = ? ORDER BY account_key",
            (source,),
        ).fetchall()
        accounts = []
        for key, payload in rows:
            history = connection.execute("""
                SELECT payload FROM asset_history
                WHERE source = ? AND account_key = ? ORDER BY day
            """, (source, key))
            accounts.append(AccountAssets.model_validate_json(payload).model_copy(update={
                "history": [AssetPoint.model_validate_json(point) for point, in history],
            }))
        return accounts
