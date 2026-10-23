"""Repository、缓存和历史版本存储实现。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .exceptions import StorageError
from .models import DataKind, DataRequest, DataResult


class DataRepository(Protocol):
    """Repository 模式的最小接口。"""

    def save(self, result: DataResult, request: DataRequest) -> str: ...

    def query(self, data_kind: DataKind | str, request: DataRequest, *, source: str | None = None) -> DataResult | None: ...

    def close(self) -> None: ...


@dataclass
class MemoryCache:
    """带 TTL 的进程内缓存；实时行情可以使用较短 TTL。"""

    ttl_seconds: float = 3600.0

    def __post_init__(self) -> None:
        self._items: dict[str, tuple[float, DataResult]] = {}

    def get(self, key: str) -> DataResult | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires, result = item
        if expires < time.monotonic():
            self._items.pop(key, None)
            return None
        return DataResult(result.data.copy(), result.source, result.data_kind, result.request_id, result.timestamp_semantics, dict(result.metadata))

    def put(self, key: str, result: DataResult, ttl_seconds: float | None = None) -> None:
        self._items[key] = (time.monotonic() + (self.ttl_seconds if ttl_seconds is None else ttl_seconds), result)

    def clear(self) -> None:
        self._items.clear()


class ParquetRepository:
    """按 data_kind/provider/symbol 分区的 Parquet Repository。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, result: DataResult, request: DataRequest) -> str:
        frame = result.data.copy()
        version = str(frame.attrs.get("data_version") or _version(frame, result.source, request))
        frame["__data_version"] = version
        try:
            groups = frame.groupby("symbol", dropna=False) if "symbol" in frame.columns else [(None, frame)]
            for symbol, group in groups:
                path = self._path(result, request, symbol)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    old = pd.read_parquet(path)
                    group = pd.concat([old, group], ignore_index=True)
                    keys = [column for column in ("symbol", "datetime", "trade_date", "end_date", "ann_date") if column in group]
                    if keys:
                        group = group.drop_duplicates(keys, keep="last")
                group.to_parquet(path, index=False)
                path.with_suffix(".meta.json").write_text(json.dumps({"source": result.source, "version": version, "request": request.cache_key(result.source)}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            raise StorageError(f"Parquet 写入失败: {exc}; 请安装 pyarrow 或 fastparquet") from exc
        return version

    def query(self, data_kind: DataKind | str, request: DataRequest, *, source: str | None = None) -> DataResult | None:
        kind = DataKind(str(data_kind))
        candidates = list(self.root.glob(f"{kind.value}/**/*.parquet"))
        if source:
            candidates = [path for path in candidates if f"/{source}/" in path.as_posix()]
        frames = []
        for path in candidates:
            try:
                frames.append(pd.read_parquet(path))
            except Exception as exc:
                raise StorageError(f"Parquet 读取失败 {path}: {exc}") from exc
        if not frames:
            return None
        frame = pd.concat(frames, ignore_index=True)
        if "symbol" in frame and request.symbols:
            frame = frame[frame["symbol"].isin(request.symbols)]
        frame = _filter_dates(frame, request)
        version = str(frame["__data_version"].iloc[0]) if "__data_version" in frame and not frame.empty else ""
        frame = frame.drop(columns=["__data_version"], errors="ignore")
        actual_source = source or (str(frame["source"].iloc[0]) if "source" in frame and not frame.empty else "storage")
        return DataResult(frame, actual_source, kind, metadata={"storage": "parquet", "data_version": version})

    def close(self) -> None:
        return None

    def _path(self, result: DataResult, request: DataRequest, symbol: Any | None = None) -> Path:
        value = request.symbol if symbol is None or pd.isna(symbol) else symbol
        partition = str(value or "_market").replace(".", "_")
        return self.root / result.data_kind.value / result.source / f"symbol={partition}" / "data.parquet"


class SQLiteRepository:
    """不依赖额外驱动的 SQLite Repository，支持幂等写入和版本追溯。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = sqlite3.connect(self.path)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS data_records (
                    record_key TEXT PRIMARY KEY,
                    data_kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT,
                    event_time TEXT,
                    version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    saved_at REAL NOT NULL
                )
            """)
            self.connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"SQLite 初始化失败: {exc}") from exc

    def save(self, result: DataResult, request: DataRequest) -> str:
        version = str(result.data.attrs.get("data_version") or _version(result.data, result.source, request))
        try:
            for row in result.data.to_dict(orient="records"):
                symbol = str(row.get("symbol", ""))
                event_time = str(row.get("datetime") or row.get("trade_date") or row.get("end_date") or "")
                record_key = hashlib.sha256(json.dumps({"kind": result.data_kind.value, "source": result.source, "symbol": symbol, "time": event_time, "row": row}, sort_keys=True, default=str).encode()).hexdigest()
                self.connection.execute(
                    "INSERT OR REPLACE INTO data_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (record_key, result.data_kind.value, result.source, symbol, event_time, version, json.dumps(row, ensure_ascii=False, default=str), request.cache_key(result.source), time.time()),
                )
            self.connection.commit()
        except (sqlite3.Error, TypeError, ValueError) as exc:
            self.connection.rollback()
            raise StorageError(f"SQLite 写入失败: {exc}") from exc
        return version

    def query(self, data_kind: DataKind | str, request: DataRequest, *, source: str | None = None) -> DataResult | None:
        kind = DataKind(str(data_kind))
        where = ["data_kind = ?"]
        params: list[Any] = [kind.value]
        if source:
            where.append("source = ?")
            params.append(source)
        if request.symbols:
            where.append("symbol IN (%s)" % ",".join("?" for _ in request.symbols))
            params.extend(request.symbols)
        try:
            rows = self.connection.execute(f"SELECT source, version, payload FROM data_records WHERE {' AND '.join(where)} ORDER BY event_time", params).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"SQLite 查询失败: {exc}") from exc
        if not rows:
            return None
        frame = pd.DataFrame([json.loads(row[2]) for row in rows])
        frame = _filter_dates(frame, request)
        if frame.empty:
            return None
        frame.attrs["data_version"] = rows[0][1]
        frame.attrs["storage"] = "sqlite"
        return DataResult(frame, rows[0][0], kind, metadata=dict(frame.attrs))

    def close(self) -> None:
        self.connection.close()


def _version(frame: pd.DataFrame, source: str, request: DataRequest) -> str:
    value = json.dumps({"source": source, "request": request.cache_key(source), "data": frame.to_json(orient="split", date_format="iso")}, sort_keys=True).encode()
    return hashlib.sha256(value).hexdigest()[:20]


def _filter_dates(frame: pd.DataFrame, request: DataRequest) -> pd.DataFrame:
    """Repository 查询层的日期裁剪，保留可复现请求的边界语义。"""

    column = next((name for name in ("datetime", "trade_date", "end_date") if name in frame.columns), None)
    if column is None or (request.start is None and request.end is None):
        return frame
    values = pd.to_datetime(frame[column], errors="coerce")
    start = pd.to_datetime(request.start, errors="coerce") if request.start is not None else None
    end = pd.to_datetime(request.end, errors="coerce") if request.end is not None else None
    if start is not None and pd.notna(start):
        if getattr(values.dt, "tz", None) is not None and getattr(start, "tzinfo", None) is None:
            start = start.tz_localize(values.dt.tz)
        frame = frame[values >= start]
        values = values[frame.index]
    if end is not None and pd.notna(end):
        if getattr(values.dt, "tz", None) is not None and getattr(end, "tzinfo", None) is None:
            end = end.tz_localize(values.dt.tz)
        frame = frame[values <= end]
    return frame.reset_index(drop=True)
