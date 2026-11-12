"""46 因子滚动历史 IC 定向、等权截面组合的周频研究回测。"""
from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.strategy.auction_factors import FACTOR_COLUMNS
from src.utils.commission import ChinaStockCommission

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


def main():
    cov=pd.read_parquet(COVERAGE);cov['date']=pd.to_datetime(cov.date).dt.normalize()
    if cov.duplicated(['symbol','date']).any():raise ValueError('资格表重复')
    symbols=sorted(cov.symbol.unique());calendar=pd.DatetimeIndex(sorted(cov.date.unique()))
    if calendar.min()!=pd.Timestamp('2021-01-04') or calendar.max()!=pd.Timestamp('2026-02-27'):raise ValueError('资格数据范围发生变化')
    raw_daily=Path('data/micro_cap_timing_plus/raw/daily')
    following=sorted(pd.Timestamp(p.stem) for p in raw_daily.glob('*.parquet') if len(p.stem)==8 and p.stem.isdigit() and pd.Timestamp(p.stem)>calendar.max())
    if not following:raise ValueError('缺少最后调仓日的下一交易日行情')
    dates=calendar.append(pd.DatetimeIndex([following[0]]))
    # 仅信号日及其最近四个交易日需要读因子文件。
    ends=pd.Series(calendar,index=calendar).groupby(calendar.to_period('W-FRI')).last()
    required=set()
    for day in ends:
        i=calendar.get_loc(day)
        if i>=4:required.update(calendar[i-4:i+1])
    minute=[];auction=[]; impl=sha('src/strategy/intraday_factors.py');builder=sha('scripts/build_local_minute_factors.py');repo=sha('src/datahub/local_minute_repository.py');auction_impl=sha('src/strategy/auction_factors.py')
    snapshots=Path('data/intraday_factors/csi500/snapshots.parquet');snap=sha(snapshots)
    symbol_hash=hashlib.sha256('\n'.join(symbols).encode()).hexdigest()
    for i,day in enumerate(sorted(required),1):
        key=day.strftime('%Y%m%d'); p=ROOT/(key+'.parquet'); info=json.loads(p.with_suffix('.json').read_text()); f=pd.read_parquet(p)
        if info['output_sha256']!=sha(p) or info['implementation_sha256']!=impl or info['builder_sha256']!=builder or info['repository_sha256']!=repo or info['snapshot_sha256']!=snap or info['symbols']!=symbols or len(f)!=info['rows'] or not pd.to_datetime(f.date).eq(day).all():raise ValueError(f'分钟因子校验失败 {key}')
        q=AUCTION/(key+'.parquet'); ainfo=json.loads(q.with_suffix('.json').read_text()); a=pd.read_parquet(q)
        if ainfo['implementation_sha256']!=auction_impl or ainfo['symbols_sha256']!=symbol_hash or len(a)!=ainfo['rows'] or not pd.to_datetime(a.date).eq(day).all():raise ValueError(f'竞价因子校验失败 {key}')
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
    ic=pd.read_csv(HISTORY,parse_dates=['signal_date','exit_date'])
    if set(ic.factor.unique())!=set(factors):raise ValueError('历史IC因子集合不匹配')
    # 历史IC仅在实际持有期结束后可用于方向；训练固定最近52个已完成周。
    byfactor={f:ic[ic.factor.eq(f)].sort_values('exit_date') for f in factors}
    eligibility=cov.set_index(['date','symbol']).eligible
    schedules={};directions=[];scores=[]
    for day in ends:
        pos=calendar.get_loc(day)
        if pos<4:continue
        signs=training_directions(byfactor,day)
        if len(signs)!=46:continue
        x=smooth.xs(day,level='date'); allowed=eligibility.xs(day,level='date');x=x.loc[allowed[allowed.eq(True)].index.intersection(x.index)]
        x=x.replace([np.inf,-np.inf],np.nan).dropna(subset=factors)
        if len(x)<20:continue
        ranked=x[factors].rank(pct=True,method='average');score=ranked.mul(pd.Series(signs),axis='columns').mean(axis=1)
        score=score.sort_values(ascending=False,kind='stable');count=max(1,math.ceil(len(score)*.10));selected=score.index[:count].tolist()
        entry=dates[pos+1];schedules[entry]=(day,selected,len(score));directions.append({'signal_date':day,**signs})
        scores.extend({'signal_date':day,'symbol':s,'rank':i+1,'score':float(score.loc[s]),'selected':s in selected} for i,s in enumerate(score.index))
    if not schedules:raise ValueError('没有合格信号')
    print('可回测调仓次数',len(schedules),'最近信号',max(x[0] for x in schedules.values()),flush=True)
    # 读取未经复权日线；依上一成交日收盘/当日参考前收构造近似总收益开盘价格。
    quotes=[]
    for d in dates:
        p=raw_daily/(d.strftime('%Y%m%d')+'.parquet')
        if not p.exists():raise ValueError(f'缺少日线 {d}')
        q=pd.read_parquet(p,columns=['ts_code','trade_date','open','close','pre_close','vol']);q=q[q.ts_code.isin(symbols)].copy();q['date']=d;quotes.append(q)
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
    bench=pd.read_parquet('data/micro_cap_timing_plus/reference/index_000905.SH.parquet');bench['date']=pd.to_datetime(bench.trade_date.astype(str),format='%Y%m%d');bench=bench.set_index('date').open
    nav['benchmark_open']=nav.date.map(bench);nav['benchmark_nav']=nav.benchmark_open/nav.benchmark_open.iloc[0]
    if nav.benchmark_nav.isna().any():raise ValueError('缺少基准指数开盘价')
    nav['nav']=nav.equity/1_000_000;nav['relative_nav']=nav.nav/nav.benchmark_nav
    yrs=(nav.date.iloc[-1]-nav.date.iloc[0]).days/365.25
    metrics={'first_trade_date':str(nav.date.iloc[0].date()),'end_date':str(nav.date.iloc[-1].date()),'latest_signal_date':str(max(schedules.values(),key=lambda x:x[0])[0].date()),'rebalance_count':len(schedules),'stock_pool':'中证500月度快照滞后31自然日近似，ST、上市不足一年和未成交筛除','factors':46,'train':'最近52个已经结束持有期的单因子周度秩IC均值定向；2026年沿用2025年以前已完成的IC','min_input_factors':46,'top_fraction':0.1,'window_days':5,'initial_cash':1000000,'final_equity':float(nav.equity.iloc[-1]),'total_return':float(nav.nav.iloc[-1]-1),'annual_return':float(nav.nav.iloc[-1]**(1/yrs)-1),'benchmark_total_return':float(nav.benchmark_nav.iloc[-1]-1),'relative_total_return':float(nav.relative_nav.iloc[-1]-1),'annual_relative_return':float(nav.relative_nav.iloc[-1]**(1/yrs)-1),'max_drawdown':float((nav.nav/nav.nav.cummax()-1).min()),'total_commission':float(trade.fee.sum()),'stale_position_days':int(nav.stale_positions.sum()),'input_coverage_sha256':sha(COVERAGE),'input_ic_sha256':sha(HISTORY),'snapshot_sha256':snap,'limitations':'日线开盘近似成交，无涨跌停、市场冲击、滑点、印花税和过户费；连续股数无整手；手续费使用项目佣金（万0.854，每笔最低5元）；复权使用前收比值近似，公司行为等效再投资，停牌沿用上次估值；未来缺失开盘不能成交，长期缺价不自动退市清算；月度权重非精确历史成分；竞价因子快照口径和分钟时间语义未完全确认；因子方向来自历史单因子IC，非研报指定组合。'}
    OUT.mkdir(parents=True,exist_ok=True);nav.to_csv(OUT/'nav.csv',index=False);trade.to_csv(OUT/'trades.csv',index=False);target.to_csv(OUT/'targets.csv',index=False);pd.DataFrame(scores).to_parquet(OUT/'scores.parquet',index=False);pd.DataFrame(directions).to_csv(OUT/'directions.csv',index=False)
    latest=target[(target.signal_date==target.signal_date.max()) & target.selected].copy();names=pd.read_parquet('data/micro_cap_timing_plus/reference/stock_basic.parquet')[['ts_code','name']].rename(columns={'ts_code':'symbol'});latest=latest.merge(names,on='symbol',how='left',validate='many_to_one');score_frame=pd.DataFrame(scores);last_scores=score_frame[score_frame.signal_date.eq(target.signal_date.max())][['symbol','rank','score']];latest=latest.merge(last_scores,on='symbol',validate='one_to_one').sort_values('rank');latest.to_csv(OUT/'latest_selection.csv',index=False)
    (OUT/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(metrics,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
