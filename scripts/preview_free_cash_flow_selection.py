"""使用本地已缓存数据生成研究候选，不生成委托、不联网、不下单。"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from examples.free_cash_flow import DATA_DIR, load_panels, market_snapshot
from src.strategy.free_cash_flow import FreeCashFlowParams, build_fundamentals, candidate_pool
from src.strategy.free_cash_flow_execution import constrained_weights, select_with_buffer
from src.utils.industry_history import build_industry_matrix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True, help='信息截止日期，使用不晚于此日期的最近行情')
    parser.add_argument('--output', type=Path, default=Path('data/free_cash_flow/research_selection_30.csv'))
    args = parser.parse_args()
    panels = load_panels('2025-09-01')
    eligible = panels['returns'].index[panels['returns'].index <= pd.Timestamp(args.as_of)]
    if eligible.empty:
        raise ValueError('指定截止日前无行情')
    cutoff = eligible[-1]
    basic = pd.read_parquet(DATA_DIR / 'reference/stock_basic.parquet').drop_duplicates('ts_code').set_index('ts_code')
    basic['list_date'] = pd.to_datetime(basic['list_date'], errors='coerce')
    members = pd.read_parquet(DATA_DIR / 'reference/citic_member_by_stock.parquet')
    raw = {}
    for table in ('income', 'cashflow', 'balancesheet'):
        files = sorted((DATA_DIR / 'financial' / table).glob('*.parquet'))
        frame = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
        for col in ('ann_date', 'f_ann_date', 'end_date'):
            value = pd.to_datetime(frame[col], errors='coerce')
            frame[col] = value.dt.tz_localize(None) if value.dt.tz is not None else value
        announcement = frame['ann_date'].fillna(frame['f_ann_date'])
        raw[table] = frame[announcement.notna() & (announcement <= cutoff) & frame.f_ann_date.notna() & (frame.f_ann_date <= cutoff)]
    fundamentals, annual = build_fundamentals(raw['income'], raw['cashflow'], raw['balancesheet'])
    market = market_snapshot(panels, basic, members, cutoff)
    matrix = build_industry_matrix(members, pd.DatetimeIndex([cutoff]))
    market['industry'] = matrix.loc[cutoff].reindex(market.index)
    pool = candidate_pool(cutoff, market, fundamentals, annual, FreeCashFlowParams())
    chosen = select_with_buffer(pool, 30, set(), 30)
    weights = constrained_weights(chosen, .10)
    output = chosen.loc[weights.index, ['composite', 'fcf_ttm', 'industry']].copy()
    output.insert(0, 'rank', range(1, len(output) + 1))
    output['target_weight'] = weights
    output['information_cutoff'] = cutoff.date().isoformat()
    output.index.name = 'symbol'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f'为避免覆盖已有数据，请指定新输出文件: {args.output}')
    output.to_csv(args.output)
    print(f'仅研究用途，行情及财务可见截止日 {cutoff.date()}，候选池 {len(pool)}，选中 {len(output)}；未生成订单')
    print(output.to_string())
    print(f'已保存: {args.output}')


if __name__ == '__main__':
    main()
