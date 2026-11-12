"""周频竞价因子研究用的简化开盘撮合模拟，不处理公司行为或涨跌停。"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from src.utils.commission import ChinaStockCommission


def simulate_weekly(daily: pd.DataFrame, calendar: pd.DatetimeIndex, *, factor: str,
                    top_fraction: float = .1, initial_cash: float = 1_000_000., window: int = 5,
                    min_universe: int = 10, lot: int = 100):
    """按 T 收盘因子排序，T+1 开盘再平衡；仅项目佣金、整手、现金约束。"""
    if not 0 < top_fraction <= 1 or initial_cash <= 0 or window < 1 or min_universe < 1 or lot < 1:
        raise ValueError('参数无效')
    dates=pd.DatetimeIndex(pd.to_datetime(calendar)).normalize().sort_values()
    if dates.has_duplicates:
        raise ValueError('重复交易日')
    data=daily[['symbol','date','open_proxy',factor]].copy()
    data['date']=pd.to_datetime(data.date).dt.normalize()
    if data.duplicated(['symbol','date']).any() or not data.date.isin(dates).all():
        raise ValueError('重复证券日期或日期不在交易日历')
    grid=pd.MultiIndex.from_product([sorted(data.symbol.unique()),dates],names=['symbol','date'])
    panel=data.set_index(['symbol','date']).reindex(grid)
    signal=panel.groupby(level='symbol')[factor].transform(lambda x:x.rolling(window,min_periods=window).mean())
    price=panel.open_proxy.unstack('symbol').reindex(dates)
    price=price.where(np.isfinite(price)&(price>0))
    ends=pd.Series(dates,index=dates).groupby(dates.to_period('W-FRI')).last()
    schedules={}
    for day in ends:
        pos=dates.get_loc(day)
        if pos+1>=len(dates):
            continue
        values=signal.xs(day,level='date').dropna().sort_values(ascending=False,kind='stable')
        if len(values)>=min_universe:
            count=max(1, math.ceil(len(values)*top_fraction))
            schedules[dates[pos+1]]=(day,values.iloc[:count].index.tolist(),len(values))
    commission=ChinaStockCommission()
    cash=float(initial_cash)
    positions={}
    marks={}
    trades=[]
    equity=[]
    for day in dates:
        row=price.loc[day].dropna()
        marks.update(row.to_dict())
        if day in schedules:
            signal_day,selected,universe=schedules[day]
            value=cash+sum(size*marks[symbol] for symbol,size in positions.items())
            target_value=value/len(selected)
            target={symbol:(int(target_value/row[symbol]/lot)*lot if symbol in row else None) for symbol in selected}
            for symbol,size in sorted(list(positions.items())):
                if symbol not in row:
                    continue
                desired=target.get(symbol,0)
                qty=max(0,size-(desired if desired is not None else size))
                if qty:
                    px=float(row[symbol]); fee=commission.getcommission(-qty,px)
                    cash+=qty*px-fee
                    positions[symbol]-=qty
                    if not positions[symbol]:
                        del positions[symbol]
                    trades.append({'date':day,'signal_date':signal_day,'symbol':symbol,'side':'sell','shares':qty,'price':px,'commission':fee,'signal_universe':universe})
            for symbol in selected:
                desired=target[symbol]
                if desired is None:
                    continue
                px=float(row[symbol]); qty=max(0,desired-positions.get(symbol,0))
                while qty>0:
                    # 费用最低 5 元；按可用现金直接求上限，避免逐手反复调用佣金模型。
                    estimated_fee=max(px*qty*commission.p.commission,commission.p.min_comm)
                    if qty*px+estimated_fee<=cash+1e-8:
                        break
                    qty=max(0,int((cash-estimated_fee)/(px*lot))*lot)
                if qty:
                    fee=commission.getcommission(qty,px)
                    cash-=qty*px+fee
                    positions[symbol]=positions.get(symbol,0)+qty
                    trades.append({'date':day,'signal_date':signal_day,'symbol':symbol,'side':'buy','shares':qty,'price':px,'commission':fee,'signal_universe':universe})
        stale=sum(symbol not in row for symbol in positions)
        mv=sum(size*marks[symbol] for symbol,size in positions.items())
        equity.append({'date':day,'cash':cash,'market_value':mv,'equity':cash+mv,
                       'positions':len(positions),'stale_positions':stale,'rebalanced':day in schedules})
    return pd.DataFrame(equity),pd.DataFrame(trades,columns=['date','signal_date','symbol','side','shares','price','commission','signal_universe'])
