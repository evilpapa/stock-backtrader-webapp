"""历史动态中证500快照的集合竞价因子截面研究（不是可成交回测）。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import create_service, DataRequest
from src.datahub.duckdb_frames import file_sha256, frame_exists, promote_frame, read_frame, write_frame
from src.datahub.models import DataKind
from src.datahub.research_daily_repository import ResearchDailyRepository
from src.datahub.service import MarketDataService
from src.datahub.router import DataRouter
from src.strategy.auction_factors import FACTOR_COLUMNS
from src.strategy.intraday_factor_research import weekly_research
from src.strategy.intraday_artifacts import load_factors


def adjust_open_returns(quotes: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """用 Tushare 前收与上一成交日收盘的比值近似处理除权，按交易日计算 T+1 至 T+6 收益。"""
    q = quotes.sort_values(['symbol', 'date']).copy()
    for c in ['close', 'pre_close', 'open_proxy']:
        q[c] = pd.to_numeric(q[c], errors='coerce')
    prior = q.groupby('symbol', sort=False).close.shift()
    prev_valid = np.isfinite(prior) & (prior > 0)
    today_valid = np.isfinite(q.pre_close) & (q.pre_close > 0)
    q['bad_event'] = prev_valid & ~today_valid
    q['ratio'] = (prior / q.pre_close).where(prev_valid & today_valid, 1.0)
    q['scale'] = q.groupby('symbol', sort=False).ratio.cumprod()
    q['bad_count'] = q.groupby('symbol', sort=False).bad_event.cumsum()
    q['adj_open'] = q.open_proxy * q.scale
    index = pd.MultiIndex.from_product([q.symbol.unique(), days], names=['symbol', 'date'])
    panel = q.set_index(['symbol', 'date'])[['adj_open', 'bad_count']].reindex(index)
    by = panel.groupby(level='symbol', sort=False)
    entry = by.adj_open.shift(-1);
    exit_price = by.adj_open.shift(-6)
    # 无行情日继承最近已知的公司行为校验状态，不凭空生成开盘价。
    bad = by.bad_count.ffill().groupby(level='symbol', sort=False)
    entry_bad = bad.shift(-1);
    exit_bad = bad.shift(-6)
    returns = exit_price.div(entry).sub(1).where(entry_bad.eq(exit_bad))
    returns = returns.where(np.isfinite(returns) & entry.gt(0) & exit_price.gt(0))
    return returns.rename('forward_return').reset_index()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2021-01-04');
    p.add_argument('--end', default='2026-02-27')
    p.add_argument('--snapshots', type=Path, default=Path('data/intraday_factors/csi500/snapshots.duckdb'))
    p.add_argument('--factor-dir', type=Path, default=Path('data/intraday_factors/auction_history/daily'))
    p.add_argument('--reference-dir', type=Path, default=Path('data/micro_cap_timing_plus'))
    p.add_argument('--output-dir', type=Path, default=Path('examples/intraday_factors/auction_history'))
    p.add_argument('--snapshot-lag-days', type=int, default=31)
    args = p.parse_args()
    if args.snapshot_lag_days < 1: raise ValueError('快照滞后至少一天')
    snapshots = promote_frame(args.snapshots)
    snap = read_frame(snapshots)
    snap['snapshot_date'] = pd.to_datetime(snap.trade_date.astype(str), format='%Y%m%d')
    symbols = tuple(sorted(snap.con_code.unique()))
    symbols_hash = hashlib.sha256('\n'.join(symbols).encode()).hexdigest()
    implementation_hash = hashlib.sha256(Path('src/strategy/auction_factors.py').read_bytes()).hexdigest()
    snap['available_date'] = snap.snapshot_date + pd.to_timedelta(args.snapshot_lag_days, unit='D')
    availability = snap[['snapshot_date', 'available_date']].drop_duplicates().sort_values('available_date')
    if availability.available_date.duplicated().any(): raise ValueError('快照可用日重复')
    service = create_service()
    try:
        cal = service.get_trade_calendar(
            DataRequest(start=args.start, end=args.end, exchange='SSE', options={'is_open': '1'}))
    finally:
        service.close()
    if cal.empty or cal.attrs.get('source') != 'tushare': raise ValueError('日历异常')
    days = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.astype(str).eq('1'), 'trade_date'])).sort_values()
    day_snapshot = pd.merge_asof(pd.DataFrame({'date': days}), availability, left_on='date', right_on='available_date',
                                 direction='backward')
    last_snapshot = snap.snapshot_date.max()
    if days.max() > (last_snapshot + pd.offsets.MonthEnd(2)):
        raise ValueError('研究结束时间距最后一个快照超过两个月，避免无意使用过期股票池')
    pool = day_snapshot.dropna(subset=['snapshot_date']).merge(snap[['snapshot_date', 'con_code']], on='snapshot_date',
                                                               validate='many_to_many')
    pool = pool[['date', 'con_code']].rename(columns={'con_code': 'symbol'}).assign(in_pool=True)
    if pool.duplicated(['date', 'symbol']).any(): raise ValueError('股票池重复')
    repo = ResearchDailyRepository(args.reference_dir)
    local = MarketDataService(DataRouter({}), repository=repo)
    basic_result = local.get_cached(DataKind.STOCK_BASIC, DataRequest())
    if basic_result is None: raise ValueError('缺少证券基础信息')
    basic = basic_result[['ts_code', 'list_date', 'delist_date']].copy().rename(columns={'ts_code': 'symbol'})
    if basic.symbol.duplicated().any(): raise ValueError('股票基础信息代码重复')
    basic['list_date'] = pd.to_datetime(basic.list_date, format='%Y%m%d', errors='coerce')
    basic['delist_date'] = pd.to_datetime(basic.delist_date, format='%Y%m%d', errors='coerce')
    basics_hash = basic_result.attrs['data_version']
    factors = [];
    daily = [];
    sts = [];
    inputs = []
    for i, day in enumerate(days, 1):
        key = day.strftime('%Y%m%d');
        factor_path = args.factor_dir / (key + '.duckdb')
        info = args.factor_dir / (key + '.json')
        if not frame_exists(factor_path) or not info.exists(): raise ValueError(f'缺少竞价因子缓存 {key}')
        f, meta = load_factors(factor_path, day, list(symbols), args.snapshots, auction=True)
        req = DataRequest(symbols=symbols, start=day, end=day, frequency='1d', adjust='none')
        quote = local.get_cached(DataKind.DAILY_BULK, req);
        st = local.get_cached(DataKind.ST, req)
        if quote is None or st is None: raise ValueError(f'缺少日线或ST缓存 {key}')
        d = quote[['ts_code', 'open', 'close', 'pre_close', 'vol']].rename(
            columns={'ts_code': 'symbol', 'open': 'daily_open'}).assign(date=day)
        if d.symbol.duplicated().any(): raise ValueError(f'日线证券代码重复 {key}')
        x = st[['ts_code']].rename(columns={'ts_code': 'symbol'}).assign(date=day, is_st=True)
        if x.symbol.duplicated().any(): raise ValueError(f'ST证券代码重复 {key}')
        factors.append(f);
        daily.append(d);
        sts.append(x)
        inputs.append(
            {'date': key, 'auction_version': meta['auction_data_version'], 'daily_sha256': quote.attrs['data_version'],
             'st_sha256': st.attrs['data_version']})
        if i % 100 == 0 or i == len(days): print(f'读取 {i}/{len(days)} 日', flush=True)
    factor = pd.concat(factors, ignore_index=True);
    factor['date'] = pd.to_datetime(factor.date)
    quote = pd.concat(daily, ignore_index=True);
    st = pd.concat(sts, ignore_index=True)
    merged = quote.merge(factor, on=['symbol', 'date'], how='left', validate='one_to_one').merge(pool,
                                                                                                 on=['symbol', 'date'],
                                                                                                 how='left',
                                                                                                 validate='one_to_one').merge(
        st, on=['symbol', 'date'], how='left', validate='one_to_one').merge(basic, on='symbol', how='left',
                                                                            validate='many_to_one')
    matched = merged.auction_open.notna() & (merged.auction_open > 0) & (merged.daily_open > 0) & (
                (merged.auction_open - merged.daily_open).abs() < 0.0051)
    pre_ok = merged.auction_pre_close.notna() & (merged.auction_pre_close > 0) & (merged.pre_close > 0) & (
                (merged.auction_pre_close - merged.pre_close).abs() < 0.0051)
    listed = merged.list_date.notna() & (merged.date >= merged.list_date + pd.DateOffset(years=1)) & (
                merged.delist_date.isna() | (merged.date < merged.delist_date))
    traded = merged.vol.notna() & (merged.vol > 0)
    merged['listed_one_year'] = listed
    merged['signal_traded'] = traded
    merged['open_match'] = matched
    merged['pre_close_match'] = pre_ok
    merged['eligible'] = merged.in_pool.eq(True) & ~merged.is_st.eq(True) & listed & traded & matched & pre_ok
    merged['open_proxy'] = merged.auction_open.where(matched & traded)
    returns = adjust_open_returns(merged[['symbol', 'date', 'close', 'pre_close', 'open_proxy']], days)
    merged = merged.merge(returns, on=['symbol', 'date'], how='left', validate='one_to_one')
    research = merged[['symbol', 'date', 'open_proxy', 'eligible', 'forward_return'] + FACTOR_COLUMNS].copy()
    weekly = weekly_research(research, days, eligibility_column='eligible', returns_column='forward_return')
    # 指数只是参考，不具备可交易性；使用同一持有期的指数开盘到开盘收益。
    index_path = args.reference_dir / 'reference' / 'index_000905.SH.duckdb'
    benchmark = read_frame(index_path)
    benchmark['date'] = pd.to_datetime(benchmark.trade_date.astype(str), format='%Y%m%d')
    if benchmark.date.duplicated().any(): raise ValueError('指数行情日期重复')
    index_open = benchmark.set_index('date')['open']
    if not weekly.empty:
        a = weekly.entry_date.map(index_open);
        b = weekly.exit_date.map(index_open)
        weekly['benchmark_return'] = (b / a - 1).where(a.gt(0) & b.gt(0))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    weekly.to_csv(args.output_dir / 'weekly_research.csv', index=False)
    write_frame(args.output_dir / 'coverage.duckdb', merged[['symbol', 'date', 'in_pool', 'is_st', 'eligible', 'daily_open', 'auction_open', 'pre_close',
            'auction_pre_close', 'vol', 'listed_one_year', 'signal_traded', 'open_match', 'pre_close_match',
            'forward_return']])
    day_snapshot.to_csv(args.output_dir / 'universe_snapshots.csv', index=False)
    summary = weekly.groupby('factor', as_index=False).agg(weeks=('rank_ic', 'count'), mean_rank_ic=('rank_ic', 'mean'),
                                                           median_n=('n', 'median'), mean_low=('group_1', 'mean'),
                                                           mean_high=('group_10', 'mean'),
                                                           mean_benchmark=('benchmark_return', 'mean'))
    summary.to_csv(args.output_dir / 'factor_summary.csv', index=False)
    manifest = {'start': args.start, 'end': args.end, 'calendar_source': cal.attrs.get('source'),
                'calendar_data_version': cal.attrs.get('data_version'),
                'snapshot_file': str(snapshots),
                'snapshot_sha256': file_sha256(snapshots),
                'snapshot_lag_days': args.snapshot_lag_days,
                'pool_rule': '最近一个快照日期至少滞后31自然日；发布时点未核实，月度近似', 'symbols_union': len(symbols),
                'auction_factor_implementation_sha256': implementation_hash,
                'basic_file': str(basic_result.attrs['path']),
                'basic_sha256': basics_hash, 'dates': len(days), 'eligible_stock_days': int(merged.eligible.sum()),
                'weekly_rows': len(weekly),
                'signal_dates': int(weekly.signal_date.nunique()) if not weekly.empty else 0,
                'open_matches': int(matched.sum()),
                'open_compared': int((merged.auction_open.notna() & merged.daily_open.notna()).sum()),
                'pre_close_matches': int(pre_ok.sum()),
                'pre_close_compared': int((merged.auction_pre_close.notna() & merged.pre_close.notna()).sum()),
                'factor_rule': '阶段至少2个有效快照，价格等于买一及卖一并在有效限价之内，快照可能遗漏极值。',
                'return_rule': 'T+1开盘到T+6开盘，使用上次成交日收盘/当日参考前收累乘估算除权；不足以取代复权因子和公司行为现金账。',
                'limitations': 'ST、上市一年、信号日有成交已筛；月度快照非精确历史成分、滞后不是已验证发布时间；价格口径待核验；未来缺价股票不参与收益统计；涨跌停、成交、滑点、交易成本、印花税及持仓现金行为未建模，不是策略净值。',
                'daily_source_versions': inputs}
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
                                                   encoding='utf-8')
    print(summary.to_string(index=False));
    print('信号周', manifest['signal_dates'], '合格股票日', manifest['eligible_stock_days'])


if __name__ == '__main__': main()
