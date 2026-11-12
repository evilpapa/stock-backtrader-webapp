"""将本地分钟因子与历史竞价、资格和收益合并，输出周度截面研究。"""
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


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8*1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',required=True);p.add_argument('--end',required=True)
    p.add_argument('--factor-dir',type=Path,default=Path('data/intraday_factors/local_minute_factors'))
    p.add_argument('--auction-dir',type=Path,default=Path('data/intraday_factors/auction_history/daily'))
    p.add_argument('--coverage',type=Path,default=Path('examples/intraday_factors/auction_history/coverage.parquet'))
    p.add_argument('--output-dir',type=Path,default=Path('examples/intraday_factors/local_minute_research'))
    args=p.parse_args(); start=pd.Timestamp(args.start);end=pd.Timestamp(args.end)
    if start>end: p.error('开始日期晚于结束日期')
    cov=pd.read_parquet(args.coverage);cov['date']=pd.to_datetime(cov.date).dt.normalize()
    if cov.duplicated(['symbol','date']).any():raise ValueError('资格数据存在重复证券日')
    # 给滚动窗口和远期持有期保留交易日，不凭空填充因子。
    cov=cov[cov.date.between(start-pd.Timedelta(days=14),end+pd.Timedelta(days=14))].copy()
    calendar=pd.DatetimeIndex(sorted(cov.date.unique()))
    if calendar.empty or calendar.max() < end:raise ValueError('资格数据不覆盖研究终点')
    snapshots=Path('data/intraday_factors/csi500/snapshots.parquet')
    symbols=sorted(pd.read_parquet(snapshots).con_code.dropna().unique().tolist())
    symbol_hash=hashlib.sha256('\n'.join(symbols).encode()).hexdigest()
    impl=sha('src/strategy/intraday_factors.py');builder=sha('scripts/build_local_minute_factors.py')
    repo=sha('src/datahub/local_minute_repository.py');snap=sha(snapshots);auction_impl=sha('src/strategy/auction_factors.py')
    minutes=[];auctions=[];versions=[]
    for day in calendar[calendar<=end]:
        key=day.strftime('%Y%m%d');path=args.factor_dir/(key+'.parquet');meta_path=path.with_suffix('.json')
        if not path.exists() or not meta_path.exists():raise ValueError(f'缺少分钟因子 {key}')
        m=json.loads(meta_path.read_text()); f=pd.read_parquet(path)
        if (m.get('output_sha256')!=sha(path) or m.get('implementation_sha256')!=impl or m.get('builder_sha256')!=builder or m.get('repository_sha256')!=repo or m.get('snapshot_sha256')!=snap or m.get('symbols')!=symbols or len(f)!=m.get('rows') or not pd.to_datetime(f.date).eq(day).all()):
            raise ValueError(f'分钟因子来源、日期或版本异常 {key}')
        minutes.append(f); versions.append({'date':key,'input_sha256':m['input_sha256'],'output_sha256':m['output_sha256']})
        ap=args.auction_dir/(key+'.parquet');am=ap.with_suffix('.json')
        if not ap.exists() or not am.exists():raise ValueError(f'缺少竞价因子 {key}')
        info=json.loads(am.read_text()); af=pd.read_parquet(ap)
        if len(af)!=info.get('rows') or info.get('symbols_sha256')!=symbol_hash or info.get('implementation_sha256')!=auction_impl or not pd.to_datetime(af.date).eq(day).all():raise ValueError(f'竞价因子版本或日期异常 {key}')
        auctions.append(af[['symbol','date']+FACTOR_COLUMNS])
    minute=pd.concat(minutes,ignore_index=True); auction=pd.concat(auctions,ignore_index=True)
    minute['date']=pd.to_datetime(minute.date).dt.normalize();auction['date']=pd.to_datetime(auction.date).dt.normalize()
    if minute.duplicated(['symbol','date']).any() or auction.duplicated(['symbol','date']).any():raise ValueError('因子证券日重复')
    panel=cov[['symbol','date','eligible','forward_return','auction_open']].rename(columns={'auction_open':'open_proxy'})
    panel=panel.merge(minute,on=['symbol','date'],how='left',validate='one_to_one').merge(auction,on=['symbol','date'],how='left',validate='one_to_one')
    weekly=weekly_research(panel,calendar,eligibility_column='eligible',returns_column='forward_return')
    if weekly.empty:raise ValueError('没有可计算的周度截面')
    weekly=weekly[weekly.signal_date.between(start,end)].copy()
    bench=pd.read_parquet('data/micro_cap_timing_plus/reference/index_000905.SH.parquet')
    bench['date']=pd.to_datetime(bench.trade_date.astype(str),format='%Y%m%d');index_open=bench.set_index('date').open
    weekly['benchmark_return']=weekly.exit_date.map(index_open).div(weekly.entry_date.map(index_open)).sub(1)
    summary=weekly.groupby('factor',as_index=False).agg(weeks=('rank_ic','count'),mean_rank_ic=('rank_ic','mean'),median_n=('n','median'),mean_low=('group_1','mean'),mean_high=('group_10','mean'),mean_benchmark=('benchmark_return','mean'))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    weekly.to_csv(args.output_dir/'weekly_research.csv',index=False);summary.to_csv(args.output_dir/'factor_summary.csv',index=False)
    manifest={'start':args.start,'end':args.end,'minute_stock_days':len(minute),'factors':len(summary),'weekly_records':len(weekly),'daily_inputs':versions,
              'coverage_sha256':sha(args.coverage),'snapshot_sha256':snap,
              'limitations':'月末权重快照滞后31天近似历史成分；分钟复权、时间标签和供应商未完全核实；竞价数据可能不完整；收益使用公司行为近似，未来缺价被排除；不含交易约束、成本和滑点，不是可交易净值。'}
    (args.output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('分钟股票日',len(minute),'因子',len(summary),'周记录',len(weekly),flush=True)

if __name__=='__main__':main()
