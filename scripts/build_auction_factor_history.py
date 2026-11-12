"""从 DataHub 竞价快照仓库按交易日构建可恢复的日因子缓存。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.datahub import create_service,DataRequest
from src.datahub.models import DataKind
from src.datahub.auction_tick_repository import AuctionTickRepository
from src.datahub.service import MarketDataService
from src.datahub.router import DataRouter
from src.strategy.auction_factors import auction_daily_factors_vectorized


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',default='2021-01-04');p.add_argument('--end',default='2026-02-27')
    p.add_argument('--output-dir',type=Path,default=Path('data/intraday_factors/auction_history'))
    p.add_argument('--snapshots',type=Path,default=Path('data/intraday_factors/csi500/snapshots.parquet'))
    p.add_argument('--auction-dir',type=Path,default=Path('data/tick_auction_parquet'))
    args=p.parse_args()
    snapshot=pd.read_parquet(args.snapshots)
    symbols=tuple(sorted(snapshot.con_code.dropna().unique()))
    if not symbols:
        raise ValueError('股票池快照为空')
    symbols_hash=hashlib.sha256('\n'.join(symbols).encode()).hexdigest()
    implementation_hash=hashlib.sha256(Path('src/strategy/auction_factors.py').read_bytes()).hexdigest()
    service=create_service()
    try:cal=service.get_trade_calendar(DataRequest(start=args.start,end=args.end,exchange='SSE',options={'is_open':'1'}))
    finally:service.close()
    if cal.empty or cal.attrs.get('source')!='tushare':raise ValueError('交易日历为空或来源异常')
    days=pd.to_datetime(cal.loc[cal.is_open.astype(str).eq('1'),'trade_date']).sort_values()
    repo=AuctionTickRepository(args.auction_dir)
    local=MarketDataService(DataRouter({}),repository=repo)
    output=args.output_dir/'daily'
    output.mkdir(parents=True,exist_ok=True)
    for i,day in enumerate(days,1):
        key=day.strftime('%Y%m%d'); path=output/(key+'.parquet'); info=output/(key+'.json')
        result=local.get_cached(DataKind.TICK,DataRequest(symbols=symbols,start=day,end=day,frequency='tick',adjust='none'))
        if result is None or result.empty:
            raise ValueError(f'{key} 竞价分区缺失或股票池为空')
        if path.exists() or info.exists():
            if path.exists() and info.exists():
                meta=json.loads(info.read_text(encoding='utf-8'))
                if meta['symbols_sha256']==symbols_hash and meta['auction_data_version']==result.attrs['data_version'] and meta['version']==1 and meta.get('implementation_sha256')==implementation_hash:
                    if i%50==0:print(f'{i}/{len(days)} {key} 已缓存',flush=True)
                    continue
            raise ValueError(f'{key} 缓存存在但来源不匹配；请检查 {path} 和 {info}')
        f,q=auction_daily_factors_vectorized(result)
        data=f.merge(q[['symbol','date','auction_open','auction_pre_close','stage1_valid','stage2_valid']],on=['symbol','date'],validate='one_to_one')
        data.to_parquet(path,index=False)
        info.write_text(json.dumps({'version':1,'date':key,'rows':len(data),'symbols_sha256':symbols_hash,
                                   'auction_data_version':result.attrs['data_version'],'implementation_sha256':implementation_hash,
                                   'archive_sha256':result.attrs['archive_sha256'],'source':repo.source,
                                   'frequency':'tick','adjust':'none','quality_rule':'bid1=ask1=last, 限价内, 每阶段至少2条'},ensure_ascii=False,indent=2),encoding='utf-8')
        if i%25==0 or i==len(days):print(f'{i}/{len(days)} {key} 股票日 {len(data)}',flush=True)

if __name__=='__main__':main()
