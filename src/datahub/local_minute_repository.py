"""只读本地逐年/逐日 Parquet 分钟数据，供 DataHub 研究使用。"""
from __future__ import annotations

import hashlib
from pathlib import Path
import duckdb
import pandas as pd

from .models import Adjust, BarTimestamp, DataKind, DataRequest, DataResult


class LocalMinuteRepository:
    source = 'local_minute_parquet'

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._versions: dict[Path, tuple[int, int, str]] = {}
        self.connection = duckdb.connect()
        self.connection.execute('SET threads=4')

    def _version(self, path: Path) -> str:
        st = path.stat()
        old = self._versions.get(path)
        if old and old[:2] == (st.st_size, st.st_mtime_ns):
            return old[2]
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        after = path.stat()
        if (st.st_size, st.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f'读取时源文件发生变化: {path}')
        version = digest.hexdigest()
        self._versions[path] = (st.st_size, st.st_mtime_ns, version)
        return version

    def query(self, kind: DataKind | str, request: DataRequest, *, source: str | None = None):
        if DataKind(kind) != DataKind.MINUTE or source not in (None, self.source):
            raise ValueError('不支持的数据类型或来源')
        if request.frequency != '1m' or request.adjust != Adjust.NONE or not request.symbols:
            raise ValueError('仅支持指定证券的不复权假设 1 分钟行情')
        if request.start is None or request.end is None:
            raise ValueError('必须指定单个交易日')
        day = pd.Timestamp(request.start).normalize()
        if pd.Timestamp(request.end).normalize() != day:
            raise ValueError('本地分钟仓库要求单日请求')
        annual = self.root / f'year={day.year}' / f'{day.year}.parquet'
        daily = self.root / f'year={day.year}' / f'month={day.month:02d}' / f'day={day.day:02d}' / f'{day:%Y%m%d}.parquet'
        if annual.is_file() and daily.is_file():
            raise ValueError(f'存在重叠的年度和日度文件: {day:%Y%m%d}')
        path = annual if annual.is_file() else daily
        if not path.is_file():
            return None
        version = self._version(path)
        start = day.strftime('%Y-%m-%d')
        end = (day + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        frame = self.connection.execute('''
            SELECT ts_code AS symbol, trade_time AS datetime, open, high, low, close,
                   vol AS volume, amount
            FROM read_parquet(?, hive_partitioning=false)
            WHERE trade_time >= ? AND trade_time < ? AND ts_code IN (SELECT unnest(?))
        ''', [str(path), start, end, list(request.symbols)]).df()
        frame['datetime'] = pd.to_datetime(frame['datetime'], errors='raise')
        frame = frame.sort_values(['symbol', 'datetime']).reset_index(drop=True)
        if frame.duplicated(['symbol', 'datetime']).any():
            raise ValueError(f'源行情存在重复证券时间戳: {day:%Y%m%d}')
        meta = {'source': self.source, 'path': str(path), 'data_version': version,
                'frequency': '1m', 'adjust': 'none_assumed', 'volume_unit': 'shares_assumed',
                'amount_unit': 'yuan_assumed', 'timestamp_semantics': 'end_assumed',
                'note': '原始供应商及复权方式未获确认；单位、标签与不复权日线及QMT抽样核对。'}
        frame.attrs.update(meta)
        return DataResult(frame, self.source, DataKind.MINUTE, request.request_id, BarTimestamp.END, meta)

    def save(self, result, request):
        raise NotImplementedError('原始分钟数据只读')

    def close(self):
        self.connection.close()
