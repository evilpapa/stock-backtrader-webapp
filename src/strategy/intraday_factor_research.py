"""周频截面研究：使用明确交易日历，输出毛收益而非可交易回测。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def weekly_research(daily: pd.DataFrame, calendar: pd.DatetimeIndex, window: int = 5, hold: int = 5, *, eligibility_column: str | None = None, returns_column: str | None = None):
    """T 收盘信号，T+1 首分钟开盘至 T+1+hold 首分钟开盘的毛收益。

    输入 open_proxy 不是官方开盘价；无 ST、涨跌停、公司行为或成本处理。
    日历必须覆盖输入及未来收益所需的所有交易日。
    """
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize().sort_values()
    if calendar.has_duplicates or window < 1 or hold < 1:
        raise ValueError('日历或参数无效')
    data = daily.copy()
    data['date'] = pd.to_datetime(data['date']).dt.normalize()
    if data.duplicated(['symbol', 'date']).any() or not data.date.isin(calendar).all():
        raise ValueError('存在重复证券日期或日期不在交易日历内')
    factors = [c for c in data.columns if c not in ('symbol', 'date', 'open_proxy', eligibility_column, returns_column)]
    if returns_column is not None and returns_column not in data:
        raise ValueError('缺少预计算未来收益字段')
    if eligibility_column is not None and eligibility_column not in data:
        raise ValueError('缺少股票池资格字段')
    data = data.set_index(['symbol', 'date']).sort_index()
    grid = pd.MultiIndex.from_product([data.index.get_level_values('symbol').unique(), calendar], names=['symbol', 'date'])
    panel = data.reindex(grid)
    smoothed = panel.groupby(level='symbol')[factors].transform(lambda x: x.rolling(window, min_periods=window).mean())
    opens = panel['open_proxy'].unstack('symbol').reindex(calendar)
    opens = opens.where(np.isfinite(opens) & (opens > 0))
    week_end = pd.Series(calendar, index=calendar).groupby(calendar.to_period('W-FRI')).last()
    # 末周可能被截断；日历末日不足以确认末周收盘，但它也没有未来持有期。
    result = []
    for day in week_end:
        pos = calendar.get_loc(day)
        if pos + 1 + hold >= len(calendar):
            continue
        entry, exit_day = calendar[pos + 1], calendar[pos + 1 + hold]
        returns = (opens.loc[exit_day].div(opens.loc[entry]).sub(1) if returns_column is None
                   else panel[returns_column].xs(day, level='date')).replace([np.inf, -np.inf], np.nan)
        values = smoothed.xs(day, level='date')
        if eligibility_column is not None:
            allowed = panel[eligibility_column].xs(day, level='date').eq(True)
            values = values.loc[allowed]
        for factor in factors:
            # 首先仅按信号日可见数据分组，避免用未来价格是否缺失影响分组。
            sample = pd.DataFrame({'factor': values[factor], 'return': returns})
            sample = sample.dropna(subset=['factor']).sort_values('factor', kind='stable')
            if len(sample) < 10 or sample['factor'].nunique() < 2:
                continue
            sample['group'] = np.floor(np.arange(len(sample)) * 10 / len(sample)).astype(int) + 1
            valid = sample.dropna(subset=['return'])
            if len(valid) < 10:
                continue
            row = {'signal_date': day, 'entry_date': entry, 'exit_date': exit_day, 'factor': factor,
                   'signal_n': len(sample), 'n': len(valid),
                   'rank_ic': valid['factor'].corr(valid['return'], method='spearman')}
            row.update({f'group_{i}': valid.loc[valid.group.eq(i), 'return'].mean() for i in range(1, 11)})
            row.update({f'group_{i}_n': int(valid.group.eq(i).sum()) for i in range(1, 11)})
            result.append(row)
    return pd.DataFrame(result)
