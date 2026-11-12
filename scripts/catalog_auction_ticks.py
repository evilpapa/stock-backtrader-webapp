"""核对已整理的竞价 Tick 逐日索引与 Tushare 上交所交易日历。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import pandas as pd
import pyarrow.parquet as pq
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path, default=Path('data/tick_auction_parquet'))
    p.add_argument('--start', default='20200101')
    p.add_argument('--end', default='20261031')
    args=p.parse_args()
    rows=[]
    for path in sorted(args.directory.glob('*/*/*.json')):
        if not re.fullmatch(r'\d{8}', path.stem):
            continue
        entry=json.loads(path.read_text(encoding='utf-8'))
        f=path.with_suffix('.parquet')
        metadata=pq.ParquetFile(f).metadata
        if entry['date'] != path.stem or entry['rows'] != metadata.num_rows:
            raise ValueError(f'文件日期或行数不一致：{path}')
        rows.append({**entry, 'parquet':str(f)})
    if not rows:
        raise ValueError('未找到日文件')
    frame=pd.DataFrame(rows).sort_values('date')
    if frame.date.duplicated().any():
        raise ValueError('发现重复日期')
    service=create_service()
    try:
        cal=service.get_trade_calendar(DataRequest(start=args.start, end=args.end, exchange='SSE', options={'is_open':'1'}))
        if cal.attrs.get('source') != 'tushare':
            raise ValueError('交易日历来源不是 Tushare')
        dates=set(pd.to_datetime(cal.loc[cal.is_open.astype(str).eq('1'),'trade_date']).dt.strftime('%Y%m%d'))
        calendar_version=cal.attrs.get('data_version')
    finally:
        service.close()
    observed=set(frame.date)
    frame.to_parquet(args.directory/'daily_index.parquet', index=False)
    manifest={'start':args.start, 'end':args.end, 'source_calendar':'tushare', 'calendar_data_version':calendar_version,
              'first_date':frame.date.min(), 'last_date':frame.date.max(), 'files':len(frame),
              'rows':int(frame.rows.sum()), 'parquet_bytes':int(frame.parquet_bytes.sum()),
              'months':int(frame.date.str[:6].nunique()), 'trading_days':len(dates),
              'missing_trading_dates':sorted(dates-observed), 'extra_dates':sorted(observed-dates),
              'limitations':'日历比较仅验证日期存在，不验证每只股票完整性、逐笔更新或行情准确性；保留原始数值，未进行有效报价筛选。'}
    (args.directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2,default=str))


if __name__=='__main__':
    main()
