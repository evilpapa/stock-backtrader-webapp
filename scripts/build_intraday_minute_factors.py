"""从 DataHub 分钟批次缓存构建 39 个日因子，按请求批次保存并校验来源。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.minute_batch_repository import MinuteBatchRepository
from src.datahub.models import DataKind
from src.strategy.intraday_factors import daily_factors


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2025-11-01')
    p.add_argument('--end', default='2025-11-30')
    p.add_argument('--snapshot')
    p.add_argument('--limit', type=int)
    p.add_argument('--batch-size', type=int, default=50)
    p.add_argument('--download', action='store_true')
    p.add_argument('--input-dir', type=Path, default=Path('data/intraday_factors/minute_history'))
    p.add_argument('--output-dir', type=Path, default=Path('data/intraday_factors/minute_factors'))
    args = p.parse_args()
    if pd.Timestamp(args.start) > pd.Timestamp(args.end) or args.batch_size < 1 or (args.limit is not None and args.limit < 1):
        p.error('日期或批量参数无效')
    snap = pd.read_parquet('data/intraday_factors/csi500/snapshots.parquet')
    if args.snapshot:
        snap = snap[snap.trade_date.astype(str).eq(args.snapshot)]
    symbols = sorted(snap.con_code.dropna().unique().tolist())[:args.limit]
    if not symbols:
        p.error('没有找到证券')
    implementation = digest(Path('src/strategy/intraday_factors.py'))
    service = create_service(repository=MinuteBatchRepository(args.input_dir))
    try:
        for month in pd.period_range(args.start, args.end, freq='M'):
            begin = max(pd.Timestamp(args.start), month.start_time).strftime('%Y%m%d')
            end = min(pd.Timestamp(args.end), month.end_time.normalize()).strftime('%Y%m%d') + '235959'
            for offset in range(0, len(symbols), args.batch_size):
                batch = tuple(symbols[offset:offset + args.batch_size])
                request = DataRequest(symbols=batch, start=begin, end=end, frequency='1m', adjust='none',
                                      options={'download':args.download, 'fill_data':False})
                bars = service.get_cached(DataKind.MINUTE, request, source='xtquant')
                if bars is None:
                    raise ValueError(f'缺少行情批次：{month} {offset + 1}-{offset + len(batch)}')
                source_hash = bars.attrs['parquet_sha256']
                directory = args.output_dir / str(month).replace('-', '')
                directory.mkdir(parents=True, exist_ok=True)
                key = request.cache_key('xtquant')
                path, meta = directory / (key + '.parquet'), directory / (key + '.json')
                if path.exists() and meta.exists():
                    info = json.loads(meta.read_text(encoding='utf-8'))
                    if (info.get('input_sha256') == source_hash and info.get('implementation_sha256') == implementation
                            and info.get('output_sha256') == digest(path)):
                        print(f'{month} {offset + len(batch)}/{len(symbols)} 缓存 股票日={info["rows"]}', flush=True)
                        continue
                factors = daily_factors(bars)
                tmp = path.with_suffix('.parquet.tmp')
                factors.to_parquet(tmp, index=False)
                info = {'request_key':key, 'input_sha256':source_hash, 'input_data_version':bars.attrs.get('data_version'),
                        'implementation_sha256':implementation, 'output_sha256':digest(tmp), 'rows':len(factors),
                        'symbols':list(batch), 'start':begin, 'end':end, 'source':'xtquant',
                        'frequency':'1m', 'adjust':'none', 'bar_time_assumption':'end',
                        'note':'仅完整 240 分钟股票日；时间语义未经独立核实，因子定义限制见研报复现说明。'}
                tmp_meta = meta.with_suffix('.json.tmp')
                tmp_meta.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
                os.replace(tmp, path)
                os.replace(tmp_meta, meta)
                print(f'{month} {offset + len(batch)}/{len(symbols)} 计算 股票日={len(factors)}', flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    main()
