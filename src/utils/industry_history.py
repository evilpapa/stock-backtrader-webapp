"""根据历史行业成员区间构造时点行业矩阵。

成员区间使用 [in_date, out_date)；缺少入选日期不推测，缺少剔除日期视为仍在。
同一证券同日存在不同一级行业的重叠记录时标记缺失，不用未来信息猜测。
"""
from __future__ import annotations

import pandas as pd


def build_industry_matrix(members: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    required = {'ts_code', 'l1_name', 'in_date', 'out_date'}
    missing = required - set(members.columns)
    if missing:
        raise ValueError(f'行业成员数据缺少字段: {sorted(missing)}')
    data = members[list(required)].copy()
    data['in_date'] = pd.to_datetime(data['in_date'], errors='coerce')
    data['out_date'] = pd.to_datetime(data['out_date'], errors='coerce')
    data = data.dropna(subset=['ts_code', 'l1_name', 'in_date']).drop_duplicates()
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).normalize().sort_values().unique()
    rows = []
    for day in dates:
        active = data[(data.in_date <= day) & (data.out_date.isna() | (data.out_date > day))]
        # 低级行业更替可能产生同一一级行业重复记录，仅跨一级行业重叠才算冲突。
        counts = active.groupby('ts_code')['l1_name'].nunique()
        valid = active[active['ts_code'].map(counts).eq(1)]
        rows.append(valid.drop_duplicates('ts_code').set_index('ts_code')['l1_name'].rename(day))
    matrix = pd.DataFrame(rows).reindex(columns=sorted(data['ts_code'].unique()))
    matrix.index = pd.DatetimeIndex(dates, name='date')
    matrix.columns.name = 'symbol'
    return matrix
