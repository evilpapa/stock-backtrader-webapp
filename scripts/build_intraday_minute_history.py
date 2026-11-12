"""以固定快照或历史快照并集准备 XtQuant 分钟行情，可中断后续跑。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.minute_batch_repository import MinuteBatchRepository
from src.datahub.models import BarTimestamp, DataKind, DataResult
from src.datahub.router import RoutePolicy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2025-11-01')
    p.add_argument('--end', default='2026-02-27')
    p.add_argument('--snapshot', help='按指定月末快照选股，格式 YYYYMMDD；默认所有历史快照的并集')
    p.add_argument('--limit', type=int, help='仅处理排序后的前 N 只，用于试运行')
    p.add_argument('--batch-size', type=int, default=5)
    p.add_argument('--output-dir', type=Path, default=Path('data/intraday_factors/minute_history'))
    p.add_argument('--refresh', action='store_true', help='重新拉取已缓存批次（包括空批次）')
    p.add_argument('--download', action='store_true', help='请求 QMT 下载缺失历史；需终端具备下载通道')
    args = p.parse_args()
    if args.batch_size < 1 or (args.limit is not None and args.limit < 1) or pd.Timestamp(args.start) > pd.Timestamp(args.end):
        p.error('日期范围、批量和数量必须有效')
    snapshots = pd.read_parquet('data/intraday_factors/csi500/snapshots.parquet')
    if args.snapshot:
        snapshots = snapshots[snapshots.trade_date.astype(str).eq(args.snapshot)]
    symbols = sorted(snapshots.con_code.dropna().unique().tolist())
    if args.limit:
        symbols = symbols[:args.limit]
    if not symbols:
        p.error('没有找到股票')
    service = create_service(repository=MinuteBatchRepository(args.output_dir))
    service.router.policies[DataKind.MINUTE] = RoutePolicy(('xtquant',), fallback_on_empty=False)
    try:
        for month in pd.period_range(args.start, args.end, freq='M'):
            start = max(pd.Timestamp(args.start), month.start_time).strftime('%Y%m%d')
            end = min(pd.Timestamp(args.end), month.end_time.normalize()).strftime('%Y%m%d') + '235959'
            for offset in range(0, len(symbols), args.batch_size):
                batch = tuple(symbols[offset:offset + args.batch_size])
                request = DataRequest(symbols=batch, start=start, end=end, frequency='1m', adjust='none',
                                      options={'download': args.download, 'fill_data': False})
                cached = service.get_cached(DataKind.MINUTE, request, source='xtquant')
                bars = None if args.refresh else cached
                state = '缓存'
                if bars is None:
                    bars = service.get_minute(request, use_cache=False)
                    if bars.attrs.get('source') != 'xtquant':
                        raise ValueError('分钟行情来源不是 XtQuant')
                    if cached is not None and not cached.empty and bars.empty:
                        raise ValueError('刷新结果为空，保留原有非空缓存')
                    result = DataResult(bars, 'xtquant', DataKind.MINUTE, request.request_id,
                                        BarTimestamp(bars.attrs['timestamp_semantics']), dict(bars.attrs))
                    service.repository.save(result, request)
                    state = '获取'
                if bars.attrs.get('source') != 'xtquant':
                    raise ValueError('分钟行情来源不是 XtQuant')
                counts = bars.groupby('symbol').size().to_dict() if not bars.empty else {}
                print(f'{month} {min(offset + len(batch), len(symbols))}/{len(symbols)} {state} 行数={len(bars)} 有数据股票={len(counts)}', flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    main()
