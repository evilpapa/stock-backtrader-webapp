"""只读的本地集合竞价 Tick Repository；字段保持供应商原始口径。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
from .models import DataKind, DataRequest, DataResult


class AuctionTickRepository:
    source = 'auction_tick_parquet'

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def query(self, data_kind: DataKind | str, request: DataRequest, *, source: str | None = None) -> DataResult | None:
        if DataKind(data_kind) != DataKind.TICK or (source and source != self.source):
            raise ValueError('仅支持本地集合竞价 Tick')
        if request.start is None or request.end is None or request.frequency != 'tick' or str(request.adjust) != 'none':
            raise ValueError('需要明确指定日期范围、tick 频率及 none 复权')
        start, end = pd.Timestamp(request.start), pd.Timestamp(request.end)
        if start.normalize() != end.normalize() or start != start.normalize() or end != end.normalize():
            raise ValueError('每次请求必须为单个自然日，且不能包含日内时间')
        day = start.strftime('%Y%m%d')
        path = self.root / day[:4] / day[4:6] / f'{day}.parquet'
        info = path.with_suffix('.json')
        if not path.exists() or not info.exists():
            return None
        manifest = json.loads(info.read_text(encoding='utf-8'))
        parquet = pq.ParquetFile(path)
        metadata = parquet.schema_arrow.metadata or {}
        if (manifest.get('date') != day or manifest.get('rows') != parquet.metadata.num_rows
                or metadata.get(b'archive_sha256', b'').decode() != manifest.get('archive_sha256')):
            raise ValueError(f'集合竞价分区与来源记录不一致: {path}')
        filters = [('security_id', 'in', list(request.symbols))] if request.symbols else None
        frame = pq.read_table(path, filters=filters).to_pandas()
        version = hashlib.sha256((manifest['archive_sha256'] + ':' + day + ':' + str(manifest['version'])).encode()).hexdigest()[:20]
        details = {'source':self.source, 'frequency':'tick', 'adjust':'none', 'data_version':version,
                   'storage':'parquet', 'date':day, 'source_archive':manifest['archive'],
                   'source_member':manifest['member'], 'archive_sha256':manifest['archive_sha256'],
                   'timestamp_semantics':'snapshot', 'price_adjust':'unknown', 'volume_unit':'provider_raw'}
        frame.attrs.update(details)
        return DataResult(frame, self.source, DataKind.TICK, request.request_id, metadata=details)

    def save(self, result, request):
        raise NotImplementedError('原始行情仓库只读')

    def close(self):
        pass
