"""本地 QMT 分钟缓存 + Tushare 日历的周频因子研究演示。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.storage import SQLiteRepository
from src.datahub.models import DataKind
from src.datahub.router import RoutePolicy
from src.strategy.intraday_factors import daily_factors
from src.strategy.intraday_factor_research import weekly_research


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2026-01-05')
    parser.add_argument('--end', default='2026-01-30')
    parser.add_argument('--snapshot', default='20251231')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--output-dir', type=Path, default=Path('examples/intraday_factors/weekly_sample'))
    args = parser.parse_args()
    if args.limit < 10 or pd.Timestamp(args.snapshot) >= pd.Timestamp(args.start):
        parser.error('limit 至少为 10，快照日期必须早于研究开始日期')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = pd.read_parquet('data/intraday_factors/csi500/snapshots.parquet')
    symbols = sorted(snapshot.loc[snapshot.trade_date.astype(str).eq(args.snapshot), 'con_code'].unique())[:args.limit]
    if not symbols:
        raise ValueError('没有找到指定日期的快照')
    repo = SQLiteRepository(args.output_dir / 'datahub.sqlite')
    service = create_service(repository=repo)
    try:
        cal = service.get_trade_calendar(DataRequest(start=args.start, end=args.end, exchange='SSE', options={'is_open':'1'}), persist=True)
        calendar = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.astype(str).eq('1'), 'trade_date']))
        if len(calendar) == 0:
            raise ValueError('交易日历为空')
        service.router.policies[DataKind.MINUTE] = RoutePolicy(('xtquant',), fallback_on_empty=False)
        daily, metadata = [], []
        months = pd.period_range(args.start, args.end, freq='M')
        for month in months:
            begin = max(pd.Timestamp(args.start), month.start_time)
            end = min(pd.Timestamp(args.end), month.end_time.normalize())
            for start in range(0, len(symbols), 5):
                batch = symbols[start:start + 5]
                req = DataRequest(symbols=tuple(batch), start=begin.strftime('%Y%m%d'), end=end.strftime('%Y%m%d')+'235959', frequency='1m', adjust='none', options={'download':False, 'fill_data':False})
                bars = service.get_minute(req, persist=True)
                if bars.attrs.get('source') != 'xtquant':
                    raise ValueError('分钟行情来源不是 XtQuant')
                metadata.append({'start':str(begin.date()), 'end':str(end.date()), 'symbols':batch, 'rows':len(bars), **{k:bars.attrs.get(k) for k in ('source','frequency','adjust','data_version','timestamp_semantics')}})
                if not bars.empty:
                    bars['datetime'] = pd.to_datetime(bars['datetime'])
                    if bars['datetime'].dt.tz is not None:
                        bars['datetime'] = bars['datetime'].dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
                    factors = daily_factors(bars)
                    minute = bars.datetime.dt.hour * 60 + bars.datetime.dt.minute
                    first = bars.loc[minute.eq(571)].copy()
                    first['date'] = first.datetime.dt.normalize()
                    first = first[['symbol','date','open']].rename(columns={'open':'open_proxy'})
                    if not factors.empty:
                        daily.append(factors.merge(first, on=['symbol','date'], validate='one_to_one'))
                print(f'{month} 完成 {min(start+5,len(symbols))}/{len(symbols)} 股票，分钟行数 {len(bars)}', flush=True)
        if not daily:
            raise ValueError('没有完整交易日分钟数据')
        data = pd.concat(daily, ignore_index=True)
        results = weekly_research(data, calendar)
        data.to_parquet(args.output_dir / 'daily_factors.parquet', index=False)
        results.to_csv(args.output_dir / 'weekly_research.csv', index=False)
        manifest = {'start':args.start, 'end':args.end, 'snapshot':args.snapshot, 'requested_symbols':symbols,
                    'stocks_with_complete_day':int(data.symbol.nunique()), 'complete_stock_days':len(data),
                    'calendar_source':cal.attrs.get('source'), 'calendar_data_version':cal.attrs.get('data_version'),
                    'minute_batches':metadata, 'adjust':'none', 'bar_time':'end', 'download':False, 'fill_data':False,
                    'limitations':'月末快照近似股票池、发布时间未知；未过滤 ST/上市年限/涨跌停；未处理分红复权、成本及可成交性；首分钟开盘价为代理价；仅毛收益研究。'}
        (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(f'完整股票日 {len(data)}，周频因子记录 {len(results)}')
    finally:
        service.close()


if __name__ == '__main__':
    main()
