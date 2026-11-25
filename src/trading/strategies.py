"""Strategy catalog and adapters from native signals to executable portfolios.

No adapter infers symbols from display names, guesses exchange holidays, or
turns a research index into a traded security. Callers supply those mappings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from src.datahub.ticker import TickerMapper
from .targets import TargetPortfolio, write_targets


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    title: str
    kind: str
    class_name: str | None = None


STRATEGIES = {
    spec.strategy_id: spec for spec in (
        StrategySpec("ma", "单均线", "backtrader", "MaStrategy"),
        StrategySpec("macross", "双均线", "backtrader", "MaCrossStrategy"),
        StrategySpec("etf_momentum", "ETF动量", "backtrader", "EtfMomentumStrategy"),
        StrategySpec("qb_etf_momentum", "QB ETF动量", "backtrader", "QbEtfMomentumStrategy"),
        StrategySpec("leading_rotation", "龙头轮动", "backtrader", "LeadingRotationStrategy"),
        StrategySpec("sector_rotation", "行业轮动", "backtrader", "SectorRotationStrategy"),
        StrategySpec("small_cap", "小市值", "backtrader", "SmallCapStrategy"),
        StrategySpec("mysterious_spiral", "神秘螺旋", "backtrader", "MysteriousSpiralStrategy"),
        StrategySpec("turtle_trading", "海龟交易（现金多头）", "backtrader", "TurtleTradingStrategy"),
        StrategySpec("equal_weight", "等权持有", "backtrader", "EqualWeightStrategy"),
        StrategySpec("just_buy_hold", "买入持有", "backtrader", "JustBuyHoldStrategy"),
        StrategySpec("sector_rotation_dual", "双轮行业ETF", "dual"),
        StrategySpec("micro_cap_timing_plus", "微盘择时增强", "timing"),
        StrategySpec("free_cash_flow", "自由现金流", "weights"),
        StrategySpec("free_cash_flow_account", "自由现金流约束账户", "weights"),
        StrategySpec("intraday46", "46因子中证500", "targets"),
    )
}


def strategy_spec(strategy_id):
    try:
        return STRATEGIES[strategy_id]
    except KeyError as exc:
        raise ValueError(f"unknown strategy {strategy_id!r}; choose from {', '.join(STRATEGIES)}") from exc


def trading_calendar(calendar) -> pd.DatetimeIndex:
    days = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    if days.empty or days.hasnans or days.has_duplicates or days.tz is not None:
        raise ValueError("calendar must contain unique, timezone-naive trading dates")
    return days.sort_values()


def next_trade_date(signal_date, calendar):
    days = trading_calendar(calendar)
    day = pd.Timestamp(signal_date).normalize()
    if day not in days:
        raise ValueError(f"signal date is not in trading calendar: {day.date()}")
    following = days[days > day]
    if following.empty:
        raise ValueError(f"calendar needs a trading date after signal {day.date()}")
    return following[0].date().isoformat()


def mapped_weights(weights: Mapping, symbol_map=None):
    symbol_map = symbol_map or {}
    result = {}
    for name, weight in weights.items():
        weight = float(weight)
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("cash execution does not support short/nonfinite weights")
        if weight == 0:
            continue
        symbol = TickerMapper.normalize(symbol_map.get(name, name))
        if symbol in result:
            raise ValueError(f"multiple asset names map to the same security: {symbol}")
        result[symbol] = weight
    if sum(result.values()) > 1 + 1e-8:
        raise ValueError("cash execution does not support leveraged target weights")
    return result


def weight_targets(strategy_id, weights_by_date, calendar, *, symbol_map=None):
    """Unshifted close-time target weights, including explicit empty portfolios."""
    strategy_spec(strategy_id)
    days = trading_calendar(calendar)
    result = []
    seen = set()
    for day, weights in sorted(weights_by_date.items(), key=lambda pair: pd.Timestamp(pair[0])):
        signal = pd.Timestamp(day).date().isoformat()
        if signal in seen:
            raise ValueError(f"duplicate signal date: {signal}")
        seen.add(signal)
        result.append(TargetPortfolio(strategy_id, signal, next_trade_date(signal, days),
                                      mapped_weights(weights, symbol_map)))
    return result


def record_order_intent(strategy, order):
    """Called at submission time, before any future bar or simulated fill.

    Native target-weight histories take precedence on rebalance dates. This
    fallback covers fixed-size MA orders, pyramiding and risk/avoid-month exits.
    It records intended post-order exposure, never a future realized holding.
    """
    if order is None:
        return
    if not hasattr(strategy, "execution_order_history"):
        strategy.execution_order_history = {}
        strategy._execution_order_refs = set()
    if order.ref in strategy._execution_order_refs:
        return
    strategy._execution_order_refs.add(order.ref)
    in_open = getattr(strategy, "_execution_in_open", False)
    day = strategy.datas[0].datetime.date(-1 if in_open else 0).isoformat()
    history = strategy.execution_order_history
    if day not in history:
        equity = float(strategy.broker.getvalue())
        history[day] = {"equity": equity, "sizes": {
            data._name: float(strategy.getposition(data).size) for data in strategy.datas},
            "prices": {data._name: float(data.open[0] if in_open else data.close[0]) for data in strategy.datas}}
    snapshot = history[day]
    name = order.data._name
    snapshot["sizes"][name] += float(order.created.size)


def backtrader_targets(strategy, calendar, *, strategy_id=None, symbol_map=None):
    if strategy_id is None:
        matches = [spec.strategy_id for spec in STRATEGIES.values()
                   if spec.class_name and any(cls.__name__ == spec.class_name for cls in type(strategy).__mro__)]
        if len(matches) != 1:
            raise ValueError("supply a registered strategy_id")
        strategy_id = matches[0]
    spec = strategy_spec(strategy_id)
    if spec.kind != "backtrader":
        raise ValueError("strategy is not a Backtrader strategy")
    if not any(cls.__name__ == spec.class_name for cls in type(strategy).__mro__):
        raise ValueError("strategy class does not match strategy_id")
    if strategy_id == "turtle_trading" and strategy.p.allow_short:
        raise ValueError("cash execution requires TurtleTradingStrategy(allow_short=False)")
    names = [data._name for data in strategy.datas]
    if len(names) != len(set(names)):
        raise ValueError("data feeds need unique names")
    native = {}
    for row in getattr(strategy, "rebalance_history", []):
        weights = row.get("target_weights_by_name")
        if weights is None:
            weights = row.get("target_weights", row.get("weights"))
        if weights is None:
            continue
        if not isinstance(weights, Mapping):
            if len(weights) != len(names):
                raise ValueError("target array does not match feed names")
            weights = dict(zip(names, weights))
        signal = pd.Timestamp(row.get("signal_date", row.get("date"))).date().isoformat()
        if "execution_date" in row and next_trade_date(signal, calendar) != str(row["execution_date"]):
            raise ValueError("native execution date differs from trading calendar")
        native[signal] = dict(weights)
    for day, row in getattr(strategy, "execution_order_history", {}).items():
        if day in native:
            continue
        if not math.isfinite(row["equity"]) or row["equity"] <= 0:
            raise ValueError("invalid signal-time equity")
        native[day] = {name: size * row["prices"][name] / row["equity"]
                       for name, size in row["sizes"].items() if size != 0}
    return weight_targets(strategy_id, native, calendar, symbol_map=symbol_map)


def export_backtrader_targets(strategy, calendar, output_path, *, strategy_id=None, symbol_map=None):
    return write_targets(backtrader_targets(strategy, calendar, strategy_id=strategy_id,
                                            symbol_map=symbol_map), output_path)


def dual_rotation_targets(result, calendar, *, symbol_map=None):
    """Combine overlapping positive/reverse baskets using native allocation w."""
    weights = {}
    for day, baskets in result.holdings.items():
        w = float(result.weights.loc[day, "w"])
        if not math.isfinite(w) or not 0 <= w <= 1:
            raise ValueError("invalid dual rotation allocation")
        combined = {}
        for codes, allocation in ((baskets["pos"], w), (baskets["rev"], 1 - w)):
            if len(codes) != len(set(codes)):
                raise ValueError("duplicate ETF in basket")
            for code in codes:
                combined[code] = combined.get(code, 0.) + allocation / len(codes)
        weights[day] = combined
    return weight_targets("sector_rotation_dual", weights, calendar, symbol_map=symbol_map)


def dual_rotation_latest_target(strategy, data, calendar, *, symbol_map=None):
    """Export the original latest_target, with the actual next session date."""
    native = strategy.latest_target(data)
    signal = pd.Timestamp(native["signal_date"])
    trade = next_trade_date(signal, calendar)
    if signal.to_period("W-SUN") == pd.Timestamp(trade).to_period("W-SUN"):
        raise ValueError("latest dual signal must be the final trading session of its week")
    return weight_targets("sector_rotation_dual", {signal: native["target"]}, calendar,
                          symbol_map=symbol_map)[0]


def timing_targets(positions, constituents, calendar):
    """Apply the unshifted timing exposure to an explicit investable basket.

    constituents is a mapping of signal dates to symbol weights, or a DataFrame
    indexed by signal date. An abstract microcap index is never sent as a stock.
    """
    if positions.index.has_duplicates:
        raise ValueError("duplicate timing date")
    baskets = constituents.to_dict(orient="index") if isinstance(constituents, pd.DataFrame) else constituents
    baskets = {pd.Timestamp(day).normalize(): weights for day, weights in baskets.items()}
    weights = {}
    for day, exposure in positions.items():
        day = pd.Timestamp(day).normalize()
        exposure = float(exposure)
        if not math.isfinite(exposure) or not 0 <= exposure <= 1:
            raise ValueError("invalid timing exposure")
        if not exposure:
            weights[day] = {}
            continue
        if day not in baskets:
            raise ValueError(f"missing point-in-time constituent basket: {day.date()}")
        basket = mapped_weights(baskets[day])
        if not basket:
            raise ValueError("positive timing exposure requires constituents")
        weights[day] = {code: exposure * weight for code, weight in basket.items()}
    return weight_targets("micro_cap_timing_plus", weights, calendar)


def write_native_weights(weights_by_date, path):
    """Export unshifted native portfolios, preserving all-cash signal dates."""
    from pathlib import Path

    rows = []
    for day, weights in weights_by_date.items():
        weights = mapped_weights(weights)
        for symbol, weight in (weights or {"": 0.}).items():
            rows.append({"date": pd.Timestamp(day).date().isoformat(), "symbol": symbol, "weight": weight})
    if not rows:
        raise ValueError("no native target portfolios")
    frame = pd.DataFrame(rows)
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("duplicate native target/date")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def to_backtrader_ohlcv(raw):
    """Adapt normalized DataHub bars without changing units or adjustment.

    Keep amount for SmallCapPandasData and attrs for source/version tracing.
    """
    frame = raw.copy()
    required = ["open", "high", "low", "close", "volume"]
    if set(required) - set(frame) or frame.empty:
        raise ValueError("normalized OHLCV columns are required")
    values = frame["date"] if "date" in frame else frame["datetime"] if "datetime" in frame else frame.index
    if pd.api.types.is_numeric_dtype(values):
        values = values.astype(str)
    dates = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    if dates.tz is not None:
        dates = dates.tz_convert("Asia/Shanghai").tz_localize(None)
    dates = dates.normalize()
    if dates.hasnans or dates.has_duplicates:
        raise ValueError("one daily bar per symbol/session is required")
    frame["date"] = dates
    frame.index = dates
    extra = ["amount"] if "amount" in frame else []
    result = frame[["date", *required, *extra]].sort_index()
    result.attrs.update(raw.attrs)
    return result


def run_backtrader_signals(strategy_id, price_data, calendar, *, params=None, initial_cash=1_000_000.,
                           stake=100, symbol_map=None):
    """Run original strategy code on supplied OHLCV; return next-session signals.

    price_data is already acquired/normalized by DataHub, or synthetic in tests.
    Supply the full trading calendar, including the session after the final bar.
    """
    import backtrader as bt
    import src.strategy as strategy_module
    from src.strategy.small_cap import SmallCapPandasData
    from src.utils.commission import ChinaStockCommission

    spec = strategy_spec(strategy_id)
    if spec.kind != "backtrader":
        raise ValueError("use the native adapter for this strategy")
    params = dict(params or {})
    if strategy_id == "turtle_trading" and params.get("allow_short") is not False:
        raise ValueError("set allow_short=False explicitly for cash execution")
    if not price_data:
        raise ValueError("price_data is required")
    if not math.isfinite(initial_cash) or initial_cash <= 0 or stake <= 0:
        raise ValueError("positive initial cash and stake are required")
    days = trading_calendar(calendar)
    cerebro = bt.Cerebro(stdstats=False, cheat_on_open=strategy_id == "mysterious_spiral")
    for name, raw in price_data.items():
        frame = to_backtrader_ohlcv(raw)
        if not frame.index.isin(days).all():
            raise ValueError("price dates are absent from trading calendar")
        frame = frame.sort_index()
        feed = SmallCapPandasData if strategy_id == "small_cap" else bt.feeds.PandasData
        cerebro.adddata(feed(dataname=frame), name=name)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.addcommissioninfo(ChinaStockCommission())
    cerebro.addsizer(bt.sizers.FixedSize, stake=stake)
    cerebro.addstrategy(getattr(strategy_module, spec.class_name), **params)
    strategy = cerebro.run()[0]
    return backtrader_targets(strategy, days, strategy_id=strategy_id, symbol_map=symbol_map)
