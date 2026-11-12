"""基于本地集合竞价快照构造盘前因子；价格有效性规则为研究假设。"""
from __future__ import annotations
import numpy as np
import pandas as pd

FACTOR_COLUMNS = ['ret_open2AH1','ret_open2AL1','ret_open2AH2','ret_open2AL2','diverge_A1','diverge_A2','ret_overnight']


def auction_daily_factors(ticks: pd.DataFrame, min_observations: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {'security_id','md_date','md_time','last','open','pre_close','bid1','ask1','min','max'}
    if not required.issubset(ticks.columns) or min_observations < 1:
        raise ValueError('缺少行情字段或最小有效快照数不合法')
    if ticks.duplicated(['security_id','md_date','md_time']).any():
        raise ValueError('集合竞价快照时间戳重复')
    data=ticks.copy()
    data['date']=pd.to_datetime(data['md_date'].astype(str), format='%Y%m%d', errors='raise')
    data=data.sort_values(['security_id','date','md_time'])
    factors=[]
    quality=[]
    for (symbol, date), group in data.groupby(['security_id','date'], sort=True):
        closing=group.loc[(group.md_time>=92500000)&(group.md_time<93000000), 'open']
        closing=pd.to_numeric(closing, errors='coerce')
        prices=closing[np.isfinite(closing)&(closing>0)].unique()
        opening=float(prices[0]) if len(prices)==1 else np.nan
        pc=pd.to_numeric(group.pre_close, errors='coerce')
        prev=pc[np.isfinite(pc)&(pc>0)].unique()
        previous=float(prev[0]) if len(prev)==1 else np.nan
        stages=[]
        for lo,hi in [(91500000,92000000),(92000000,92500000)]:
            stage=group.loc[(group.md_time>=lo)&(group.md_time<hi)].copy()
            numeric=['last','bid1','ask1','min','max']
            stage[numeric]=stage[numeric].apply(pd.to_numeric,errors='coerce')
            ok=(np.isfinite(stage[numeric]).all(axis=1) & (stage['last']>0) & (stage.bid1>0)
                & np.isclose(stage.bid1,stage.ask1,atol=1e-8,rtol=0)
                & np.isclose(stage['last'],stage.bid1,atol=1e-8,rtol=0)
                & (stage['min']>0) & (stage['max']>stage['min'])
                & (stage['last']>=stage['min']-1e-8) & (stage['last']<=stage['max']+1e-8))
            valid=stage.loc[ok,'last']
            stages.append((len(stage),len(valid),float(valid.min()) if len(valid)>=min_observations else np.nan,
                           float(valid.max()) if len(valid)>=min_observations else np.nan))
        row={'symbol':symbol,'date':date}
        for index, (_,_,low,high) in enumerate(stages,1):
            row[f'ret_open2AH{index}']=opening/high-1 if np.isfinite(opening) and np.isfinite(high) else np.nan
            row[f'ret_open2AL{index}']=opening/low-1 if np.isfinite(opening) and np.isfinite(low) else np.nan
            # 报告仅描述振幅，未给明确分母；暂以参考前收为分母。
            row[f'diverge_A{index}']=(high-low)/previous if np.isfinite(previous) and np.isfinite(high) else np.nan
        row['ret_overnight']=opening/previous-1 if np.isfinite(opening) and np.isfinite(previous) else np.nan
        factors.append(row)
        quality.append({'symbol':symbol,'date':date,'auction_open':opening,'auction_pre_close':previous,
                        'open_values':len(prices),'pre_close_values':len(prev),
                        'stage1_total':stages[0][0],'stage1_valid':stages[0][1],
                        'stage2_total':stages[1][0],'stage2_valid':stages[1][1],
                        'stage1_low':stages[0][2],'stage1_high':stages[0][3],
                        'stage2_low':stages[1][2],'stage2_high':stages[1][3]})
    return pd.DataFrame(factors, columns=['symbol','date']+FACTOR_COLUMNS), pd.DataFrame(quality)


def auction_daily_factors_vectorized(ticks: pd.DataFrame, min_observations: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """批量版，与逐证券实现使用相同的过滤条件及因子定义。"""
    required={'security_id','md_date','md_time','last','open','pre_close','bid1','ask1','min','max'}
    if not required.issubset(ticks.columns) or min_observations < 1:
        raise ValueError('缺少行情字段或最小有效快照数不合法')
    if ticks.duplicated(['security_id','md_date','md_time']).any():
        raise ValueError('集合竞价快照时间戳重复')
    data=ticks.copy()
    keys=['security_id','md_date']
    for col in ['last','open','pre_close','bid1','ask1','min','max']:
        data[col]=pd.to_numeric(data[col],errors='coerce')
    grouped=data.groupby(keys,sort=True)
    pc=data.pre_close.where(np.isfinite(data.pre_close)&(data.pre_close>0))
    opens=data.open.where((data.md_time>=92500000)&(data.md_time<93000000)&np.isfinite(data.open)&(data.open>0))
    summaries=data[keys].drop_duplicates().set_index(keys).sort_index()
    summaries['pc_min']=pc.groupby([data[k] for k in keys]).min()
    summaries['pc_max']=pc.groupby([data[k] for k in keys]).max()
    summaries['open_min']=opens.groupby([data[k] for k in keys]).min()
    summaries['open_max']=opens.groupby([data[k] for k in keys]).max()
    summaries['auction_pre_close']=summaries.pc_min.where(summaries.pc_min.eq(summaries.pc_max))
    summaries['auction_open']=summaries.open_min.where(summaries.open_min.eq(summaries.open_max))
    valid=(np.isfinite(data[['last','bid1','ask1','min','max']]).all(axis=1) & (data['last']>0)
           & (data.bid1>0)&np.isclose(data.bid1,data.ask1,atol=1e-8,rtol=0)
           & np.isclose(data['last'],data.bid1,atol=1e-8,rtol=0)
           &(data['min']>0)&(data['max']>data['min'])
           &(data['last']>=data['min']-1e-8)&(data['last']<=data['max']+1e-8))
    for i,(lo,hi) in enumerate([(91500000,92000000),(92000000,92500000)],1):
        stage=(data.md_time>=lo)&(data.md_time<hi)
        totals=data.loc[stage].groupby(keys).size()
        selected=data.loc[stage&valid].groupby(keys)['last'].agg(['size','min','max'])
        summaries[f'stage{i}_total']=totals.reindex(summaries.index,fill_value=0)
        summaries[f'stage{i}_valid']=selected['size'].reindex(summaries.index,fill_value=0)
        summaries[f'stage{i}_low']=selected['min'].where(selected['size']>=min_observations)
        summaries[f'stage{i}_high']=selected['max'].where(selected['size']>=min_observations)
        summaries[f'ret_open2AH{i}']=summaries.auction_open/summaries[f'stage{i}_high']-1
        summaries[f'ret_open2AL{i}']=summaries.auction_open/summaries[f'stage{i}_low']-1
        summaries[f'diverge_A{i}']=(summaries[f'stage{i}_high']-summaries[f'stage{i}_low'])/summaries.auction_pre_close
    summaries['ret_overnight']=summaries.auction_open/summaries.auction_pre_close-1
    summaries=summaries.reset_index().rename(columns={'security_id':'symbol','md_date':'date'})
    summaries['date']=pd.to_datetime(summaries.date.astype(str),format='%Y%m%d')
    factors=summaries[['symbol','date']+FACTOR_COLUMNS]
    quality=summaries[['symbol','date','auction_open','auction_pre_close','stage1_total','stage1_valid',
                       'stage2_total','stage2_valid','stage1_low','stage1_high','stage2_low','stage2_high']]
    return factors,quality
