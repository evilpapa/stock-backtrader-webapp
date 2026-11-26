"""量稳换手率选股策略（东吴证券 2021-12-07《“技术分析拥抱选股因子”系列研究（九）：改进 STR——换手率要比别人稳，也要比自己稳》）。

核心因子族（月底截面计算，次月首日生效，均做 MAD 去极值 + 横截面市值中性化 + 标准化，方向均为“越小越好”）：
1. ``turn20``：传统换手率因子 —— 过去 K 日日均换手率；
2. ``pct_turn20``：换手率变化率因子 —— 过去 K 日内每日“当日换手率 / 前 X 日均值 - 1”的均值；
3. ``str``：量稳换手率因子（The Stability of Turnover Rate）—— 过去 K 日换手率标准差；
4. ``scr``：量稳换手率变化率因子（The STR Change Rate）—— 过去 K 日换手率标准差 / 再往前 X 日换手率标准差 - 1；
5. ``pure_scr``：纯净 SCR 因子 —— 在 ``scr`` 基础上进一步对常用风格因子与一级行业哑变量回归取残差。

默认参数与研报保持一致：K=20，X=40，月频调仓，手续费率沿用 ``src/utils/commission.py`` 默认万 0.854。
纯 pandas/numpy 实现，严格保证截面无前视偏差。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src.utils.commission import ChinaStockCommission

DEFAULT_COMMISSION: float = float(ChinaStockCommission.params.commission)
FACTOR_NAMES: tuple[str, ...] = ("turn20", "pct_turn20", "str", "scr")
ALL_FACTOR_NAMES: tuple[str, ...] = (*FACTOR_NAMES, "pure_scr")


@dataclass(frozen=True)
class TurnoverStabilityParams:
    """量稳换手率选股策略参数。"""

    k_window: int = 20
    x_window: int = 40
    min_listed_days: int = 120
    min_cur_ratio: float = 0.75
    min_base_ratio: float = 0.75
    mad_scale: float = 5.0
    deciles: int = 10
    top_fraction: float = 0.10
    top_n: int = 50
    commission: float = DEFAULT_COMMISSION


# ---------------------------------------------------------------------------
# 截面预处理与中性化
# ---------------------------------------------------------------------------


def winsorize_mad(series: pd.Series, scale: float = 5.0) -> pd.Series:
    """中位数绝对偏差（MAD）去极值。"""
    valid = series.dropna()
    if valid.empty:
        return series.copy()
    median = float(valid.median())
    mad = float((valid - median).abs().median())
    if mad <= 0 or not np.isfinite(mad):
        return series.copy()
    bound = scale * mad
    return series.clip(lower=median - bound, upper=median + bound)


def standardize(series: pd.Series) -> pd.Series:
    """横截面 z-score 标准化。"""
    valid = series.dropna()
    if len(valid) < 2:
        return pd.Series(np.nan, index=series.index, dtype=float)
    std = float(valid.std(ddof=1))
    if std <= 0 or not np.isfinite(std):
        return pd.Series(np.nan, index=series.index, dtype=float)
    return (series - float(valid.mean())) / std


def neutralize_series(
    factor: pd.Series,
    controls: pd.DataFrame,
    *,
    mad_scale: float = 5.0,
    standardize_output: bool = True,
) -> pd.Series:
    """横截面 MAD 去极值 + OLS 回归取残差 + 可选标准化。"""
    y = winsorize_mad(factor.astype(float), scale=mad_scale)
    aligned = pd.concat([y.rename("__y__"), controls], axis=1).dropna()
    if len(aligned) <= controls.shape[1] + 2:
        return pd.Series(np.nan, index=factor.index, dtype=float)

    y_vec = aligned["__y__"].to_numpy(dtype=float)
    x_mat = aligned.drop(columns=["__y__"]).to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(y_vec), dtype=float), x_mat])
    beta, *_ = np.linalg.lstsq(design, y_vec, rcond=None)
    resid = pd.Series(y_vec - design @ beta, index=aligned.index, dtype=float)
    result = resid.reindex(factor.index)
    return standardize(result) if standardize_output else result


def neutralize_by_size(
    factor: pd.Series,
    total_mv: pd.Series,
    *,
    mad_scale: float = 5.0,
) -> pd.Series:
    """横截面自然对数市值中性化（研报 Turn20 / PctTurn20 / STR / SCR 标准步骤）。"""
    log_mv = np.log(total_mv.astype(float).where(total_mv > 0))
    return neutralize_series(
        factor,
        pd.DataFrame({"log_mv": log_mv}, index=factor.index),
        mad_scale=mad_scale,
    )


def neutralize_style_industry(
    factor: pd.Series,
    styles: pd.DataFrame,
    industry: pd.Series | None = None,
    *,
    mad_scale: float = 5.0,
) -> pd.Series:
    """纯净因子：剔除常用风格因子与一级行业哑变量（研报 4.1 节）。"""
    parts: list[pd.DataFrame] = []
    if not styles.empty:
        clean_styles = pd.DataFrame(
            {col: standardize(winsorize_mad(styles[col].astype(float), scale=mad_scale)) for col in styles.columns},
            index=factor.index,
        )
        # 保留存在有效差异的风格列，缺失值用横截面中位数(0)填充，避免丢失过多样本。
        valid_cols = [c for c in clean_styles.columns if clean_styles[c].notna().sum() >= 10]
        if valid_cols:
            parts.append(clean_styles[valid_cols].fillna(0.0))

    if industry is not None:
        ind = industry.reindex(factor.index).fillna("__MISSING__").astype(str)
        dummies = pd.get_dummies(ind, prefix="ind", drop_first=True, dtype=float)
        if not dummies.empty:
            parts.append(dummies)

    if not parts:
        return standardize(winsorize_mad(factor.astype(float), scale=mad_scale))
    controls = pd.concat(parts, axis=1)
    return neutralize_series(factor, controls, mad_scale=mad_scale)


# ---------------------------------------------------------------------------
# 调仓日与样本池过滤
# ---------------------------------------------------------------------------


def month_end_dates(
    trading_days: pd.DatetimeIndex,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> list[pd.Timestamp]:
    """返回区间内每个自然月的最后一个交易日（月底截面日）。"""
    days = pd.DatetimeIndex(trading_days).sort_values()
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    scoped = days[(days >= start_ts) & (days <= end_ts)]
    if scoped.empty:
        return []
    periods = scoped.to_period("M")
    return [pd.Timestamp(group.iloc[-1]) for _, group in pd.Series(scoped).groupby(periods)]


def eligible_universe(
    date: pd.Timestamp,
    *,
    turnover_today: pd.Series,
    total_mv: pd.Series,
    is_st: pd.Series,
    list_date: pd.Series,
    params: TurnoverStabilityParams = TurnoverStabilityParams(),
    universe_codes: Sequence[str] | None = None,
) -> pd.Index:
    """截面有效股票池：剔除 ST/*ST、上市未满 min_listed_days、当日停牌/无有效换手与市值个股。"""
    index = turnover_today.index
    if universe_codes is not None:
        index = index.intersection(pd.Index(universe_codes))
    if index.empty:
        return pd.Index([])

    t_val = turnover_today.reindex(index).astype(float)
    mv_val = total_mv.reindex(index).astype(float)
    st_flag = is_st.reindex(index).fillna(False).astype(bool)
    listed = pd.to_datetime(list_date.reindex(index), errors="coerce")
    age_days = (pd.Timestamp(date) - listed).dt.days

    mask = (
        (~st_flag)
        & age_days.ge(params.min_listed_days)
        & mv_val.gt(0)
        & t_val.gt(0)
        & np.isfinite(t_val)
        & np.isfinite(mv_val)
    )
    return index[mask]


# ---------------------------------------------------------------------------
# 因子计算（严格使用 date 及之前历史数据）
# ---------------------------------------------------------------------------


def compute_raw_turnover_factors(
    turnover: pd.DataFrame,
    date: pd.Timestamp,
    *,
    k_window: int = 20,
    x_window: int = 40,
    min_cur_ratio: float = 0.75,
    min_base_ratio: float = 0.75,
    pct_turn_base_mean: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """计算单个月底截面 ``date`` 的未中性化原始因子（Turn20 / PctTurn20 / STR / SCR）。

    ``turnover`` 为日期 × 股票的日度换手率面板（停牌/缺失为 NaN 或 <=0 时视作无效）。
    """
    loc = turnover.index.searchsorted(pd.Timestamp(date), side="right") - 1
    need = k_window + x_window
    if loc + 1 < need:
        return pd.DataFrame(columns=list(FACTOR_NAMES), index=turnover.columns, dtype=float)

    clean = turnover.iloc[loc - need + 1 : loc + 1].astype(float)
    clean = clean.where(clean > 0)

    cur_win = clean.iloc[-k_window:]
    base_win = clean.iloc[:x_window]

    min_cur = max(2, int(np.ceil(k_window * min_cur_ratio)))
    min_base = max(2, int(np.ceil(x_window * min_base_ratio)))

    cur_count = cur_win.notna().sum(axis=0)
    base_count = base_win.notna().sum(axis=0)

    turn20 = cur_win.mean(axis=0).where(cur_count >= min_cur)
    str_raw = cur_win.std(axis=0, ddof=1).where(cur_count >= min_cur)
    base_std = base_win.std(axis=0, ddof=1).where(base_count >= min_base)
    scr_raw = (str_raw / base_std - 1.0).where(base_std > 0)

    if pct_turn_base_mean is not None:
        base_daily = pct_turn_base_mean.iloc[loc - k_window + 1 : loc + 1]
        daily_chg = (cur_win / base_daily.where(base_daily > 0) - 1.0)
        pct_turn20 = daily_chg.mean(axis=0).where(daily_chg.notna().sum(axis=0) >= min_cur)
    else:
        # 严格按研报 2.1 节：对过去 K 个交易日的每日，基准换手率为该日前 X 个交易日换手率均值。
        hist_start = max(0, loc - need + 1)
        full_slice = turnover.iloc[hist_start : loc + 1].astype(float).where(lambda df: df > 0)
        rolling_base = full_slice.shift(1).rolling(x_window, min_periods=min_base).mean().iloc[-k_window:]
        daily_chg = cur_win / rolling_base.where(rolling_base > 0) - 1.0
        pct_turn20 = daily_chg.mean(axis=0).where(daily_chg.notna().sum(axis=0) >= min_cur)

    return pd.DataFrame(
        {
            "turn20": turn20,
            "pct_turn20": pct_turn20,
            "str": str_raw,
            "scr": scr_raw,
        },
        index=turnover.columns,
    )


def precompute_pct_turn_base(
    turnover: pd.DataFrame,
    x_window: int = 40,
    min_base_ratio: float = 0.75,
) -> pd.DataFrame:
    """预计算每个交易日“往前 X 个交易日换手率均值”，供全历史截面复用提速。"""
    min_base = max(2, int(np.ceil(x_window * min_base_ratio)))
    clean = turnover.astype(float).where(lambda df: df > 0)
    return clean.shift(1).rolling(x_window, min_periods=min_base).mean()


def build_style_controls(
    date: pd.Timestamp,
    *,
    returns: pd.DataFrame,
    turnover: pd.DataFrame,
    total_mv: pd.Series,
    pb: pd.Series | None = None,
    pe_ttm: pd.Series | None = None,
    index: pd.Index,
) -> pd.DataFrame:
    """基于日频价量与估值数据构造纯净 SCR 所需的横截面风格控制矩阵（严格 <= date）。"""
    log_mv = np.log(total_mv.reindex(index).astype(float).where(lambda s: s > 0))
    size_z = standardize(winsorize_mad(log_mv))
    # 非线性市值：对标准化市值的立方再做线性市值正交
    nl_raw = size_z ** 3
    nl_size = neutralize_series(nl_raw, pd.DataFrame({"size": size_z}), standardize_output=True)

    loc = returns.index.searchsorted(pd.Timestamp(date), side="right") - 1
    ret_sub = returns.iloc[: loc + 1].reindex(columns=index)
    turn_sub = turnover.iloc[: loc + 1].reindex(columns=index).where(lambda df: df > 0)

    # 动量（过去 252 日剔除近 21 日）与短期反转（近 20 日）
    if len(ret_sub) >= 60:
        mom_end = max(0, len(ret_sub) - 21)
        mom_start = max(0, len(ret_sub) - 252)
        mom_win = ret_sub.iloc[mom_start:mom_end]
        momentum = (1.0 + mom_win.fillna(0.0)).prod(axis=0) - 1.0
        momentum = momentum.where(mom_win.notna().sum(axis=0) >= 20)
    else:
        momentum = pd.Series(np.nan, index=index, dtype=float)

    rev_win = ret_sub.iloc[-20:]
    rev20 = (1.0 + rev_win.fillna(0.0)).prod(axis=0) - 1.0
    rev20 = rev20.where(rev_win.notna().sum(axis=0) >= 10)

    vol_win = ret_sub.iloc[-60:]
    volatility = vol_win.std(axis=0, ddof=1).where(vol_win.notna().sum(axis=0) >= 20)

    liq_win = turn_sub.iloc[-20:]
    liquidity = np.log(liq_win.mean(axis=0).where(lambda s: s > 0))
    liquidity = liquidity.where(liq_win.notna().sum(axis=0) >= 10)

    data: dict[str, pd.Series] = {
        "size": log_mv,
        "nl_size": nl_size,
        "momentum": momentum,
        "rev20": rev20,
        "volatility": volatility,
        "liquidity": liquidity,
    }
    if pb is not None:
        pb_s = pb.reindex(index).astype(float)
        data["bp"] = (1.0 / pb_s).where(pb_s > 0)
    if pe_ttm is not None:
        pe_s = pe_ttm.reindex(index).astype(float)
        data["ep"] = (1.0 / pe_s).where(pe_s != 0)
    return pd.DataFrame(data, index=index)


def compute_cross_section_factors(
    date: pd.Timestamp,
    *,
    turnover: pd.DataFrame,
    total_mv: pd.Series,
    is_st: pd.Series,
    list_date: pd.Series,
    params: TurnoverStabilityParams = TurnoverStabilityParams(),
    universe_codes: Sequence[str] | None = None,
    pct_turn_base_mean: pd.DataFrame | None = None,
    returns: pd.DataFrame | None = None,
    pb: pd.Series | None = None,
    pe_ttm: pd.Series | None = None,
    industry: pd.Series | None = None,
    include_pure_scr: bool = False,
) -> pd.DataFrame:
    """计算指定截面日的全套市值中性化因子（以及可选的纯净 SCR 因子）。"""
    date_ts = pd.Timestamp(date)
    if date_ts not in turnover.index:
        return pd.DataFrame(columns=list(ALL_FACTOR_NAMES if include_pure_scr else FACTOR_NAMES))

    pool = eligible_universe(
        date_ts,
        turnover_today=turnover.loc[date_ts],
        total_mv=total_mv,
        is_st=is_st,
        list_date=list_date,
        params=params,
        universe_codes=universe_codes,
    )
    if len(pool) < params.deciles:
        return pd.DataFrame(columns=list(ALL_FACTOR_NAMES if include_pure_scr else FACTOR_NAMES))

    raw = compute_raw_turnover_factors(
        turnover,
        date_ts,
        k_window=params.k_window,
        x_window=params.x_window,
        min_cur_ratio=params.min_cur_ratio,
        min_base_ratio=params.min_base_ratio,
        pct_turn_base_mean=pct_turn_base_mean,
    ).reindex(pool)

    mv_pool = total_mv.reindex(pool)
    out = pd.DataFrame(
        {
            col: neutralize_by_size(raw[col], mv_pool, mad_scale=params.mad_scale)
            for col in FACTOR_NAMES
        },
        index=pool,
    )

    if include_pure_scr:
        if returns is None:
            raise ValueError("计算 pure_scr 需要提供 returns 面板")
        styles = build_style_controls(
            date_ts,
            returns=returns,
            turnover=turnover,
            total_mv=total_mv,
            pb=pb,
            pe_ttm=pe_ttm,
            index=pool,
        )
        out["pure_scr"] = neutralize_style_industry(
            out["scr"],
            styles,
            industry=industry,
            mad_scale=params.mad_scale,
        )
    return out


# ---------------------------------------------------------------------------
# 分组、选股与回测
# ---------------------------------------------------------------------------


def decile_groups(score: pd.Series, groups: int = 10, *, ascending: bool = True) -> list[pd.Index]:
    """按因子值排序等分为 ``groups`` 组。默认升序：G1 为因子值最小（多头），G10 为最大（空头）。"""
    ordered = score.dropna().sort_values(ascending=ascending, kind="mergesort").index
    if len(ordered) < groups:
        return [pd.Index([]) for _ in range(groups)]
    return [pd.Index(chunk) for chunk in np.array_split(ordered, groups)]


def select_equal_weight(
    score: pd.Series,
    *,
    top_fraction: float | None = None,
    top_n: int | None = None,
    ascending: bool = True,
) -> pd.Series:
    """选取因子最优股票并等权分配权重（默认因子值越小越好）。"""
    ordered = score.dropna().sort_values(ascending=ascending, kind="mergesort")
    if ordered.empty:
        return pd.Series(dtype=float)
    if top_n is not None:
        count = max(1, min(int(top_n), len(ordered)))
    elif top_fraction is not None:
        count = max(1, int(round(len(ordered) * float(top_fraction))))
    else:
        raise ValueError("必须指定 top_fraction 或 top_n 之一")
    picked = ordered.iloc[:count].index
    return pd.Series(1.0 / len(picked), index=picked, dtype=float)


def backtest_weights(
    returns: pd.DataFrame,
    targets: Mapping[pd.Timestamp, pd.Series],
    commission: float = DEFAULT_COMMISSION,
) -> pd.DataFrame:
    """月底收盘按目标权重建仓，下一交易日起计收益，月内权重随价格自然漂移。

    返回列：``return``（日收益率）、``turnover``（调仓当日双边换手率，非调仓日为 0）。
    """
    dates = sorted(targets)
    if not dates:
        return pd.DataFrame(columns=["return", "turnover"], dtype=float)

    out_ret = pd.Series(np.nan, index=returns.index, dtype=float)
    turnover = pd.Series(0.0, index=returns.index, dtype=float)
    holdings = pd.Series(dtype=float)

    for i, day in enumerate(dates):
        target = targets[day]
        end = dates[i + 1] if i + 1 < len(dates) else returns.index[-1]
        period = returns.loc[(returns.index > day) & (returns.index <= end)]
        if period.empty:
            continue

        aligned = pd.concat([holdings.rename("prev"), target.rename("next")], axis=1).fillna(0.0)
        trade = float((aligned["next"] - aligned["prev"]).abs().sum()) if not holdings.empty else float(target.abs().sum())
        turnover.loc[period.index[0]] = trade

        if target.empty:
            out_ret.loc[period.index] = 0.0
            holdings = pd.Series(dtype=float)
            continue

        r = period.reindex(columns=target.index).fillna(0.0)
        value = (1.0 + r).cumprod().mul(target, axis=1)
        nav = value.sum(axis=1)
        prev_nav = np.concatenate([[1.0], nav.iloc[:-1].to_numpy(dtype=float)])
        daily = nav.to_numpy(dtype=float) / prev_nav - 1.0
        daily[0] -= trade * commission
        out_ret.loc[period.index] = daily
        holdings = value.iloc[-1] / float(nav.iloc[-1])

    return pd.DataFrame({"return": out_ret, "turnover": turnover}).dropna(subset=["return"])


def period_forward_returns(
    returns: pd.DataFrame,
    start_day: pd.Timestamp,
    end_day: pd.Timestamp,
) -> pd.Series:
    """计算 ``(start_day, end_day]`` 区间内每只股票的累计复利收益（要求区间内至少有 1 个非空收益）。"""
    window = returns.loc[(returns.index > start_day) & (returns.index <= end_day)]
    if window.empty:
        return pd.Series(dtype=float)
    has_obs = window.notna().any(axis=0)
    compounded = (1.0 + window.fillna(0.0)).prod(axis=0) - 1.0
    return compounded.where(has_obs)


def evaluate_factor_monthly(
    factor_by_date: Mapping[pd.Timestamp, pd.Series],
    returns: pd.DataFrame,
    *,
    deciles: int = 10,
    commission: float = 0.0,
) -> dict[str, object]:
    """执行标准单因子月度截面检验（IC / RankIC / 10 分组收益 / 多空对冲 / 多空分解 / 组内离散度）。

    返回包含：
    - ``ic_series``: 月度 Pearson IC
    - ``rank_ic_series``: 月度 Spearman RankIC
    - ``decile_monthly``: 月度 10 分组收益 DataFrame (G1..G10, market_ew, ls, long_excess, short_excess)
    - ``decile_daily``: 逐日 10 分组收益及多空组合日收益 DataFrame
    - ``group_dispersion``: 各分组下月收益横截面标准差的跨月均值（对应研报图 3 / 图 9）
    - ``summary``: 汇总绩效字典
    """
    dates = sorted(factor_by_date)
    decile_targets: dict[str, dict[pd.Timestamp, pd.Series]] = {f"G{g}": {} for g in range(1, deciles + 1)}
    market_targets: dict[pd.Timestamp, pd.Series] = {}

    ic_rows: dict[pd.Timestamp, float] = {}
    rank_ic_rows: dict[pd.Timestamp, float] = {}
    monthly_rows: list[dict[str, float]] = []
    monthly_index: list[pd.Timestamp] = []
    dispersion_rows: list[dict[str, float]] = []

    for i, day in enumerate(dates[:-1]):
        next_day = dates[i + 1]
        score = factor_by_date[day].dropna()
        if len(score) < deciles:
            continue

        fwd = period_forward_returns(returns, day, next_day)
        joined = pd.concat([score.rename("factor"), fwd.rename("fwd")], axis=1).dropna()
        if len(joined) < deciles:
            continue

        ic_rows[next_day] = float(joined["factor"].corr(joined["fwd"], method="pearson"))
        rank_ic_rows[next_day] = float(joined["factor"].corr(joined["fwd"], method="spearman"))

        groups = decile_groups(score, groups=deciles, ascending=True)
        row_ret: dict[str, float] = {}
        row_disp: dict[str, float] = {}
        for g, members in enumerate(groups, start=1):
            label = f"G{g}"
            decile_targets[label][day] = pd.Series(1.0 / len(members), index=members) if len(members) else pd.Series(dtype=float)
            grp_fwd = fwd.reindex(members).dropna()
            row_ret[label] = float(grp_fwd.mean()) if not grp_fwd.empty else np.nan
            row_disp[label] = float(grp_fwd.std(ddof=1)) if len(grp_fwd) >= 2 else np.nan

        market_targets[day] = pd.Series(1.0 / len(score), index=score.index)
        mkt_ret = float(fwd.reindex(score.index).dropna().mean())
        g1_ret, g10_ret = row_ret["G1"], row_ret[f"G{deciles}"]
        row_ret["market_ew"] = mkt_ret
        row_ret["ls"] = (1.0 + g1_ret) / (1.0 + g10_ret) - 1.0 if (1.0 + g10_ret) > 0 else np.nan
        row_ret["long_excess"] = (1.0 + g1_ret) / (1.0 + mkt_ret) - 1.0 if (1.0 + mkt_ret) > 0 else np.nan
        row_ret["short_excess"] = (1.0 + mkt_ret) / (1.0 + g10_ret) - 1.0 if (1.0 + g10_ret) > 0 else np.nan

        monthly_rows.append(row_ret)
        dispersion_rows.append(row_disp)
        monthly_index.append(next_day)

    ic_s = pd.Series(ic_rows, dtype=float).sort_index()
    rank_ic_s = pd.Series(rank_ic_rows, dtype=float).sort_index()
    decile_monthly = pd.DataFrame(monthly_rows, index=pd.DatetimeIndex(monthly_index))
    dispersion = pd.DataFrame(dispersion_rows, index=pd.DatetimeIndex(monthly_index)).mean(axis=0)

    daily_cols: dict[str, pd.Series] = {}
    turnovers: dict[str, float] = {}
    for label, tgt in decile_targets.items():
        bt = backtest_weights(returns, tgt, commission=commission)
        daily_cols[label] = bt["return"]
        pos_turn = bt["turnover"][bt["turnover"] > 0]
        turnovers[label] = float(pos_turn.mean() / 2.0) if not pos_turn.empty else 0.0

    mkt_bt = backtest_weights(returns, market_targets, commission=0.0)
    daily_cols["market_ew"] = mkt_bt["return"]
    decile_daily = pd.DataFrame(daily_cols).dropna(how="all")
    if "G1" in decile_daily and f"G{deciles}" in decile_daily:
        # 日度等权多空对冲净值收益率（与月度多空比率口径并列汇报）
        decile_daily["ls"] = (1.0 + decile_daily["G1"]) / (1.0 + decile_daily[f"G{deciles}"]) - 1.0
        decile_daily["long_excess"] = (1.0 + decile_daily["G1"]) / (1.0 + decile_daily["market_ew"]) - 1.0
        decile_daily["short_excess"] = (1.0 + decile_daily["market_ew"]) / (1.0 + decile_daily[f"G{deciles}"]) - 1.0

    summary = summarize_factor(
        ic_s,
        rank_ic_s,
        decile_monthly,
        g1_turnover=turnovers.get("G1", np.nan),
    )
    return {
        "ic_series": ic_s,
        "rank_ic_series": rank_ic_s,
        "decile_monthly": decile_monthly,
        "decile_daily": decile_daily,
        "group_dispersion": dispersion,
        "summary": summary,
    }


def summarize_factor(
    ic_series: pd.Series,
    rank_ic_series: pd.Series,
    decile_monthly: pd.DataFrame,
    *,
    g1_turnover: float = np.nan,
) -> dict[str, float]:
    """按月度截面序列汇总 IC / RankIC 与多空/多头/空头绩效指标（与东吴研报口径对齐）。"""
    if decile_monthly.empty:
        return {}

    ic_mean = float(ic_series.mean())
    ic_std = float(ic_series.std(ddof=1))
    rank_ic_mean = float(rank_ic_series.mean())
    rank_ic_std = float(rank_ic_series.std(ddof=1))

    ls_perf = performance(decile_monthly["ls"].dropna(), periods=12)
    long_perf = performance(decile_monthly["long_excess"].dropna(), periods=12)
    short_perf = performance(decile_monthly["short_excess"].dropna(), periods=12)
    g1_perf = performance(decile_monthly["G1"].dropna(), periods=12)

    return {
        "月度IC均值": ic_mean,
        "年化ICIR": ic_mean / ic_std * np.sqrt(12) if ic_std > 0 else np.nan,
        "月度RankIC均值": rank_ic_mean,
        "年化RankICIR": rank_ic_mean / rank_ic_std * np.sqrt(12) if rank_ic_std > 0 else np.nan,
        "多空累计收益": ls_perf["累计收益"],
        "多空年化收益": ls_perf["年化收益"],
        "多空年化波动": ls_perf["年化波动"],
        "多空信息比率": ls_perf["夏普比率"],
        "多空最大回撤": ls_perf["最大回撤"],
        "多空卡玛比率": ls_perf["卡玛比率"],
        "多空月度胜率": float((decile_monthly["ls"].dropna() > 0).mean()),
        "多头超额年化": long_perf["年化收益"],
        "多头超额IR": long_perf["夏普比率"],
        "多头超额最大回撤": long_perf["最大回撤"],
        "多头超额月胜率": float((decile_monthly["long_excess"].dropna() > 0).mean()),
        "空头超额年化": short_perf["年化收益"],
        "空头超额IR": short_perf["夏普比率"],
        "空头超额最大回撤": short_perf["最大回撤"],
        "空头超额月胜率": float((decile_monthly["short_excess"].dropna() > 0).mean()),
        "多头组年化收益": g1_perf["年化收益"],
        "多头月均单边换手": g1_turnover,
        "样本月数": float(len(decile_monthly)),
    }


def yearly_factor_table(decile_monthly: pd.DataFrame, deciles: int = 10) -> pd.DataFrame:
    """生成分年度绩效表（对应研报表 4 / 表 6 / 表 8）。"""
    rows = []
    last_col = f"G{deciles}"
    for year, sub in decile_monthly.groupby(decile_monthly.index.year):
        if sub.empty:
            continue
        n = len(sub)
        scale = 12.0 / n
        g1_cum = float((1.0 + sub["G1"].dropna()).prod() - 1.0)
        g10_cum = float((1.0 + sub[last_col].dropna()).prod() - 1.0)
        ls = sub["ls"].dropna()
        ls_cum = float((1.0 + ls).prod() - 1.0)
        ls_ann = (1.0 + ls_cum) ** scale - 1.0 if n > 0 else np.nan
        ls_vol = float(ls.std(ddof=1) * np.sqrt(12.0)) if len(ls) >= 2 else np.nan
        nav = (1.0 + ls).cumprod()
        peak = pd.concat([pd.Series([1.0]), nav]).cummax().iloc[1:]
        mdd = float(-(nav.to_numpy() / peak.to_numpy() - 1.0).min()) if len(nav) else np.nan
        rows.append(
            {
                "年份": int(year),
                "月数": int(n),
                "G1收益": g1_cum,
                f"{last_col}收益": g10_cum,
                "多空收益": ls_cum,
                "多空年化收益": ls_ann,
                "多空年化波动": ls_vol,
                "信息比率": ls_ann / ls_vol if ls_vol and ls_vol > 0 else np.nan,
                "月度胜率": float((ls > 0).mean()) if len(ls) else np.nan,
                "最大回撤": mdd,
            }
        )
    return pd.DataFrame(rows).set_index("年份") if rows else pd.DataFrame()


def performance(returns: pd.Series, periods: int = 252) -> dict[str, float]:
    """统一回测绩效指标：累计收益、年化收益、年化波动、最大回撤、夏普比率、卡玛比率。"""
    clean = returns.dropna().astype(float)
    if clean.empty:
        return {
            "累计收益": np.nan,
            "年化收益": np.nan,
            "年化波动": np.nan,
            "最大回撤": np.nan,
            "夏普比率": np.nan,
            "卡玛比率": np.nan,
        }
    nav = (1.0 + clean).cumprod()
    total_return = float(nav.iloc[-1] - 1.0)
    years = len(clean) / float(periods)
    annual = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and nav.iloc[-1] > 0 else np.nan
    vol = float(clean.std(ddof=1) * np.sqrt(periods)) if len(clean) >= 2 else np.nan
    # 从初始净值 1.0 起算回撤，防止首期下跌被忽略。
    nav_with_base = pd.concat([pd.Series([1.0]), nav.reset_index(drop=True)], ignore_index=True)
    max_dd = float(-(nav_with_base / nav_with_base.cummax() - 1.0).min())
    return {
        "累计收益": total_return,
        "年化收益": annual,
        "年化波动": vol,
        "最大回撤": max_dd,
        "夏普比率": annual / vol if vol and vol > 0 else np.nan,
        "卡玛比率": annual / max_dd if max_dd and max_dd > 0 else np.nan,
    }
