"""将本地竞价快照与既有分钟因子合并，执行周频截面研究。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.models import DataKind
from src.datahub.auction_tick_repository import AuctionTickRepository
from src.strategy.auction_factors import auction_daily_factors, FACTOR_COLUMNS
from src.strategy.intraday_factor_research import weekly_research
from src.strategy.auction_weekly_backtest import simulate_weekly


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minute-factors',type=Path,default=Path('examples/intraday_factors/weekly_quarter/daily_factors.parquet'))
    parser.add_argument('--auction-dir',type=Path,default=Path('data/tick_auction_parquet'))
    parser.add_argument('--output-dir',type=Path,default=Path('examples/intraday_factors/weekly_auction'))
    parser.add_argument('--min-observations',type=int,default=2)
    parser.add_argument('--backtest-factor',default='ret_open2AL1',choices=FACTOR_COLUMNS)
    parser.add_argument('--capital',type=float,default=1_000_000)
    args=parser.parse_args()
    minute=pd.read_parquet(args.minute_factors)
    if minute.empty or not {'symbol','date','open_proxy'}.issubset(minute):
        raise ValueError('分钟因子文件为空或缺少证券、日期、入场代理价格')
    minute['date']=pd.to_datetime(minute.date).dt.normalize()
    if minute.duplicated(['symbol','date']).any():
        raise ValueError('分钟因子有重复证券日期')
    start,end=minute.date.min(),minute.date.max()
    service=create_service()
    try:
        cal=service.get_trade_calendar(DataRequest(start=start,end=end,exchange='SSE',options={'is_open':'1'}))
    finally:
        service.close()
    if cal.empty or cal.attrs.get('source')!='tushare':
        raise ValueError('交易日历为空或来源不是 Tushare')
    calendar=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.astype(str).eq('1'),'trade_date']))
    repo=AuctionTickRepository(args.auction_dir)
    outputs, quality, versions, missing, empty_days = [], [], [], [], []
    for day in calendar:
        symbols=tuple(sorted(minute.loc[minute.date.eq(day),'symbol'].unique()))
        if not symbols:
            continue
        req=DataRequest(symbols=symbols,start=day,end=day,frequency='tick',adjust='none')
        result=repo.query(DataKind.TICK,req)
        if result is None:
            missing.append(day.strftime('%Y-%m-%d'))
            continue
        versions.append(result.metadata)
        if result.data.empty:
            empty_days.append(day.strftime('%Y-%m-%d'))
            continue
        f,q=auction_daily_factors(result.data,min_observations=args.min_observations)
        outputs.append(f)
        quality.append(q)
        if len(versions)%10==0:
            print(f'已读取 {len(versions)} 个交易日竞价分区',flush=True)
    if not outputs:
        raise ValueError('没有匹配的竞价快照')
    auction=pd.concat(outputs,ignore_index=True)
    qc=pd.concat(quality,ignore_index=True)
    data=minute.merge(auction,on=['symbol','date'],how='left',validate='one_to_one')
    data=data.drop(columns='open_proxy').merge(qc[['symbol','date','auction_open']],on=['symbol','date'],how='left',validate='one_to_one').rename(columns={'auction_open':'open_proxy'})
    qc=qc.merge(minute[['symbol','date','open_proxy']],on=['symbol','date'],how='left',validate='one_to_one')
    qc['open_minus_proxy']=qc.auction_open-qc.open_proxy
    weekly=weekly_research(data,calendar)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    data.to_parquet(args.output_dir/'daily_factors.parquet',index=False)
    qc.to_parquet(args.output_dir/'auction_quality.parquet',index=False)
    weekly.to_csv(args.output_dir/'weekly_research.csv',index=False)
    equity,trades=simulate_weekly(data,calendar,factor=args.backtest_factor,initial_cash=args.capital)
    equity.to_csv(args.output_dir/'illustrative_equity.csv',index=False)
    trades.to_csv(args.output_dir/'illustrative_trades.csv',index=False)
    manifest={'start':str(start.date()),'end':str(end.date()),'minute_factor_file':str(args.minute_factors),
              'minute_manifest':str(args.minute_factors.parent/'manifest.json'),
              'minute_factor_sha256':hashlib.sha256(args.minute_factors.read_bytes()).hexdigest(), 'auction_repository':str(args.auction_dir),
              'auction_source':'auction_tick_parquet','frequency':'tick','adjust':'none',
              'price_adjust':'unknown','calendar_source':cal.attrs.get('source'),'calendar_data_version':cal.attrs.get('data_version'),
              'minute_stock_days':len(minute),'auction_stock_days':len(auction),
              'illustrative_strategy':{'factor':args.backtest_factor,'direction':'higher','top_fraction':0.1,'initial_cash':args.capital,'lot_size':100,'commission_model':'ChinaStockCommission','notes':'周末信号下个交易日开盘成交，持仓缺价沿用最近开盘价估值，停牌和涨跌停等成交约束、除权分红、印花税与滑点未建模。'},
              'valid_counts':{f:int(auction[f].notna().sum()) for f in FACTOR_COLUMNS},
              'quality_rule':f'每阶段至少 {args.min_observations} 个有效快照；bid1=ask1=last>0 且处于有效价格上下限；正式开盘价必须唯一且大于零',
              'stage_boundaries':'[09:15,09:20), [09:20,09:25)',
              'amplitude_assumption':'(阶段最高-最低)/当日参考前收，研报未明确分母',
              'return_price':'9:25后快照唯一正数open；缺失不使用分钟代理',
              'missing_auction_files':missing,'no_matching_auction_dates':empty_days,'auction_inputs':versions,
              'limitations':'快照可能遗漏极值；行情口径待供应商核实；前收口径待核实；固定月度样本非精确历史成分，未过滤ST、新股及涨跌停；开盘价不保证实际成交，未复权、未处理公司行为或交易限制；截面收益未计成本；示例模拟仅计项目佣金，不代表可交易结果。'}
    (args.output_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('股票日',len(data),'竞价股票日',len(auction),'周频因子记录',len(weekly),flush=True)

if __name__=='__main__':
    main()
