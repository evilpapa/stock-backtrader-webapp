"""只读的本地集合竞价 Tick Repository；字段保持供应商原始口径。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.csv as csv
import pyarrow.parquet as pq
from .models import DataKind, DataRequest, DataResult

DEFAULT_AUCTION_DIR = Path('/data3/stock_data/stk_open_auction')
AUCTION_FIELDS = ['security_id', 'md_date', 'md_time', 'min', 'max', 'pre_close', 'last', 'open',
                  'num_trades', 'total_volume_trade', 'total_value_trade', 'bid1', 'bid2', 'bid_size1',
                  'bid_size2', 'ask1', 'ask2', 'ask_size1', 'ask_size2']
AUCTION_TYPES = dict.fromkeys(AUCTION_FIELDS, pa.float64())
AUCTION_TYPES.update(security_id=pa.string(), md_date=pa.int64(), md_time=pa.int64(), num_trades=pa.int64())


def normalize_auction_duplicates(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """只折叠所有字段完全相同的行；同一时间的冲突报价必须人工核查。"""
    keys = ['security_id', 'md_date', 'md_time']
    if not set(keys).issubset(frame.columns):
        raise ValueError('集合竞价原始分区缺少时间主键')
    cleaned = frame.drop_duplicates().copy()
    if cleaned.duplicated(keys).any():
        raise ValueError('集合竞价同一证券时间戳存在不同报价')
    return cleaned, len(frame) - len(cleaned)


class AuctionTickRepository:
    def __init__(self, root: str | Path = DEFAULT_AUCTION_DIR, *, storage: str = 'csv'):
        if storage not in {'csv', 'parquet'}:
            raise ValueError('仅支持 csv 或 parquet 竞价分区')
        self.root = Path(root)
        self.storage = storage
        self.source = f'auction_tick_{storage}'

    def csv_path(self, day: str) -> Path:
        return self.root / day[:6] / f'{day}.csv'

    def _read_csv(self, day: str, symbols: tuple[str, ...]):
        path = self.csv_path(day)
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return None
        table = csv.read_csv(pa.BufferReader(content), convert_options=csv.ConvertOptions(
            column_types=AUCTION_TYPES, strings_can_be_null=True))
        if table.column_names != AUCTION_FIELDS:
            raise ValueError(f'集合竞价 CSV 字段不一致: {path}')
        frame = table.to_pandas()
        keys = ['security_id', 'md_date', 'md_time']
        if frame.empty or frame[keys].isna().any().any() or not frame.md_date.eq(int(day)).all():
            raise ValueError(f'集合竞价 CSV 日期、主键或行数异常: {path}')
        digest = hashlib.sha256(content).hexdigest()
        if symbols:
            frame = frame[frame.security_id.isin(symbols)]
        version = hashlib.sha256(f'{digest}:auction_csv_v1'.encode()).hexdigest()[:20]
        return frame, version, {'source_path': str(path), 'source_csv_sha256': digest}

    def _read_parquet(self, day: str, symbols: tuple[str, ...]):
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
        filters = [('security_id', 'in', list(symbols))] if symbols else None
        frame = pq.read_table(path, filters=filters).to_pandas()
        version = hashlib.sha256((manifest['archive_sha256'] + ':' + day + ':' + str(manifest['version'])).encode()).hexdigest()[:20]
        return frame, version, {'source_archive': manifest['archive'], 'source_member': manifest['member'],
                                'archive_sha256': manifest['archive_sha256']}

    def query(self, data_kind: DataKind | str, request: DataRequest, *, source: str | None = None) -> DataResult | None:
        if DataKind(data_kind) != DataKind.TICK or (source and source != self.source):
            raise ValueError('仅支持本地集合竞价 Tick')
        if request.start is None or request.end is None or request.frequency != 'tick' or str(request.adjust) != 'none':
            raise ValueError('需要明确指定日期范围、tick 频率及 none 复权')
        start, end = pd.Timestamp(request.start), pd.Timestamp(request.end)
        if start.normalize() != end.normalize() or start != start.normalize() or end != end.normalize():
            raise ValueError('每次请求必须为单个自然日，且不能包含日内时间')
        day = start.strftime('%Y%m%d')
        raw = (self._read_csv if self.storage == 'csv' else self._read_parquet)(day, request.symbols)
        if raw is None:
            return None
        frame, version, provenance = raw
        frame, duplicates_removed = normalize_auction_duplicates(frame)
        if duplicates_removed:
            version = hashlib.sha256((version + ':dedup_exact_rows_v1').encode()).hexdigest()[:20]
        details = {'source':self.source, 'frequency':'tick', 'adjust':'none', 'data_version':version,
                   'storage':self.storage, 'date':day, **provenance,
                   'timestamp_semantics':'snapshot', 'price_adjust':'unknown', 'volume_unit':'provider_raw',
                   'duplicates_removed':duplicates_removed, 'duplicate_policy':'dedup_exact_rows_v1'}
        frame.attrs.update(details)
        return DataResult(frame, self.source, DataKind.TICK, request.request_id, metadata=details)

    def save(self, result, request):
        raise NotImplementedError('原始行情仓库只读')

    def close(self):
        pass
