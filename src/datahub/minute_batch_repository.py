"""Exact-request Parquet repository for large, resumable minute data pulls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from .models import BarTimestamp, DataKind, DataRequest, DataResult


class MinuteBatchRepository:
    """One immutable-in-purpose batch per request; empty batches remain refreshable."""
    def __init__(self, root: str | Path, *, source: str = 'xtquant'):
        if source not in ('xtquant', 'tushare'):
            raise ValueError('不支持的分钟数据来源')
        self.root = Path(root)
        self.source = source
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, request: DataRequest, source: str):
        key = request.cache_key(source)
        directory = self.root / str(pd.Timestamp(request.start).strftime('%Y%m'))
        return directory / (key + '.parquet'), directory / (key + '.json')

    def save(self, result: DataResult, request: DataRequest) -> str:
        if result.data_kind != DataKind.MINUTE or result.source != self.source:
            raise ValueError('分钟数据来源与仓库配置不符')
        path, meta = self._paths(request, result.source)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.parquet.tmp')
        result.data.to_parquet(temp, index=False)
        digest = hashlib.sha256(temp.read_bytes()).hexdigest()
        metadata = dict(result.metadata)
        metadata.update({'source': result.source, 'data_kind': result.data_kind.value,
                         'timestamp_semantics': result.timestamp_semantics.value,
                         'request_key': request.cache_key(result.source), 'symbols': list(request.symbols),
                         'start': str(request.start), 'end': str(request.end),
                         'frequency': request.frequency, 'adjust': request.adjust.value,
                         'fields': list(request.fields), 'options': dict(request.options),
                         'rows': len(result.data), 'parquet_sha256': digest})
        tmp_meta = meta.with_suffix('.json.tmp')
        tmp_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        os.replace(temp, path)
        os.replace(tmp_meta, meta)
        return str(metadata.get('data_version', digest))

    def query(self, kind: DataKind | str, request: DataRequest, *, source: str | None = None):
        if DataKind(kind) != DataKind.MINUTE or source not in (None, self.source):
            raise ValueError('分钟数据来源与仓库配置不符')
        path, meta = self._paths(request, self.source)
        if not path.exists() or not meta.exists():
            return None
        info = json.loads(meta.read_text(encoding='utf-8'))
        if info.get('request_key') != request.cache_key(self.source) or hashlib.sha256(path.read_bytes()).hexdigest() != info.get('parquet_sha256'):
            raise ValueError(f'分钟缓存校验失败: {path}')
        frame = pd.read_parquet(path)
        if len(frame) != info['rows']:
            raise ValueError(f'分钟缓存行数不一致: {path}')
        frame.attrs.update(info)
        return DataResult(frame, self.source, DataKind.MINUTE, request.request_id,
                          BarTimestamp(info['timestamp_semantics']), info)

    def close(self):
        pass
