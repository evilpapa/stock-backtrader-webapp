"""DuckDB persistence with transactional, idempotent upserts."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


class DuckDBStore:
    name = "duckdb"

    def __init__(self, database: str | Path) -> None:
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("请先执行 uv sync 安装 duckdb Python 包") from exc
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(self.database))

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        self.connection.execute(schema_path.read_text(encoding="utf-8"))

    def latest_trade_date(self) -> date | None:
        value = self.connection.execute("SELECT max(trade_date) FROM daily_bars").fetchone()[0]
        return value

    def latest_bar_time(self, period: str = "1d") -> date | None:
        if period != "1d":
            raise ValueError("DuckDB 目标只支持 1d 日线")
        return self.latest_trade_date()

    def upsert_instruments(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        now = pd.Timestamp.utcnow().tz_localize(None)
        values = frame.copy()
        values["first_seen_at"] = now
        values["last_seen_at"] = now
        values = values[["symbol", "market", "asset_type", "source_sectors", "first_seen_at", "last_seen_at"]]
        self.connection.register("_instrument_stage", values)
        try:
            self.connection.execute("BEGIN")
            self.connection.execute(
                """
                DELETE FROM instrument_master AS target
                USING _instrument_stage AS stage
                WHERE target.symbol = stage.symbol
                """
            )
            self.connection.execute("INSERT INTO instrument_master SELECT * FROM _instrument_stage")
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self.connection.unregister("_instrument_stage")

    def upsert_bars(self, frame: pd.DataFrame) -> int:
        """Backward-compatible daily-bar name used by older callers."""
        if "trade_date" in frame.columns and "bar_time" not in frame.columns:
            frame = frame.copy()
            frame["bar_time"] = frame.pop("trade_date")
        return self.write_bars(frame, period="1d")

    def write_bars(self, frame: pd.DataFrame, *, period: str = "1d") -> int:
        if period != "1d":
            raise ValueError("DuckDB 目标只支持 1d 日线，请将分钟/tick 写入 KDB-X")
        if frame.empty:
            return 0
        values = frame.copy()
        values["trade_date"] = pd.to_datetime(values.pop("bar_time"), errors="coerce").dt.normalize()
        values = values.dropna(subset=["trade_date"])
        if values.empty:
            return 0
        self.connection.register("_daily_stage", values)
        try:
            self.connection.execute("BEGIN")
            self.connection.execute(
                """
                DELETE FROM daily_bars AS target
                USING _daily_stage AS stage
                WHERE target.symbol = stage.symbol
                  AND target.trade_date = stage.trade_date
                  AND target.dividend_type = stage.dividend_type
                """
            )
            self.connection.execute(
                """
                INSERT INTO daily_bars
                SELECT symbol, market, asset_type, trade_date, open, high, low, close,
                       volume, amount, dividend_type, source, ingested_at
                FROM _daily_stage
                """
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self.connection.unregister("_daily_stage")
        return len(values)

    def start_run(self, start_date: date | str, end_date: date | str, dividend_type: str) -> str:
        run_id = uuid.uuid4().hex
        self.connection.execute(
            """
            INSERT INTO sync_runs(run_id, started_at, status, start_date, end_date, dividend_type)
            VALUES (?, ?, 'running', ?, ?, ?)
            """,
            [run_id, pd.Timestamp.utcnow().tz_localize(None), start_date, end_date, dividend_type],
        )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        instrument_count: int,
        bar_count: int,
        error_count: int,
        message: str = "",
    ) -> None:
        self.connection.execute(
            """
            UPDATE sync_runs
            SET finished_at = ?, status = ?, instrument_count = ?, bar_count = ?,
                error_count = ?, message = ?
            WHERE run_id = ?
            """,
            [
                pd.Timestamp.utcnow().tz_localize(None), status, instrument_count,
                bar_count, error_count, message, run_id,
            ],
        )

    def record_errors(self, run_id: str, errors: list[dict[str, str]]) -> None:
        if not errors:
            return
        now = pd.Timestamp.utcnow().tz_localize(None)
        values = pd.DataFrame([
            {
                "run_id": run_id,
                "symbol": item.get("symbol", ""),
                "error_type": item.get("error_type", "unknown"),
                "error": item.get("error", ""),
                "created_at": now,
            }
            for item in errors
        ])
        self.connection.register("_error_stage", values)
        try:
            self.connection.execute("INSERT INTO sync_errors SELECT * FROM _error_stage")
        finally:
            self.connection.unregister("_error_stage")
