# coding: gbk

"""
QMT ETF momentum rotation strategy.

This script ports the existing ETF momentum idea into the QMT lifecycle:
- init(ContextInfo)
- handlebar(ContextInfo)
- stop(ContextInfo)

The strategy:
1. Pulls daily close data with ContextInfo.get_market_data_ex().
2. Computes N-day average return and N-day volatility.
3. Uses risk-adjusted momentum = momentum / volatility.
4. Keeps only symbols with positive risk-adjusted momentum.
5. Rebalances with order_target_percent().

The file is ASCII-only so the GBK header stays valid for QMT.
"""

import numpy as np
import pandas as pd


DEFAULT_SYMBOLS = [
    "513100.SH",
    "510300.SH",
    "518880.SH",
]

DEFAULT_SYMBOL_NAMES = {
    "513100.SH": "NASDAQ_ETF",
    "510300.SH": "CSI300_ETF",
    "518880.SH": "GOLD_ETF",
}

MOMENTUM_WINDOW = 20
REBALANCE_DAYS = 1
PRICE_PERIOD = "1d"
DIVIDEND_TYPE = "front"
ORDER_STYLE = "LATEST"
ACCOUNT_ID = ""
MIN_VOLATILITY = 1e-8


def init(ContextInfo):
    ContextInfo.symbols = list(DEFAULT_SYMBOLS)
    ContextInfo.symbol_names = dict(DEFAULT_SYMBOL_NAMES)
    ContextInfo.momentum_window = MOMENTUM_WINDOW
    ContextInfo.rebalance_days = REBALANCE_DAYS
    ContextInfo.price_period = PRICE_PERIOD
    ContextInfo.dividend_type = DIVIDEND_TYPE
    ContextInfo.order_style = ORDER_STYLE
    ContextInfo.account_id = ACCOUNT_ID
    ContextInfo.rebalance_counter = 0
    ContextInfo.latest_scores = {}
    ContextInfo.latest_momentum = {}
    ContextInfo.latest_weights = {}
    ContextInfo.rebalance_log = []

    ContextInfo.set_universe(ContextInfo.symbols)
    if ContextInfo.account_id:
        ContextInfo.set_account(ContextInfo.account_id)

    _log(
        "init complete: symbols={0}, momentum_window={1}, rebalance_days={2}".format(
            ",".join(ContextInfo.symbols),
            ContextInfo.momentum_window,
            ContextInfo.rebalance_days,
        )
    )


def handlebar(ContextInfo):
    if not ContextInfo.is_new_bar():
        return

    if ContextInfo.barpos < ContextInfo.momentum_window:
        return

    ContextInfo.rebalance_counter += 1
    if ContextInfo.rebalance_counter < ContextInfo.rebalance_days:
        return
    ContextInfo.rebalance_counter = 0

    price_frames = _fetch_price_frames(ContextInfo)
    target_weights = _build_target_weights(ContextInfo, price_frames)

    for symbol in ContextInfo.symbols:
        if _is_suspended(ContextInfo, symbol):
            _log("skip suspended symbol: {0}".format(symbol))
            continue
        _submit_target_weight(ContextInfo, symbol, target_weights.get(symbol, 0.0))

    ContextInfo.latest_weights = dict(target_weights)
    ContextInfo.rebalance_log.append(
        {
            "barpos": ContextInfo.barpos,
            "weights": dict(target_weights),
            "scores": dict(ContextInfo.latest_scores),
            "momentum": dict(ContextInfo.latest_momentum),
        }
    )

    _log(
        "rebalance bar={0} weights={1}".format(
            ContextInfo.barpos,
            _format_weights(ContextInfo.latest_weights),
        )
    )


def stop(ContextInfo):
    _log(
        "stop called: last_weights={0}".format(
            _format_weights(getattr(ContextInfo, "latest_weights", {}))
        )
    )


def _fetch_price_frames(ContextInfo):
    return ContextInfo.get_market_data_ex(
        fields=["close"],
        stock_code=ContextInfo.symbols,
        period=ContextInfo.price_period,
        start_time="",
        end_time="",
        count=ContextInfo.momentum_window + 2,
        dividend_type=ContextInfo.dividend_type,
        fill_data=True,
        subscribe=True,
    )


def _build_target_weights(ContextInfo, price_frames):
    drop_last_bar = ContextInfo.is_last_bar()
    candidates = []
    target_weights = {}
    latest_scores = {}
    latest_momentum = {}

    for symbol in ContextInfo.symbols:
        target_weights[symbol] = 0.0
        data_frame = price_frames.get(symbol)
        close_series = _extract_close_series(data_frame, drop_last_bar)

        if len(close_series) < ContextInfo.momentum_window + 1:
            latest_scores[symbol] = 0.0
            latest_momentum[symbol] = 0.0
            continue

        returns = close_series.pct_change().dropna().tail(ContextInfo.momentum_window)
        if len(returns) < ContextInfo.momentum_window:
            latest_scores[symbol] = 0.0
            latest_momentum[symbol] = 0.0
            continue

        momentum = float(returns.mean())
        volatility = float(np.std(returns.values, ddof=0))
        if not np.isfinite(momentum) or not np.isfinite(volatility):
            latest_scores[symbol] = 0.0
            latest_momentum[symbol] = 0.0
            continue

        score = 0.0
        if volatility > MIN_VOLATILITY:
            score = momentum / volatility

        latest_scores[symbol] = score
        latest_momentum[symbol] = momentum

        if score > 0.0:
            candidates.append((symbol, score))

    total_score = sum(score for _, score in candidates)
    if total_score > 0.0:
        for symbol, score in candidates:
            target_weights[symbol] = score / total_score

    ContextInfo.latest_scores = latest_scores
    ContextInfo.latest_momentum = latest_momentum
    return target_weights


def _extract_close_series(data_frame, drop_last_bar):
    if data_frame is None:
        return pd.Series(dtype="float64")
    if "close" not in data_frame.columns:
        return pd.Series(dtype="float64")

    close_series = pd.to_numeric(data_frame["close"], errors="coerce").dropna()
    if drop_last_bar and len(close_series) > 0:
        close_series = close_series.iloc[:-1]
    return close_series


def _submit_target_weight(ContextInfo, symbol, target_weight):
    target_weight = float(max(0.0, min(1.0, target_weight)))
    order_func = globals().get("order_target_percent")
    if order_func is None:
        raise RuntimeError("QMT function order_target_percent is not available.")

    if ContextInfo.account_id:
        order_func(
            symbol,
            target_weight,
            ContextInfo.order_style,
            ContextInfo,
            ContextInfo.account_id,
        )
    else:
        order_func(
            symbol,
            target_weight,
            ContextInfo.order_style,
            ContextInfo,
        )


def _is_suspended(ContextInfo, symbol):
    checker = getattr(ContextInfo, "is_suspended_stock", None)
    if checker is None:
        return False

    try:
        return bool(checker(symbol))
    except Exception:
        return False


def _format_weights(weights):
    parts = []
    for symbol in sorted(weights.keys()):
        parts.append("{0}:{1:.2%}".format(symbol, weights[symbol]))
    return ", ".join(parts)


def _log(message):
    print("[etf_momentum_qmt] {0}".format(message))
