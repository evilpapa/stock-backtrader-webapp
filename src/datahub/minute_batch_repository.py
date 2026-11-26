"""Exact-request DuckDB repository for large, resumable minute data pulls."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from .duckdb_frames import file_sha256, frame_exists, read_frame_with_metadata, write_frame
from .models import BarTimestamp, DataKind, DataRequest, DataResult


class MinuteBatchRepository:
    """One immutable-in-purpose batch per request; empty batches remain refreshable."""
    def __init__(self, root: str | Path, *, source: str = 'xtquant'):
        if source not in ('xtquant', 'tushare'):
            raise ValueError('不支持的分钟数据来源')
        self.root = Path(root)
        self.source = source
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, request: DataRequest, source: str):
        key = request.cache_key(source)
        directory = self.root / str(pd.Timestamp(request.start).strftime('%Y%m'))
        return directory / (key + '.duckdb')

    def save(self, result: DataResult, request: DataRequest) -> str:
        if result.data_kind != DataKind.MINUTE or result.source != self.source:
            raise ValueError('分钟数据来源与仓库配置不符')
        path = self._path(request, result.source)
        metadata = dict(result.metadata)
        metadata.update({'source': result.source, 'data_kind': result.data_kind.value,
                         'timestamp_semantics': result.timestamp_semantics.value,
                         'request_key': request.cache_key(result.source), 'symbols': list(request.symbols),
                         'start': str(request.start), 'end': str(request.end),
                         'frequency': request.frequency, 'adjust': request.adjust.value,
                         'fields': list(request.fields), 'options': dict(request.options),
                         'rows': len(result.data), 'storage': 'duckdb'})
        write_frame(path, result.data, metadata=metadata)
        return str(metadata.get('data_version') or file_sha256(path))

    def query(self, kind: DataKind | str, request: DataRequest, *, source: str | None = None):
        if DataKind(kind) != DataKind.MINUTE or source not in (None, self.source):
            raise ValueError('分钟数据来源与仓库配置不符')
        path = self._path(request, self.source)
        if not frame_exists(path):
            return None
        legacy = path.with_suffix('.parquet')
        sidecar = path.with_suffix('.json')
        old_info = None
        if not path.is_file():
            if not sidecar.is_file():
                return None
            old_info = json.loads(sidecar.read_text(encoding='utf-8'))
            if old_info.get('parquet_sha256') != file_sha256(legacy):
                raise ValueError(f'分钟缓存校验失败: {legacy}')
        try:
            frame, info = read_frame_with_metadata(path)
        except duckdb.Error as exc:
            raise ValueError(f'分钟缓存校验失败: {path}') from exc
        if 'legacy_sha256' in info:
            old_info = json.loads(sidecar.read_text(encoding='utf-8'))
            if old_info.get('parquet_sha256') != info['legacy_sha256']:
                raise ValueError(f'分钟缓存校验失败: {path}')
            info.update(old_info, storage='duckdb')
        elif not info and old_info is not None:
            info = old_info
        if info.get('request_key') != request.cache_key(self.source):
            raise ValueError(f'分钟缓存校验失败: {path}')
        if len(frame) != info['rows']:
            raise ValueError(f'分钟缓存行数不一致: {path}')
        if not info.get('data_version'):
            info['data_version'] = info.get('parquet_sha256') or file_sha256(path)
        frame.attrs.update(info)
        return DataResult(frame, self.source, DataKind.MINUTE, request.request_id,
                          BarTimestamp(info['timestamp_semantics']), info)

    def close(self):
        pass
