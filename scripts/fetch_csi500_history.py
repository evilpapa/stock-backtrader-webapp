"""通过 DataHub 获取中证500月度成分权重，并记录快照间观察到的变化。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys
import time

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.models import DataKind
from src.datahub.storage import SQLiteRepository


def changes_between_snapshots(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    grouped = [(date, set(part['con_code'])) for date, part in frame.groupby('trade_date', sort=True)]
    for (previous_date, previous), (date, current) in zip(grouped, grouped[1:]):
        for event, symbols in (('observed_added', current - previous), ('observed_removed', previous - current)):
            rows.extend({'index_code': '000905.SH', 'con_code': symbol, 'previous_snapshot': previous_date,
                         'snapshot_date': date, 'event': event} for symbol in sorted(symbols))
    return pd.DataFrame(rows, columns=['index_code', 'con_code', 'previous_snapshot', 'snapshot_date', 'event'])


def has_monthly_coverage(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if frame.empty or 'trade_date' not in frame:
        return False
    dates = pd.to_datetime(frame['trade_date'].astype(str), format='%Y%m%d', errors='coerce')
    return set(pd.period_range(start, end, freq='M')).issubset(set(dates.dropna().dt.to_period('M')))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='20201201')
    parser.add_argument('--end', default='20260131')
    parser.add_argument('--output-dir', type=Path, default=Path('data/intraday_factors/csi500'))
    parser.add_argument('--delay', type=float, default=0.3)
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if start > end or args.delay < 0:
        parser.error('日期范围或请求间隔无效')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repo = SQLiteRepository(args.output_dir / 'index_weight.sqlite')
    service = create_service(repository=repo)
    collected, batches = [], []
    try:
        cursor = start
        while cursor <= end:
            batch_end = min(cursor + pd.offsets.QuarterEnd(), end)
            req = DataRequest(start=cursor.strftime('%Y%m%d'), end=batch_end.strftime('%Y%m%d'), options={'index_code':'000905.SH'})
            saved = repo.query(DataKind.INDEX_WEIGHT, req, source='tushare')
            if saved is not None and has_monthly_coverage(saved.data, cursor, batch_end):
                frame = saved.data
                origin = 'repository'
            else:
                frame = service.query(DataKind.INDEX_WEIGHT, req, persist=True)
                origin = 'tushare'
                time.sleep(args.delay)
            if frame.empty:
                raise RuntimeError(f'{req.start}–{req.end} 返回空快照，已保留此前批次缓存')
            required = {'index_code','con_code','trade_date','weight'}
            if not required.issubset(frame.columns) or not frame['index_code'].eq('000905.SH').all():
                raise ValueError(f'批次字段或指数代码异常: {req.start}–{req.end}')
            if frame.duplicated(['index_code','con_code','trade_date']).any():
                raise ValueError(f'快照存在重复证券: {req.start}–{req.end}')
            collected.append(frame)
            batches.append({'start':req.start,'end':req.end,'rows':len(frame),'read_from':origin,
                            'data_version':frame.attrs.get('data_version')})
            print(f'{req.start}..{req.end}: {len(frame)} 行 ({origin})', flush=True)
            cursor = batch_end + pd.Timedelta(days=1)
    finally:
        service.close()
    data = pd.concat(collected, ignore_index=True).sort_values(['trade_date','con_code']).reset_index(drop=True)
    if data.duplicated(['index_code','con_code','trade_date']).any():
        raise ValueError('合并快照存在重复记录')
    counts = data.groupby('trade_date')['con_code'].nunique()
    months = set(pd.PeriodIndex(pd.to_datetime(counts.index, format='%Y%m%d'), freq='M'))
    expected = set(pd.period_range(start, end, freq='M'))
    changes = changes_between_snapshots(data)
    data.to_parquet(args.output_dir / 'snapshots.parquet', index=False)
    changes.to_parquet(args.output_dir / 'observed_changes.parquet', index=False)
    manifest = {'source':'tushare', 'interface':'index_weight', 'index_code':'000905.SH',
                'retrieved_at':datetime.now().astimezone().isoformat(), 'start':args.start, 'end':args.end,
                'rows':len(data), 'unique_stocks':int(data.con_code.nunique()),
                'snapshot_count':len(counts), 'snapshot_dates':counts.index.tolist(),
                'constituent_counts':{str(k):int(v) for k,v in counts.items()},
                'missing_months':sorted(map(str, expected-months)), 'observed_changes':len(changes),
                'limitations':'月度成分权重快照；变化时间仅能限定在相邻快照之间，不能当作精确生效日；快照发布时点未确认。',
                'batches':batches}
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ('rows','unique_stocks','snapshot_count','missing_months','observed_changes')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
