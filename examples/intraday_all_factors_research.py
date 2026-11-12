"""合并分钟及竞价日因子，计算动态中证500近似股票池的周度截面统计。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.strategy.auction_factors import FACTOR_COLUMNS
from src.strategy.intraday_factor_research import weekly_research


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2025-11-01')
    p.add_argument('--end', default='2026-02-27')
    p.add_argument('--minute-factor-dir', type=Path, default=Path('data/intraday_factors/minute_factors'))
    p.add_argument('--minute-dir', type=Path, default=Path('data/intraday_factors/minute_history'))
    p.add_argument('--auction-dir', type=Path, default=Path('data/intraday_factors/auction_history/daily'))
    p.add_argument('--coverage', type=Path, default=Path('examples/intraday_factors/auction_history/coverage.parquet'))
    p.add_argument('--output-dir', type=Path, default=Path('examples/intraday_factors/all_factors_history'))
    args = p.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if start > end:
        p.error('开始日期不得晚于结束日期')
    coverage = pd.read_parquet(args.coverage)
    coverage['date'] = pd.to_datetime(coverage.date).dt.normalize()
    # 日历多留一段，以便期末信号关联持有期；如来源数据不足则自动不输出该信号。
    coverage = coverage[coverage.date.between(start, end + pd.Timedelta(days=14))].copy()
    calendar = pd.DatetimeIndex(sorted(coverage.date.unique()))
    if calendar.empty or coverage.duplicated(['symbol','date']).any():
        raise ValueError('股票资格数据为空或证券日重复')
    records = []
    minute_implementation = sha(Path('src/strategy/intraday_factors.py'))
    snapshots = pd.read_parquet('data/intraday_factors/csi500/snapshots.parquet')
    expected_symbols = set(snapshots.con_code.dropna().unique())
    symbols_hash = hashlib.sha256('\n'.join(sorted(expected_symbols)).encode()).hexdigest()
    minute_versions = []
    for month in pd.period_range(start, end, freq='M'):
        directory = args.minute_factor_dir / str(month).replace('-', '')
        paths = sorted(directory.glob('*.parquet'))
        if not paths:
            raise ValueError(f'缺少月份因子批次: {month}')
        covered_symbols = set()
        month_start, month_end = max(start, month.start_time), min(end, month.end_time.normalize())
        for path in paths:
            meta_path = path.with_suffix('.json')
            if not meta_path.exists(): raise ValueError(f'缺少因子元信息: {path}')
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if meta.get('request_key') != path.stem:
                raise ValueError(f'因子请求键不一致: {path}')
            batch_symbols = set(meta['symbols'])
            if (covered_symbols & batch_symbols or pd.Timestamp(meta['start']) > month_start
                    or pd.Timestamp(meta['end']) < month_end):
                raise ValueError(f'分钟因子批次范围重复或时间不完整: {path}')
            covered_symbols.update(batch_symbols)
            source = args.minute_dir / path.parent.name / path.name
            if (not source.exists() or sha(source) != meta.get('input_sha256') or sha(path) != meta.get('output_sha256')
                    or meta.get('implementation_sha256') != minute_implementation):
                raise ValueError(f'分钟因子来源或实现校验失败: {path}')
            f = pd.read_parquet(path)
            if len(f) != meta['rows']: raise ValueError(f'分钟因子行数不一致: {path}')
            minute_versions.append({'batch':path.stem, 'month':path.parent.name,
                                    'input_sha256':meta['input_sha256'], 'output_sha256':meta['output_sha256']})
            if not f.empty: records.append(f)
        if covered_symbols != expected_symbols:
            raise ValueError(f'{month} 股票批次未完成: {len(covered_symbols)}/{len(expected_symbols)}')
    if not records: raise ValueError('分钟因子为空')
    minute = pd.concat(records, ignore_index=True)
    minute['date'] = pd.to_datetime(minute.date).dt.normalize()
    minute = minute[minute.date.between(start, end)]
    if minute.duplicated(['symbol','date']).any(): raise ValueError('分钟因子证券日重复，检查是否存在重叠批次')
    minute_cols = [c for c in minute.columns if c not in ('symbol','date')]
    if len(minute_cols) != 39 or set(minute_cols) & set(FACTOR_COLUMNS):
        raise ValueError('分钟因子字段不符合 39 因子口径')
    auction = []
    auction_versions = []
    for day in calendar[calendar <= end]:
        path = args.auction_dir / (day.strftime('%Y%m%d') + '.parquet')
        info = path.with_suffix('.json')
        if not path.exists() or not info.exists(): raise ValueError(f'缺少竞价因子: {day}')
        m = json.loads(info.read_text(encoding='utf-8'))
        f = pd.read_parquet(path)
        if (len(f) != m['rows'] or m.get('implementation_sha256') != sha(Path('src/strategy/auction_factors.py'))
                or m.get('symbols_sha256') != symbols_hash
                or not pd.to_datetime(f.date).eq(day).all()):
            raise ValueError(f'竞价因子版本或日期不一致: {path}')
        auction.append(f[['symbol','date'] + FACTOR_COLUMNS])
        auction_versions.append({'date':day.strftime('%Y%m%d'), 'auction_data_version':m.get('auction_data_version'), 'factor_sha256':sha(path)})
    auction = pd.concat(auction, ignore_index=True)
    auction['date'] = pd.to_datetime(auction.date).dt.normalize()
    panel = coverage[['symbol','date','eligible','forward_return','auction_open']].rename(columns={'auction_open':'open_proxy'})
    panel = panel.merge(auction, on=['symbol','date'], how='left', validate='one_to_one').merge(minute, on=['symbol','date'], how='left', validate='one_to_one')
    weekly = weekly_research(panel, calendar, eligibility_column='eligible', returns_column='forward_return')
    if weekly.empty: raise ValueError('无可计算的周度截面')
    weekly = weekly[weekly.signal_date <= end]
    benchmark = pd.read_parquet('data/micro_cap_timing_plus/reference/index_000905.SH.parquet')
    benchmark['date'] = pd.to_datetime(benchmark.trade_date.astype(str), format='%Y%m%d')
    index_open = benchmark.set_index('date').open
    weekly['benchmark_return'] = weekly.exit_date.map(index_open).div(weekly.entry_date.map(index_open)).sub(1)
    summary = weekly.groupby('factor',as_index=False).agg(weeks=('rank_ic','count'),mean_rank_ic=('rank_ic','mean'),median_n=('n','median'),mean_low=('group_1','mean'),mean_high=('group_10','mean'),mean_benchmark=('benchmark_return','mean'))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    weekly.to_csv(args.output_dir/'weekly_research.csv',index=False)
    summary.to_csv(args.output_dir/'factor_summary.csv',index=False)
    manifest = {'start':args.start,'end':args.end,'minute_stock_days':len(minute),'minute_symbols':int(minute.symbol.nunique()),
                'minute_first_date':str(minute.date.min().date()),'minute_last_date':str(minute.date.max().date()),
                'minute_factor_count':len(minute_cols),'auction_factor_count':len(FACTOR_COLUMNS),
                'minute_implementation_sha256':minute_implementation,'coverage_sha256':sha(args.coverage),
                'snapshot_sha256':sha(Path('data/intraday_factors/csi500/snapshots.parquet')),
                'benchmark_sha256':sha(Path('data/micro_cap_timing_plus/reference/index_000905.SH.parquet')),
                'minute_batches':minute_versions,'auction_days':auction_versions,
                'limitations':'历史成分使用滞后31自然日的月度快照代理，实际发布日期未知；分钟末时间语义未独立确认；收益为除权近似且未来缺价样本被排除；无成交约束、交易成本、滑点和完整公司行为，不是可交易净值。各因子有效样本可能不同。'}
    (args.output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('分钟股票日',len(minute),'因子',len(summary),'周记录',len(weekly))


if __name__ == '__main__': main()
