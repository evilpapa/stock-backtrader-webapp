"""One immutable DuckDB database per cache partition or strategy artifact."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import duckdb
import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def file_sha256(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def frame_exists(path: str | Path) -> bool:
    path = Path(path)
    return path.is_file() or (path.suffix == ".duckdb" and path.with_suffix(".parquet").is_file())


def frame_paths(directory: Path, pattern: str = "*") -> list[Path]:
    paths = {path.with_suffix(".duckdb") for path in directory.glob(f"{pattern}.parquet")}
    paths.update(directory.glob(f"{pattern}.duckdb"))
    return sorted(paths)


def write_frame(
    path: str | Path,
    frame: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
    replace: bool = True,
) -> None:
    path = Path(path)
    if path.suffix != ".duckdb":
        raise ValueError(f"DuckDB 文件必须使用 .duckdb 扩展名: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    details = dict(metadata or {})
    if isinstance(frame, pd.DataFrame):
        if frame.columns.name is not None:
            details["column_index_name"] = frame.columns.name
        details["datetime_columns"] = {
            name: str(dtype) for name, dtype in frame.dtypes.items()
            if pd.api.types.is_datetime64_any_dtype(dtype)
        }
        if frame.columns.empty:
            details["no_columns"] = True
            frame = pd.DataFrame({"__empty": range(len(frame))})
    with TemporaryDirectory(prefix=f".{path.stem}-", dir=path.parent) as directory:
        temporary = Path(directory) / "artifact.duckdb"
        with duckdb.connect(str(temporary), config={"threads": 1, "default_block_size": 16384}) as connection:
            connection.register("incoming", frame)
            connection.execute("CREATE TABLE data AS SELECT * FROM incoming")
            connection.execute("CREATE TABLE artifact_metadata (content JSON)")
            connection.execute("INSERT INTO artifact_metadata VALUES (?)", [json.dumps(details, default=str)])
            connection.execute("CHECKPOINT")
        if replace:
            os.replace(temporary, path)
        else:
            with suppress(FileExistsError):
                os.link(temporary, path)


def promote_frame(path: str | Path) -> Path:
    """Materialize an old internal partition once, without replacing a concurrent writer."""
    path = Path(path)
    if path.suffix != ".duckdb" or path.is_file():
        return path
    legacy = path.with_suffix(".parquet")
    if not legacy.is_file():
        raise FileNotFoundError(path)
    if not path.resolve().is_relative_to(PROJECT_ROOT) or not legacy.resolve().is_relative_to(PROJECT_ROOT):
        return legacy
    parquet = pq.ParquetFile(legacy)
    details = {"legacy_sha256": file_sha256(legacy)}
    details.update({
        key.decode(): value.decode()
        for key, value in (parquet.schema_arrow.metadata or {}).items()
        if key in {b"archive_sha256", b"source_member", b"organizer_version", b"trade_date", b"rows", b"validation"}
    })
    write_frame(path, parquet.read().to_pandas(), metadata=details, replace=False)
    return path


def connection_metadata(connection: duckdb.DuckDBPyConnection) -> dict:
    return json.loads(connection.execute("SELECT content FROM artifact_metadata").fetchall()[0][0])


def frame_metadata(path: str | Path) -> dict:
    path = promote_frame(path)
    if path.suffix == ".parquet":
        return {}
    with duckdb.connect(str(path), read_only=True, config={"threads": 1}) as connection:
        return connection_metadata(connection)


def inspect_frame(path: str | Path) -> tuple[int, dict]:
    path = promote_frame(path)
    if path.suffix == ".parquet":
        parquet = pq.ParquetFile(path)
        return parquet.metadata.num_rows, {
            key.decode(): value.decode()
            for key, value in (parquet.schema_arrow.metadata or {}).items() if key != b"pandas"
        }
    with duckdb.connect(str(path), read_only=True, config={"threads": 1}) as connection:
        return connection.execute("SELECT count(*) FROM data").fetchall()[0][0], connection_metadata(connection)


def read_frame(
    path: str | Path, *, columns: Sequence[str] | None = None
) -> pd.DataFrame:
    frame, _ = read_frame_with_metadata(path, columns=columns)
    return frame


def read_frame_with_metadata(
    path: str | Path, *, columns: Sequence[str] | None = None
) -> tuple[pd.DataFrame, dict]:
    path = promote_frame(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path, columns=columns), {}
    selection = ", ".join('"' + column.replace('"', '""') + '"' for column in columns) if columns else "*"
    with duckdb.connect(str(path), read_only=True, config={"threads": 1}) as connection:
        metadata = connection_metadata(connection)
        frame = connection.sql(f"SELECT {selection} FROM data").to_arrow_table().to_pandas()
    if metadata.get("no_columns") or columns is not None and not len(columns):
        frame = frame.iloc[:, :0]
    frame.columns.name = metadata.get("column_index_name")
    for column, timezone in metadata.get("timezone_columns", {}).items():
        if column in frame:
            frame[column] = frame[column].dt.tz_convert(timezone)
    for column, dtype in metadata.get("datetime_columns", {}).items():
        if column in frame:
            frame[column] = frame[column].astype(dtype)
    return frame, metadata


def matches_frame_hash(path: str | Path, expected: str) -> bool:
    if not expected:
        return False
    path = promote_frame(path)
    return expected == file_sha256(path) or expected == frame_metadata(path).get("legacy_sha256")
