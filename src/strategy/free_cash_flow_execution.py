"""20 万元账户的自由现金流组合实验；不发送交易订单。"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from src.utils.commission import ChinaStockCommission


@dataclass(frozen=True)
class ExecutionParams:
    initial_cash: float = 200_000.0
    commission: float = 0.0000854
    min_commission: float = 5.0
    stamp_duty: float = 0.0005  # 简化为全期间卖出千分之 0.5，非历史税率
    slippage: float = 0.001  # 买入加、卖出减，单边
    lot: int = 100


def select_with_buffer(pool: pd.DataFrame, size: int, previous: set[str], buffer: int) -> pd.DataFrame:
    """优先保留排名不低于 buffer 的老股，剩余名额按排名填入；总数不超过 size。"""
    ranked = pool.dropna(subset=['composite']).sort_values('composite', ascending=False, kind='stable')
    retained = [s for s in ranked.index[:buffer] if s in previous][:size]
    entrants = [s for s in ranked.index[:size] if s not in retained]
    chosen = retained + entrants[:size - len(retained)]
    return ranked.loc[chosen]


def constrained_weights(picked: pd.DataFrame, stock_cap: float | None = None,
                        industry_cap: float | None = None) -> pd.Series:
    """按 FCF 比例分配，迭代封顶；容量不足时保留现金，不突破约束。"""
    if picked.empty:
        return pd.Series(dtype=float)
    raw = picked['fcf_ttm'].clip(lower=0).fillna(0).astype(float)
    industry = picked['industry'].fillna('未知行业')
    result = pd.Series(0.0, index=picked.index)
    sc = stock_cap if stock_cap is not None else 1.0
    ic = industry_cap if industry_cap is not None else 1.0
    for _ in range(len(raw) + industry.nunique() + 2):
        room = (sc - result).clip(lower=0)
        group_room = (ic - result.groupby(industry).sum()).clip(lower=0)
        eligible = (room > 1e-12) & (industry.map(group_room) > 1e-12) & (raw > 0)
        remaining = 1.0 - result.sum()
        if remaining <= 1e-12 or not eligible.any():
            break
        proposal = raw.where(eligible, 0.0)
        proposal = proposal / proposal.sum() * remaining
        proposal = pd.concat([proposal, room], axis=1).min(axis=1)
        sums = proposal.groupby(industry).sum()
        factors = (group_room / sums.replace(0, np.nan)).clip(upper=1).fillna(0)
        proposal *= industry.map(factors)
        if proposal.sum() < 1e-12:
            break
        result += proposal
    return result[result > 1e-12]


def simulate(prices: dict[str, pd.DataFrame], targets: dict[pd.Timestamp, pd.Series],
             industries: dict[pd.Timestamp, pd.Series], start: str, end: str,
             params: ExecutionParams = ExecutionParams()):
    """调样日后首个交易日开盘执行，按 100 股取整，逐笔扣最低佣金。

    无公司行动明细时，将除权前市值按前收价等价折算成整手和现金；差额记为
    模拟现金调整，并非真实分红、送转或交易流水。持仓和成交严格为整手。
    无当日行情不交易；开盘接近前收 ±10% 时保守跳过（非真实涨跌停规则）。
    """
    dates = prices['close'].index
    dates = dates[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
    target_days = sorted(targets)
    if not len(dates):
        raise ValueError('没有指定区间的行情')
    effective = {}
    before = [d for d in target_days if d < dates[0]]
    if before:
        effective[dates[0]] = before[-1]
    for day in target_days:
        pos = dates.searchsorted(day, side='right')
        if day >= dates[0] and pos < len(dates):
            effective[dates[pos]] = day
    if params.lot <= 0:
        raise ValueError('交易单位必须为正')
    cash = params.initial_cash
    shares = pd.Series(dtype='int64')
    previous_close = pd.Series(dtype=float)
    daily, orders, positions = [], [], []
    commission_info = ChinaStockCommission(commission=params.commission, min_comm=params.min_commission)
    last_industry = pd.Series(dtype=object)
    for day in dates:
        close = prices['close'].loc[day]
        opening = prices['open'].loc[day]
        pre = prices['pre_close'].loc[day]
        volume = prices['volume'].loc[day]
        # 除权代理：以昨收/今前收折算理论份额，向下取整手，其余等价价值记入现金。
        # 没有事件明细时这不是实际送转及分红；价格误差在半分内视为无除权。
        corporate_action_cash = 0.0
        if not shares.empty:
            old_price = previous_close.reindex(shares.index)
            reference = pre.reindex(shares.index)
            changed = old_price.notna() & reference.notna() & (old_price > 0) & (reference > 0)
            changed &= (old_price - reference).abs() > 0.0051
            if changed.any():
                theoretical = shares[changed] * old_price[changed] / reference[changed]
                rounded = (np.floor(theoretical / params.lot + 1e-10) * params.lot).astype('int64')
                corporate_action_cash = float(((theoretical - rounded) * reference[changed]).sum())
                cash += corporate_action_cash
                shares.loc[changed] = rounded
                shares = shares[shares > 0]
        if day in effective:
            signal_day = effective[day]
            target = targets[signal_day]
            last_industry = industries[signal_day]
            mark = opening.reindex(shares.index).fillna(previous_close.reindex(shares.index))
            equity = cash + (shares * mark).sum()
            all_symbols = shares.index.union(target.index)
            for side in ('sell', 'buy'):
                for symbol in all_symbols:
                    p = opening.get(symbol, np.nan)
                    pc = pre.get(symbol, np.nan)
                    vol = volume.get(symbol, np.nan)
                    current = int(shares.get(symbol, 0))
                    desired = equity * target.get(symbol, 0.0)
                    if not (pd.notna(p) and p > 0 and pd.notna(vol) and vol > 0):
                        continue
                    delta = desired - current * p
                    if (side == 'sell' and delta >= 0) or (side == 'buy' and delta <= 0):
                        continue
                    # 仅使用开盘时已知信息：涨跌接近 10% 时保守地不买/卖。
                    # 并非真实涨跌停规则，ST、科创板等尤其需要单独行情核对。
                    if pd.notna(pc) and pc > 0:
                        move = p / pc - 1
                        if (side == 'buy' and move >= .098) or (side == 'sell' and move <= -.098):
                            continue
                    if side == 'sell':
                        qty = min(current, int(np.floor((-delta / p) / params.lot)) * params.lot)
                        if desired == 0:
                            qty = current
                        fill = p * (1 - params.slippage)
                    else:
                        fill = p * (1 + params.slippage)
                        qty = int(np.floor((delta / fill) / params.lot)) * params.lot
                        while qty > 0 and qty * fill + max(qty * fill * params.commission, params.min_commission) > cash + 1e-8:
                            qty -= params.lot
                    if qty <= 0:
                        continue
                    amount = qty * fill
                    fee = commission_info.getcommission(qty if side == 'buy' else -qty, fill)
                    tax = amount * params.stamp_duty if side == 'sell' else 0.0
                    if side == 'sell':
                        cash += amount - fee - tax
                        shares.loc[symbol] = current - qty
                    else:
                        cash -= amount + fee
                        shares.loc[symbol] = current + qty
                    orders.append(dict(date=day, signal_date=signal_day, symbol=symbol, side=side,
                                       quantity=qty, open=p, price=fill, amount=amount, commission=fee, stamp_duty=tax))
            shares = shares[shares > 1e-8]
            marks = opening.reindex(shares.index).fillna(previous_close.reindex(shares.index))
            nav = cash + (shares * marks).sum()
            for symbol, qty in shares.items():
                positions.append(dict(date=day, signal_date=signal_day, symbol=symbol, shares=qty,
                                      price=marks[symbol], market_value=qty * marks[symbol], weight=qty * marks[symbol] / nav,
                                      industry=last_industry.get(symbol, '未知行业'), target_weight=target.get(symbol, 0.0)))
        previous_close = close.reindex(shares.index).combine_first(previous_close.reindex(shares.index))
        nav = cash + (shares * previous_close).sum()
        daily.append(dict(date=day, nav=nav, cash=cash, holdings=len(shares),
                          corporate_action_cash=corporate_action_cash))
    return pd.DataFrame(daily).set_index('date'), pd.DataFrame(orders), pd.DataFrame(positions)
