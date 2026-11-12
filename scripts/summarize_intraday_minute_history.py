"""核对已缓存分钟行情的逐证券逐日覆盖；只读取本地 DataHub Repository。"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.models import DataKind
from src.datahub.minute_batch_repository import MinuteBatchRepository
from src.datahub.research_daily_repository import ResearchDailyRepository


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2025-11-01')
    p.add_argument('--end', default='2026-02-27')
    p.add_argument('--snapshot')
    p.add_argument('--limit', type=int)
    p.add_argument('--batch-size', type=int, default=5)
    p.add_argument('--download', action='store_true')
    p.add_argument('--output-dir', type=Path, default=Path('data/intraday_factors/minute_history'))
    p.add_argument('--report-dir', type=Path, help='覆盖报告目录，默认写入行情缓存目录')
    args = p.parse_args()
    snap = pd.read_parquet('data/intraday_factors/csi500/snapshots.parquet')
    if args.snapshot:
        snap = snap[snap.trade_date.astype(str).eq(args.snapshot)]
    symbols = sorted(snap.con_code.dropna().unique().tolist())[:args.limit]
    if not symbols or args.batch_size < 1:
        p.error('股票集合为空或批量无效')
    daily_root = Path('data/micro_cap_timing_plus')
    dates = sorted(pd.Timestamp(x.stem) for x in (daily_root / 'raw/daily').glob('*.parquet')
                   if len(x.stem) == 8 and x.stem.isdigit() and pd.Timestamp(args.start) <= pd.Timestamp(x.stem) <= pd.Timestamp(args.end))
    if not dates:
        raise ValueError('缺少日线缓存，无法计算覆盖')
    minute_service = create_service(repository=MinuteBatchRepository(args.output_dir))
    daily_service = create_service(repository=ResearchDailyRepository(daily_root))
    rows = []
    try:
        for month in pd.period_range(args.start, args.end, freq='M'):
            begin = max(pd.Timestamp(args.start), month.start_time)
            end = min(pd.Timestamp(args.end), month.end_time.normalize())
            month_dates = [d for d in dates if begin <= d <= end]
            traded = []
            for day in month_dates:
                req = DataRequest(symbols=tuple(symbols), start=day, end=day)
                daily = daily_service.get_cached(DataKind.DAILY_BULK, req, source='tushare_research_parquet')
                if daily is None:
                    raise ValueError(f'缺少日线 {day}')
                traded.append(pd.DataFrame({'symbol': daily.ts_code, 'date': day,
                                            'daily_traded': pd.to_numeric(daily.vol, errors='coerce').gt(0)}))
            daily_info = pd.concat(traded, ignore_index=True) if traded else pd.DataFrame(columns=['symbol', 'date', 'daily_traded'])
            for offset in range(0, len(symbols), args.batch_size):
                batch = symbols[offset:offset+args.batch_size]
                req = DataRequest(symbols=tuple(batch), start=begin.strftime('%Y%m%d'), end=end.strftime('%Y%m%d')+'235959',
                                  frequency='1m', adjust='none', options={'download':args.download, 'fill_data':False})
                bars = minute_service.get_cached(DataKind.MINUTE, req, source='xtquant')
                grid = pd.MultiIndex.from_product([batch, month_dates], names=['symbol','date']).to_frame(index=False)
                grid['batch_cached'] = bars is not None
                if bars is not None and not bars.empty:
                    bars = bars.copy()
                    bars['datetime'] = pd.to_datetime(bars.datetime).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
                    bars['date'] = bars.datetime.dt.normalize()
                    minute = bars.datetime.dt.hour * 60 + bars.datetime.dt.minute
                    bars = bars[((minute >= 571) & (minute <= 690)) | ((minute >= 781) & (minute <= 900))].copy()
                    price = pd.to_numeric(bars.close, errors='coerce')
                    volume = pd.to_numeric(bars.volume, errors='coerce')
                    bars['valid'] = np.isfinite(price) & price.gt(0) & np.isfinite(volume) & volume.ge(0)
                    bars['first_open_valid'] = minute.loc[bars.index].eq(571) & np.isfinite(pd.to_numeric(bars.open, errors='coerce')) & pd.to_numeric(bars.open, errors='coerce').gt(0)
                    grouped = bars.groupby(['symbol','date']).agg(bar_count=('datetime','size'), distinct_minutes=('datetime','nunique'), valid_count=('valid','sum'), first_open_valid=('first_open_valid','any')).reset_index()
                    grid = grid.merge(grouped, on=['symbol','date'], how='left')
                rows.append(grid.merge(daily_info, on=['symbol','date'], how='left'))
            print(f'{month} 覆盖汇总完成', flush=True)
        coverage = pd.concat(rows, ignore_index=True)
        for col in ['bar_count','distinct_minutes','valid_count']:
            if col not in coverage: coverage[col] = 0
            coverage[col] = coverage[col].fillna(0).astype(int)
        if 'first_open_valid' not in coverage: coverage['first_open_valid'] = False
        coverage['first_open_valid'] = coverage.first_open_valid.eq(True)
        coverage['complete_240'] = (coverage.bar_count.eq(240) & coverage.distinct_minutes.eq(240) & coverage.valid_count.eq(240) & coverage.first_open_valid)
        report_dir = args.report_dir or args.output_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        coverage.to_parquet(report_dir / 'coverage.parquet', index=False)
        summary = coverage.groupby(coverage.date.dt.to_period('M').astype(str)).agg(stock_days=('symbol','size'), traded_days=('daily_traded','sum'), batches_cached_days=('batch_cached','sum'), complete_days=('complete_240','sum')).reset_index().rename(columns={'date':'month'})
        summary.to_csv(report_dir / 'coverage_summary.csv', index=False)
        print(summary.to_string(index=False))
    finally:
        minute_service.close()
        daily_service.close()


if __name__ == '__main__': main()
