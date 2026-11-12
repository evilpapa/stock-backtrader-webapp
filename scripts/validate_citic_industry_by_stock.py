"""比较逐股与逐行业拉取的行业时点矩阵；未知/冲突保持缺失。"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from scripts.fetch_citic_industry_by_stock import REF, OUTPUT
from src.utils.industry_history import build_industry_matrix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2013-12-31')
    parser.add_argument('--end', default='2025-12-31')
    parser.add_argument('--out', type=Path, default=Path('examples/free_cash_flow/industry_validation'))
    args = parser.parse_args()
    old = pd.read_parquet(REF / 'citic_member_by_industry.parquet')
    new = pd.read_parquet(OUTPUT)
    basic = pd.read_parquet(REF / 'stock_basic.parquet').drop_duplicates('ts_code').set_index('ts_code')
    listed = pd.to_datetime(basic['list_date'], errors='coerce')
    delisted = pd.to_datetime(basic['delist_date'], errors='coerce')
    dates = pd.date_range(args.start, args.end, freq='YE')
    by_industry = build_industry_matrix(old, dates)
    by_stock = build_industry_matrix(new, dates)
    codes = basic.index.union(by_stock.columns).union(by_industry.columns)
    by_industry = by_industry.reindex(columns=codes)
    by_stock = by_stock.reindex(columns=codes)
    rows = []
    for day in dates:
        eligible = basic.index[(listed <= day) & (delisted.isna() | (delisted > day))]
        left, right = by_industry.loc[day].reindex(eligible), by_stock.loc[day].reindex(eligible)
        both = left.notna() & right.notna()
        rows.append({'date': day, 'listed_universe': len(eligible), 'industry_known': left.notna().sum(),
                     'stock_known': right.notna().sum(), 'only_stock': (left.isna() & right.notna()).sum(),
                     'only_industry': (left.notna() & right.isna()).sum(),
                     'different': (both & left.ne(right)).sum()})
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    by_stock.to_parquet(out / 'industry_matrix_by_stock.parquet')
    pd.DataFrame(rows).to_csv(out / 'year_end_coverage.csv', index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    main()
