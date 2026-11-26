"""46 因子滚动历史 IC 定向、等权截面组合的周频研究回测。"""
from __future__ import annotations
import argparse, hashlib, json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.strategy.auction_factors import FACTOR_COLUMNS
from src.utils.commission import ChinaStockCommission
from src.strategy.intraday_artifacts import load_factors
from src.datahub import DataRequest, create_service
from src.datahub.models import DataKind
from src.datahub.research_daily_repository import ResearchDailyRepository
from src.datahub.service import MarketDataService
from src.datahub.router import DataRouter
from src.strategy_evaluation import evaluate_returns

ROOT=Path('data/intraday_factors/local_minute_factors')
AUCTION=Path('data/intraday_factors/auction_history/daily')
COVERAGE=Path('examples/intraday_factors/auction_history/coverage.parquet')
HISTORY=Path('examples/intraday_factors/local_minute_research/weekly_research.csv')
OUT=Path('examples/intraday_factors/all_factor_backtest')


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def training_directions(byfactor, day, window=52):
    """仅使用持有期已完成的 IC；窗口不足时不产生方向。"""
    signs = {}
    for f, history in byfactor.items():
        prior = history.loc[history.exit_date.le(day), 'rank_ic'].dropna().tail(window)
        if len(prior) == window:
            signs[f] = 1 if prior.mean() >= 0 else -1
    return signs


def weekly_execution_dates(exchange_days, factor_end, valuation_end):
    """完整周最后开市日 → 下一交易日，信号不得晚于因子覆盖。"""
    exchange_days = pd.DatetimeIndex(exchange_days)
    if (exchange_days.has_duplicates or not exchange_days.is_monotonic_increasing
            or factor_end not in exchange_days or valuation_end not in exchange_days
            or valuation_end < factor_end or exchange_days[-1] <= factor_end):
        raise ValueError('交易日历须覆盖因子期、估值期及之后的交易日')
    weeks = exchange_days.to_period('W-FRI')
    return {day: next_day for day, next_day, this_week, next_week
            in zip(exchange_days, exchange_days[1:], weeks, weeks[1:])
            if this_week != next_week and day <= factor_end and next_day <= valuation_end}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factor-dir',type=Path,default=ROOT)
    parser.add_argument('--auction-dir',type=Path,default=AUCTION)
    parser.add_argument('--coverage',type=Path,default=COVERAGE)
    parser.add_argument('--history',type=Path,default=HISTORY)
    parser.add_argument('--output-dir',type=Path,default=OUT)
    parser.add_argument('--snapshots',type=Path,default=Path('data/intraday_factors/csi500/snapshots.parquet'))
    parser.add_argument('--reference-dir',type=Path,default=Path('data/micro_cap_timing_plus'))
    parser.add_argument('--calendar',type=Path,help='参考准备脚本生成的交易所日历 Parquet')
    parser.add_argument('--valuation-end',help='开盘估值结束日；默认取资格截止日或已缓存的下一交易日')
    args=parser.parse_args()
    root,auction_dir,coverage,history_path,out=args.factor_dir,args.auction_dir,args.coverage,args.history,args.output_dir
    snapshots=args.snapshots
    cov=pd.read_parquet(coverage);cov['date']=pd.to_datetime(cov.date).dt.normalize()
    if cov.duplicated(['symbol','date']).any():raise ValueError('资格表重复')
    symbols=sorted(cov.symbol.unique());calendar=pd.DatetimeIndex(sorted(cov.date.unique()))
    if calendar.min()!=pd.Timestamp('2021-01-04'):raise ValueError('资格数据起点发生变化')
    factor_end=calendar.max()
    calendar_path=args.calendar or snapshots.parent.parent/'calendar.parquet'
    if calendar_path.is_file():
        exchange_days=pd.DatetimeIndex(pd.read_parquet(calendar_path).date)
        calendar_version=sha(calendar_path)
    elif args.calendar:
        raise FileNotFoundError(calendar_path)
    else:
        service=create_service()
        try:
            sessions=service.get_trade_calendar(DataRequest(start=calendar.min(),
                end=factor_end+pd.Timedelta(days=14),exchange='SSE',options={'is_open':'1'}))
        finally:
            service.close()
        exchange_days=pd.DatetimeIndex(pd.to_datetime(sessions.loc[sessions.is_open.eq(1),'trade_date'])).sort_values()
        calendar_version=sessions.attrs.get('data_version')
    if not calendar.equals(exchange_days[exchange_days <= factor_end]):
        raise ValueError('资格表和交易所日历的日期不一致')
    next_session=exchange_days[exchange_days > factor_end]
    if next_session.empty:
        raise ValueError('日历必须覆盖因子截止日之后的开市日')
    has_next_price=(args.reference_dir/'raw/daily'/f'{next_session[0]:%Y%m%d}.parquet').is_file()
    valuation_end=pd.Timestamp(args.valuation_end) if args.valuation_end else next_session[0] if has_next_price else factor_end
    entries=weekly_execution_dates(exchange_days,factor_end,valuation_end)
    dates=exchange_days[exchange_days <= valuation_end]
    # 仅信号日及其最近四个交易日需要读因子文件。
    ends=entries.keys()
    required=set()
    for day in ends:
        i=calendar.get_loc(day)
        if i>=4:required.update(calendar[i-4:i+1])
    minute=[];auction=[]; impl=sha('src/strategy/intraday_factors.py');builder=sha('scripts/build_local_minute_factors.py');repo=sha('src/datahub/local_minute_repository.py');auction_impl=sha('src/strategy/auction_factors.py')
    snap=sha(snapshots)
    symbol_hash=hashlib.sha256('\n'.join(symbols).encode()).hexdigest()
    for i,day in enumerate(sorted(required),1):
        key=day.strftime('%Y%m%d'); p=root/(key+'.parquet')
        f,info=load_factors(p,day,symbols,snapshots)
        q=auction_dir/(key+'.parquet')
        a,ainfo=load_factors(q,day,symbols,snapshots,auction=True)
        minute.append(f);auction.append(a[['symbol','date']+FACTOR_COLUMNS])
        if i%250==0:print('载入因子',i,'/',len(required),flush=True)
    m=pd.concat(minute,ignore_index=True);a=pd.concat(auction,ignore_index=True)
    m['date']=pd.to_datetime(m.date);a['date']=pd.to_datetime(a.date)
    factors=[c for c in m if c not in ('symbol','date')]+FACTOR_COLUMNS
    if len(factors)!=46 or len(set(factors))!=46:raise ValueError('因子数异常')
    frame=m.merge(a,on=['symbol','date'],how='outer',validate='one_to_one')
    if frame.duplicated(['symbol','date']).any():raise ValueError('因子日期重复')
    # 行情日历网格确保连续5个交易日都有观测，不能跨停牌/缺失填充。
    grid=pd.MultiIndex.from_product([symbols,calendar],names=['symbol','date'])
    frame=frame.set_index(['symbol','date']).reindex(grid)
    smooth=frame.groupby(level='symbol',sort=False)[factors].transform(lambda v:v.rolling(5,min_periods=5).mean())
    del frame,m,a,minute,auction
    ic=pd.read_csv(history_path,parse_dates=['signal_date','exit_date'])
    if set(ic.factor.unique())!=set(factors):raise ValueError('历史IC因子集合不匹配')
    if ic.duplicated(['factor','signal_date']).any() or not ic.exit_date.gt(ic.signal_date).all():
        raise ValueError('IC主键或持有期时间异常')
    # 历史IC仅在实际持有期结束后可用于方向；训练固定最近52个已完成周。
    byfactor={f:ic[ic.factor.eq(f)].sort_values('exit_date') for f in factors}
    eligibility=cov.set_index(['date','symbol']).eligible
    schedules={};directions=[];scores=[];training_windows=[]
    for day in ends:
        pos=calendar.get_loc(day)
        if pos<4:continue
        signs=training_directions(byfactor,day)
        if len(signs)!=46:continue
        for f,history in byfactor.items():
            prior=history[history.exit_date.le(day)].dropna(subset=['rank_ic']).tail(52)
            training_windows.append({'signal_date':day,'factor':f,'observations':len(prior),
                                     'first_exit':prior.exit_date.min(),'last_exit':prior.exit_date.max(),
                                     'mean_rank_ic':prior.rank_ic.mean(),'direction':signs[f]})
        x=smooth.xs(day,level='date'); allowed=eligibility.xs(day,level='date');x=x.loc[allowed[allowed.eq(True)].index.intersection(x.index)]
        x=x.replace([np.inf,-np.inf],np.nan).dropna(subset=factors)
        if len(x)<20:continue
        ranked=x[factors].rank(pct=True,method='average');score=ranked.mul(pd.Series(signs),axis='columns').mean(axis=1)
        score=score.sort_values(ascending=False,kind='stable');count=max(1,math.ceil(len(score)*.10));selected=score.index[:count].tolist()
        entry=entries[day];schedules[entry]=(day,selected,len(score));directions.append({'signal_date':day,**signs})
        scores.extend({'signal_date':day,'symbol':s,'rank':i+1,'score':float(score.loc[s]),'selected':s in selected} for i,s in enumerate(score.index))
    if not schedules:raise ValueError('没有合格信号')
    print('可回测调仓次数',len(schedules),'最近信号',max(x[0] for x in schedules.values()),flush=True)
    # 读取未经复权日线；依上一成交日收盘/当日参考前收构造近似总收益开盘价格。
    quotes=[]
    daily_service=MarketDataService(DataRouter({}),repository=ResearchDailyRepository(args.reference_dir))
    quote_versions=[]
    try:
        for d in dates:
            q=daily_service.get_cached(DataKind.DAILY_BULK,DataRequest(symbols=tuple(symbols),start=d,end=d,frequency='1d',adjust='none'))
            if q is None:raise ValueError(f'缺少日线 {d}')
            quote_versions.append({'date':str(d.date()),'sha256':q.attrs['data_version']})
            q=q[['ts_code','trade_date','open','close','pre_close','vol']].copy();q['date']=d;quotes.append(q)
    finally:daily_service.close()
    q=pd.concat(quotes,ignore_index=True).sort_values(['ts_code','date']);q=q.rename(columns={'ts_code':'symbol'})
    if q.duplicated(['symbol','date']).any():raise ValueError('日线重复')
    prev=q.groupby('symbol').close.shift();valid=(prev>0)&(q.pre_close>0);q['ratio']=(prev/q.pre_close).where(valid,1.)
    q['scale']=q.groupby('symbol').ratio.cumprod();q['adjusted_open']=q.open*q.scale
    q.loc[(q.open<=0)|(q.vol<=0),'adjusted_open']=np.nan
    prices=q.pivot(index='date',columns='symbol',values='adjusted_open').reindex(dates)
    rawopen=q.pivot(index='date',columns='symbol',values='open').reindex(dates)
    marks=prices.ffill();commission=ChinaStockCommission();cash=1_000_000.;positions={};equity=[];trades=[];targets=[]
    first=min(schedules)
    for day in dates[dates>=first]:
        row=prices.loc[day];mark=marks.loc[day]
        if any(not np.isfinite(mark.get(s,np.nan)) for s in positions):raise ValueError(f'持仓没有估值 {day}')
        if day in schedules:
            signal,selected,universe=schedules[day];value=cash+sum(v*mark[s] for s,v in positions.items());target_value=value/len(selected)
            for s in sorted(set(positions)|set(selected)):
                px=row.get(s,np.nan); curr=positions.get(s,0.)*(mark.get(s,0.) if np.isfinite(mark.get(s,np.nan)) else 0.)
                desired=target_value if s in selected else 0.
                targets.append({'signal_date':signal,'trade_date':day,'symbol':s,'selected':s in selected,'target_weight':1/len(selected) if s in selected else 0.,'open_raw':rawopen.loc[day].get(s,np.nan),'can_price':bool(np.isfinite(px) and px>0),'score_universe':universe})
                if not np.isfinite(px) or px<=0:continue
                delta=desired-curr
                if delta< -1e-7:
                    qty=min(positions.get(s,0.),-delta/px);fee=commission.getcommission(-qty,px);cash+=qty*px-fee;positions[s]-=qty
                    if positions[s]<1e-10:positions.pop(s,None)
                    trades.append({'date':day,'symbol':s,'side':'sell','notional':qty*px,'fee':fee})
            for s in selected:
                px=row.get(s,np.nan)
                if not np.isfinite(px) or px<=0:continue
                curr=positions.get(s,0.)*px; delta=max(0.,target_value-curr)
                if delta<1e-7:continue
                delta=min(delta,max(0.,(cash-commission.p.min_comm)/(1+commission.p.commission)))
                if delta<=0:continue
                qty=delta/px;fee=commission.getcommission(qty,px)
                if delta+fee>cash+1e-6:raise ValueError('现金不足')
                cash-=delta+fee;positions[s]=positions.get(s,0.)+qty;trades.append({'date':day,'symbol':s,'side':'buy','notional':delta,'fee':fee})
        mv=sum(v*mark[s] for s,v in positions.items());equity.append({'date':day,'cash':cash,'market_value':mv,'equity':cash+mv,'positions':len(positions),'stale_positions':sum(not np.isfinite(row.get(s,np.nan)) for s in positions),'rebalance':day in schedules})
    nav=pd.DataFrame(equity);trade=pd.DataFrame(trades);target=pd.DataFrame(targets)
    bench_path=args.reference_dir/'reference/index_000905.SH.parquet'
    bench=pd.read_parquet(bench_path);bench['date']=pd.to_datetime(bench.trade_date.astype(str),format='%Y%m%d');bench=bench.set_index('date').open
    nav['benchmark_open']=nav.date.map(bench);nav['benchmark_nav']=nav.benchmark_open/nav.benchmark_open.iloc[0]
    if nav.benchmark_nav.isna().any():raise ValueError('缺少基准指数开盘价')
    nav['nav']=nav.equity/1_000_000;nav['relative_nav']=nav.nav/nav.benchmark_nav
    years = (nav.date.iloc[-1] - nav.date.iloc[0]).days / 365.25
    annual_relative = float(nav.relative_nav.iloc[-1] ** (1 / years) - 1) if years > 0 else None
    metrics={'first_trade_date':str(nav.date.iloc[0].date()),'end_date':str(nav.date.iloc[-1].date()),'latest_signal_date':str(max(schedules.values(),key=lambda x:x[0])[0].date()),'rebalance_count':len(schedules),'stock_pool':'中证500月度快照滞后31自然日近似，ST、上市不足一年和未成交筛除','factors':46,'train':'最近52个已结束持有期的单因子周度秩IC均值定向；历史IC按输入覆盖范围滚动更新','min_input_factors':46,'top_fraction':0.1,'window_days':5,'initial_cash':1000000,'final_equity':float(nav.equity.iloc[-1]),'benchmark_total_return':float(nav.benchmark_nav.iloc[-1]-1),'relative_total_return':float(nav.relative_nav.iloc[-1]-1),'annual_relative_return':annual_relative,'total_commission':float(trade.fee.sum()),'stale_position_days':int(nav.stale_positions.sum()),'input_coverage_sha256':sha(coverage),'input_ic_sha256':sha(history_path),'snapshot_sha256':snap,'limitations':'日线开盘近似成交，无涨跌停、市场冲击、滑点、印花税和过户费；连续股数无整手；手续费使用项目佣金（万0.854，每笔最低5元）；复权使用前收比值近似，公司行为等效再投资，停牌沿用上次估值；未来缺失开盘不能成交，长期缺价不自动退市清算；月度权重非精确历史成分；竞价因子快照口径和分钟时间语义未完全确认；因子方向来自历史单因子IC，非研报指定组合。'}
    out.mkdir(parents=True,exist_ok=True);nav.to_csv(out/'nav.csv',index=False);trade.to_csv(out/'trades.csv',index=False);target.to_csv(out/'targets.csv',index=False);pd.DataFrame(scores).to_parquet(out/'scores.parquet',index=False);pd.DataFrame(directions).to_csv(out/'directions.csv',index=False)
    pd.DataFrame(training_windows).to_csv(out/'training_windows.csv',index=False)
    latest=target[(target.signal_date==target.signal_date.max()) & target.selected].copy();names=pd.read_parquet(args.reference_dir/'reference/stock_basic.parquet')[['ts_code','name']].rename(columns={'ts_code':'symbol'});latest=latest.merge(names,on='symbol',how='left',validate='many_to_one');score_frame=pd.DataFrame(scores);last_scores=score_frame[score_frame.signal_date.eq(target.signal_date.max())][['symbol','rank','score']];latest=latest.merge(last_scores,on='symbol',validate='one_to_one').sort_values('rank');latest.to_csv(out/'latest_selection.csv',index=False)
    final_mark=marks.loc[nav.date.iloc[-1]]
    holdings=pd.DataFrame([{'symbol':s,'adjusted_shares':qty,
                           'market_value':qty*final_mark[s],
                           'actual_weight':qty*final_mark[s]/nav.equity.iloc[-1]}
                          for s,qty in positions.items()])
    holdings=holdings.merge(names,on='symbol',how='left',validate='one_to_one')
    holdings['valuation_date']=nav.date.iloc[-1]
    holdings.to_csv(out/'latest_holdings.csv',index=False)
    latest=latest.merge(holdings[['symbol','market_value','actual_weight']],on='symbol',how='left',validate='one_to_one')
    latest[['market_value','actual_weight']]=latest[['market_value','actual_weight']].fillna(0.)
    latest.to_csv(out/'latest_selection.csv',index=False)
    returns = nav.nav.pct_change(fill_method=None)
    returns.iloc[0] = nav.nav.iloc[0] - 1
    evaluation = evaluate_returns(returns)
    metrics.update(evaluation.metrics | evaluation.scoring)
    metrics.update(benchmark_sha256=sha(bench_path), daily_source_versions=quote_versions,
                   factor_end=str(factor_end.date()), calendar_data_version=calendar_version,
                   latest_trade_date=str(latest.trade_date.iloc[0].date()),
                   latest_target_count=len(latest), latest_priced_targets=int(latest.can_price.sum()),
                   latest_holdings=len(holdings), final_cash=float(cash),
                   cash_weight=float(cash/nav.equity.iloc[-1]),history_max_exit=str(ic.exit_date.max().date()),
                   code_sha256=sha(__file__), input_factor_directory=str(root),
                   input_auction_directory=str(auction_dir), input_history=str(history_path))
    if cash < -1e-6 or not np.isclose(holdings.market_value.sum()+cash,nav.equity.iloc[-1]):
        raise ValueError('期末资金持仓未对账')
    (out/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in metrics.items() if k!='daily_source_versions'},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
