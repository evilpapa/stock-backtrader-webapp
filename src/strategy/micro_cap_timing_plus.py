"""微盘股择时增强策略（华福证券 2026-08-11《微盘股择时——有效识别顶部风险&底部机遇的增强策略》）。

三层优先级：底部启动确认（持有 20 日）> 顶部风险退出（空仓 10 日）> MA15 趋势锚。
信号以 t 日收盘判断、t+1 日开盘执行，单边成本千一。纯 pandas 向量化实现，不依赖 Backtrader。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MicroCapTimingParams:
    ma_window: int = 15
    # 普通底部
    oversold_lookback: int = 10
    dd60_max: float = -0.10
    ma_distance_max: float = -0.03
    rsi_window: int = 7
    rsi_max: float = 45.0
    flow_breadth_min: float = 0.55
    flow_improvement_min: float = 0.05
    main_net_ratio_min: float = 0.0
    confirm_high_calm: int = 3  # 小盘占优：突破前 3 日高点
    confirm_high_defensive: int = 5  # 大盘占优：突破前 5 日高点
    bottom_hold_days: int = 20
    # 危机底部
    crisis_drop_5d: float = -0.10
    crisis_atr_window: int = 20
    crisis_atr_expand: float = 0.20
    crisis_dd60_max: float = -0.35
    crisis_ma_distance_max: float = -0.20
    crisis_rsi_max: float = 30.0
    crisis_flow_breadth_min: float = 0.40
    crisis_day_return_min: float = 0.05
    # 顶部
    diffusion_high: float = 0.85
    diffusion_drop: float = 0.05
    diffusion_lookback: int = 20
    top_lock_days: int = 10
    cost: float = 0.001


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    # 研报文字写简单均值，但与其披露的 RSI 数值对账后为 Wilder 平滑（7 日 MAD 0.47 vs SMA 7.8）
    avg_up = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    avg_down = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    return 100 - 100 / (1 + avg_up / avg_down.replace(0, np.nan))


def compute_signals(index: pd.DataFrame, factors: pd.DataFrame, style_gap: pd.Series,
                    params: MicroCapTimingParams = MicroCapTimingParams()) -> pd.DataFrame:
    """输出逐日指标与 ma / bottom / crisis / top 原始触发信号（均为 t 日收盘可得）。

    style_gap: 大盘相对小盘过去 20 日收益差（大盘 - 小盘）。
    """
    p = params
    close, high = index["close"], index["high"]
    frame = pd.DataFrame(index=index.index)
    frame["close"] = close
    frame["ma"] = close.rolling(p.ma_window).mean()
    frame["ma_distance"] = close / frame["ma"] - 1
    frame["dd60"] = close / close.rolling(60, min_periods=20).max() - 1
    frame["rsi"] = _rsi(close, p.rsi_window)
    frame["ret_1d"] = close.pct_change(fill_method=None)
    frame["ret_5d"] = close.pct_change(5, fill_method=None)

    # 资金流：广度 2 日均值、相对前 5 日均值（不含当日）的改善、主力净流入率 2 日均值
    breadth, ratio = factors["flow_breadth"], factors["main_net_ratio"]
    frame["flow_breadth"] = breadth
    frame["breadth_2d"] = breadth.rolling(2).mean()
    frame["flow_improvement"] = breadth - breadth.shift(1).rolling(5).mean()
    frame["main_net_ratio"] = ratio
    frame["main_net_2d"] = ratio.rolling(2).mean()
    frame["main_net_5d_change"] = ratio - ratio.shift(1).rolling(5).mean()
    frame["diffusion"] = factors["diffusion"]
    frame["diffusion_5d_change"] = factors["diffusion"] - factors["diffusion"].shift(1).rolling(5).mean()
    frame["diffusion_max"] = factors["diffusion"].rolling(p.diffusion_lookback).max()
    frame["style_gap"] = style_gap
    frame["style_gap_ma5"] = style_gap.rolling(5).mean()

    # 普通底部：10 日超跌记忆 + 资金 + 价格确认（大盘占优时提高到前 5 日高点）
    oversold = (frame["dd60"] <= p.dd60_max) & (frame["ma_distance"] <= p.ma_distance_max) & (frame["rsi"] <= p.rsi_max)
    memory = oversold.astype(float).rolling(p.oversold_lookback, min_periods=1).max() > 0
    flow_ok = (
        (frame["breadth_2d"] >= p.flow_breadth_min)
        & (frame["flow_improvement"] >= p.flow_improvement_min)
        & (frame["main_net_2d"] > p.main_net_ratio_min)
    )
    prior_high_3 = high.shift(1).rolling(p.confirm_high_calm).max()
    prior_high_5 = high.shift(1).rolling(p.confirm_high_defensive).max()
    defensive = frame["style_gap_ma5"] > 0
    frame["prior_high_3"], frame["prior_high_5"] = prior_high_3, prior_high_5
    price_ok = close > np.where(defensive, prior_high_5, prior_high_3)
    frame["bottom"] = memory & flow_ok & price_ok

    # 危机底部：近 10 日内出现 5 日急跌且 ATR 扩张，叠加极端超跌，首日大涨放行
    prev_close = close.shift(1)
    low_proxy = index["low"]
    tr = pd.concat([high - low_proxy, (high - prev_close).abs(), (low_proxy - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(p.crisis_atr_window).mean()
    frame["atr_change"] = atr / atr.shift(5) - 1
    stress = ((frame["ret_5d"] <= p.crisis_drop_5d) & (frame["atr_change"] >= p.crisis_atr_expand)).astype(float)
    stress = stress.rolling(p.oversold_lookback, min_periods=1).max() > 0
    deep = (
        (frame["dd60"] <= p.crisis_dd60_max)
        & (frame["ma_distance"] <= p.crisis_ma_distance_max)
        & (frame["rsi"] <= p.crisis_rsi_max)
    ).astype(float).rolling(p.oversold_lookback, min_periods=1).max() > 0
    crisis_flow = (
        (frame["flow_breadth"] >= p.crisis_flow_breadth_min)
        & (frame["flow_improvement"] >= p.flow_improvement_min)
        & (frame["main_net_ratio"] >= 0)
    )
    frame["crisis"] = stress & deep & crisis_flow & (frame["ret_1d"] >= p.crisis_day_return_min)

    # 顶部：扩散曾达高位 + 5 日显著回落 + 资金广度或主力净流入率走弱
    flow_bad = (frame["flow_improvement"] < 0) | (frame["main_net_5d_change"] < 0)
    frame["top"] = (
        (frame["diffusion_max"] >= p.diffusion_high) & (frame["diffusion_5d_change"] <= -p.diffusion_drop) & flow_bad
    )
    return frame


def build_positions(signals: pd.DataFrame, params: MicroCapTimingParams = MicroCapTimingParams(), *,
                    use_bottom: bool = True, use_top: bool = True) -> pd.Series:
    """状态机：返回 t 日收盘决定、t+1 开盘生效的目标仓位（0/1）。

    底部触发 → 强制持有 bottom_hold_days（期间忽略其他信号）；
    顶部触发 → 强制空仓 top_lock_days（期间忽略后续顶部信号，但底部可覆盖）；否则按 MA 趋势。
    """
    p = params
    bottom = (signals["bottom"] | signals["crisis"]).to_numpy() & use_bottom
    top = signals["top"].to_numpy() & use_top
    trend = (signals["close"] > signals["ma"]).to_numpy()
    position = np.zeros(len(signals))
    hold_left = lock_left = 0
    for i in range(len(signals)):
        if hold_left > 0:
            hold_left -= 1
            position[i] = 1
            continue
        if bottom[i]:
            hold_left = p.bottom_hold_days - 1
            lock_left = 0
            position[i] = 1
        elif lock_left > 0:
            lock_left -= 1
            position[i] = 0
        elif top[i]:
            lock_left = p.top_lock_days - 1
            position[i] = 0
        else:
            position[i] = float(trend[i])
    return pd.Series(position, index=signals.index, name="position")


def backtest(index: pd.DataFrame, position: pd.Series, cost: float = 0.001) -> pd.Series:
    """t 日仓位于 t+1 开盘执行：隔夜段按旧仓位，日内段按新仓位，换仓扣单边成本。"""
    pos_new = position.shift(1).fillna(0.0)  # t 日持有的仓位（t-1 收盘决定）
    pos_old = pos_new.shift(1).fillna(0.0)
    prev_close = index["close"].shift(1)
    overnight = index["open"] / prev_close - 1
    intraday = index["close"] / index["open"] - 1
    turnover = (pos_new - pos_old).abs()
    ret = pos_old * overnight + pos_new * intraday - turnover * cost
    return ret.iloc[1:].rename("strategy_return")


def performance(returns: pd.Series, periods: int = 252) -> dict[str, float]:
    nav = (1 + returns).cumprod()
    years = len(returns) / periods
    annual = nav.iloc[-1] ** (1 / years) - 1
    vol = returns.std() * np.sqrt(periods)
    drawdown = (nav / nav.cummax() - 1).min()
    return {
        "年化收益": annual,
        "年化波动": vol,
        "夏普比率": annual / vol if vol else np.nan,
        "最大回撤": -drawdown,
        "卡玛比率": annual / -drawdown if drawdown else np.nan,
        "累计净值": nav.iloc[-1],
    }
