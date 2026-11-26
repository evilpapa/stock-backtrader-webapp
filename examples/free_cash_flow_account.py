"""自由现金流策略：不同持股数与 20 万元账户模拟（不会下单）。

python -m examples.free_cash_flow_account --output-dir examples/free_cash_flow/account_industry
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from src.datahub.duckdb_frames import frame_exists, frame_paths, read_frame, write_frame

from examples.free_cash_flow import DATA_DIR, _load_daily, load_panels, load_index, market_snapshot
from src.strategy.free_cash_flow import (FreeCashFlowParams, build_fundamentals, candidate_pool,
                                         performance, rebalance_dates, selection_cutoff)
from src.strategy.free_cash_flow_execution import ExecutionParams, constrained_weights, select_with_buffer, simulate
from src.utils.industry_history import build_industry_matrix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2014-01-02')
    parser.add_argument('--end', default='2026-10-30')
    parser.add_argument('--industry-members', type=Path, default=DATA_DIR / 'reference/citic_member_by_industry.duckdb')
    parser.add_argument('--output-dir', type=Path, default=Path('examples/free_cash_flow/account_industry'))
    args = parser.parse_args()
    params = FreeCashFlowParams()
    panels = load_panels('2012-10-01')
    trading_days = panels['returns'].index
    basic = read_frame(DATA_DIR / 'reference/stock_basic.duckdb').drop_duplicates('ts_code').set_index('ts_code')
    basic['list_date'] = pd.to_datetime(basic['list_date'], errors='coerce')
    if not frame_exists(args.industry_members):
        raise FileNotFoundError(f'缺少分行业成员缓存 {args.industry_members}；先运行 python -m scripts.fetch_citic_industry_history')
    members = read_frame(args.industry_members)
    # 原有财务构造将最新修订数回填至首次公告日。这里在每个截面先按公告日截断原始版本，
    # 再计算 TTM，避免使用已知晚于该截面的修订；供应商覆盖式修订仍无法从缓存恢复。
    raw = {}
    for name in ('income', 'cashflow', 'balancesheet'):
        files = frame_paths(DATA_DIR / 'financial' / name)
        raw[name] = pd.concat([read_frame(path) for path in files], ignore_index=True)
        for col in ('ann_date', 'f_ann_date', 'end_date'):
            values = pd.to_datetime(raw[name][col], errors='coerce')
            raw[name][col] = values.dt.tz_localize(None) if values.dt.tz is not None else values
    scenarios = {f'{n}只-原始': (n, False, False) for n in (20, 25, 30, 50, 100)}
    for n in (25, 30):
        scenarios[f'{n}只-约束'] = (n, True, False)
        scenarios[f'{n}只-约束缓冲'] = (n, True, True)
    targets = {s: {} for s in scenarios}
    industries = {}
    # 包含起点前最近一期调样，避免起点后首季一直空仓而与满仓指数比较。
    history_start = (pd.Timestamp(args.start) - pd.Timedelta(days=100)).strftime('%Y-%m-%d')
    candidate_dates = rebalance_dates(trading_days, history_start, args.end)
    previous = [d for d in candidate_dates if d < pd.Timestamp(args.start)]
    dates = ([previous[-1]] if previous else []) + [d for d in candidate_dates if d >= pd.Timestamp(args.start)]
    cutoffs = [selection_cutoff(trading_days, day) for day in dates]
    industry_matrix = build_industry_matrix(members, pd.DatetimeIndex(cutoffs))
    coverage = []
    # 第一天初始化需要此前最近一次调样。
    for day in dates:
        cutoff = selection_cutoff(trading_days, day)
        available = {}
        for name, frame in raw.items():
            announcement = frame['ann_date'].fillna(frame['f_ann_date'])
            available[name] = frame[announcement.notna() & (announcement <= cutoff) &
                                    frame['f_ann_date'].notna() & (frame['f_ann_date'] <= cutoff)]
        fundamentals, annual = build_fundamentals(available['income'], available['cashflow'], available['balancesheet'])
        market = market_snapshot(panels, basic, members, cutoff)
        # 时点矩阵缺失及互相冲突的行业保持未知，不使用未来分类回填。
        market['industry'] = industry_matrix.loc[cutoff].reindex(market.index)
        pool = candidate_pool(cutoff, market, fundamentals, annual, params)
        industries[day] = market['industry'].fillna('未知行业')
        coverage.append({'rebalance_date': day, 'cutoff_date': cutoff, 'market_count': len(market),
                         'market_known': int(market['industry'].notna().sum()), 'pool_count': len(pool),
                         'pool_known': int(pool['industry'].notna().sum())})
        for name, (n, constrained, buffered) in scenarios.items():
            old = set(next(reversed(targets[name].values())).index) if targets[name] else set()
            selected = select_with_buffer(pool, n, old if buffered else set(), 40 if buffered and n == 25 else 45 if buffered else n)
            targets[name][day] = constrained_weights(selected, .08 if constrained else .10,
                                                       .25 if constrained else None)
        print(day.date(), '候选', len(pool), flush=True)
    daily = _load_daily('daily', ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pre_close', 'vol'], args.start)
    prices = {name: daily.pivot_table(index='trade_date', columns='ts_code', values=col, aggfunc='last').reindex(trading_days)
              for name, col in [('open', 'open'), ('high', 'high'), ('low', 'low'), ('close', 'close'), ('pre_close', 'pre_close'), ('volume', 'vol')]}
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    write_frame(out / 'industry_matrix.duckdb', industry_matrix.reset_index())
    pd.DataFrame(coverage).to_csv(out / 'industry_coverage.csv', index=False)
    bench = load_index('932365CNY010.CSI')
    metrics, all_daily, all_orders, all_positions = [], [], [], []
    from src.trading.strategies import write_native_weights
    for name in scenarios:
        write_native_weights(targets[name], out / 'trading' / name / 'native_weights.csv')
        ledger, orders, positions = simulate(prices, targets[name], industries, args.start, args.end, ExecutionParams())
        ledger['return'] = ledger.nav.pct_change().fillna(ledger.nav.iloc[0] / 200_000 - 1)
        ledger['benchmark_return'] = bench.pct_change(fill_method=None).reindex(ledger.index)
        # 指数只有收盘序列：无法与账户首日开盘买入精确对齐，首日不纳入相对指标。
        ledger.loc[ledger.index[0], 'benchmark_return'] = np.nan
        ledger['scenario'] = name
        stats = performance(ledger['return'])
        paired = ledger[['return', 'benchmark_return']].dropna()
        relative = (1 + paired['return']) / (1 + paired['benchmark_return'])
        relative_nav = pd.concat([pd.Series([1.0]), relative.cumprod().reset_index(drop=True)], ignore_index=True)
        active = paired['return'] - paired['benchmark_return']
        stats.update(relative_annual=relative.prod() ** (252 / len(relative)) - 1 if len(relative) else np.nan,
                     information_ratio=active.mean() / active.std() * np.sqrt(252) if active.std() > 0 else np.nan,
                     relative_max_drawdown=-(relative_nav / relative_nav.cummax() - 1).min(),
                     scenario=name, total_fees=orders['commission'].sum(), stamp_duty=orders['stamp_duty'].sum(),
                     ending_cash=ledger.cash.iloc[-1], avg_cash_weight=(ledger.cash / ledger.nav).mean(),
                     orders=len(orders), max_stock_weight=positions.weight.max(),
                     max_industry_weight=positions.groupby(['date', 'industry']).weight.sum().max())
        metrics.append(stats)
        orders['scenario'] = name
        positions['scenario'] = name
        all_orders.append(orders)
        all_positions.append(positions)
        all_daily.append(ledger.reset_index())
    daily_out = pd.concat(all_daily, ignore_index=True)
    orders_out = pd.concat(all_orders, ignore_index=True)
    positions_out = pd.concat(all_positions, ignore_index=True)
    yearly = daily_out.groupby(['scenario', daily_out.date.dt.year]).apply(
        lambda x: pd.Series({'strategy': (1 + x['return']).prod() - 1,
                             'benchmark': (1 + x['benchmark_return'].dropna()).prod() - 1}), include_groups=False).reset_index()
    yearly['difference_pp'] = yearly.strategy - yearly.benchmark
    summary = pd.DataFrame(metrics).set_index('scenario')
    summary.to_csv(out / 'metrics.csv')
    yearly.to_csv(out / 'yearly.csv', index=False)
    daily_out.to_csv(out / 'daily.csv', index=False)
    orders_out.to_csv(out / 'orders.csv', index=False)
    positions_out.to_csv(out / 'positions.csv', index=False)
    industry = positions_out.groupby(['scenario', 'date', 'industry'], dropna=False).weight.sum().reset_index()
    industry.to_csv(out / 'industry_weights.csv', index=False)
    latest = orders_out.date.max()
    orders_out[orders_out.date == latest].to_csv(out / 'latest_rebalance_orders.csv', index=False)
    # 从空仓出发，以最近一期信号、其后第一个交易日开盘价，独立模拟投入 20 万元。
    signal = max(d for d in dates if d < pd.Timestamp(args.end))
    execution = trading_days[trading_days > signal][0]
    initial_orders, initial_positions = [], []
    for name in scenarios:
        _, order, position = simulate(prices, {signal: targets[name][signal]}, {signal: industries[signal]},
                                      str(execution.date()), str(execution.date()), ExecutionParams())
        order['scenario'] = name
        position['scenario'] = name
        initial_orders.append(order)
        initial_positions.append(position)
    pd.concat(initial_orders, ignore_index=True).to_csv(out / 'initial_orders_latest_signal.csv', index=False)
    pd.concat(initial_positions, ignore_index=True).to_csv(out / 'initial_positions_latest_signal.csv', index=False)
    print(summary.to_string())
    print('最近调仓模拟成交:', latest, '最近信号的空仓建仓模拟:', signal.date(), execution.date())


if __name__ == '__main__':
    main()
