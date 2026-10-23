"""增强型自由现金流策略（国泰海通 2026-10-17《正收益策略系列01：如何通过估值、盈利质量和资本开支效率构建自由现金流策略》）。

流程（研报 4.1.2 / 4.3 节）：
1. 候选池 = 中证自由现金流指数选样：剔除 ST、次新 → 剔除过去一年日均成交额后 20% →
   剔除金融/地产 → 按盈利质量取前 80% → 要求 FCF_TTM>0、EV>0、近 5 个年报经营现金流均为正；
2. 复现指数：候选池按 FCF/EV 取前 100；
3. 增强策略：候选池内对 自由现金流率1(FCF/EV1)、自由现金流EBITDA比、资本开支效率ROEPB 做百分位等权合成，取前 100；
4. 加权：自由现金流绝对值加权、单只上限 10%（或等权）；季度调样（3/6/9/12 月第二个周五收盘定样，下一交易日生效），
   期间权重随价格漂移。

纯 pandas 实现：财务数据按首次公告日 ``f_ann_date`` 做 point-in-time 过滤，不依赖 Backtrader。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FINANCE_REAL_ESTATE = frozenset({"银行", "非银行金融", "综合金融", "房地产"})
FACTORS = ("fcf_yield1", "fcf_ebitda", "capex_roepb")


@dataclass(frozen=True)
class FreeCashFlowParams:
    size: int = 100
    weight_cap: float = 0.10
    liquidity_keep: float = 0.80
    quality_keep: float = 0.80
    ocf_years: int = 5
    liquidity_window: int = 252
    min_listed_days_main: int = 91  # 其他证券上市满一个季度（自然日）
    min_listed_days_star: int = 365  # 科创板满一年
    min_listed_days_bj: int = 730  # 北交所满两年
    commission: float = 0.0000854  # 与 src/utils/commission.py 默认费率一致，双边各收一次


# ---------------------------------------------------------------------------
# 财务数据 → 按报告期的指标（带可用日期）
# ---------------------------------------------------------------------------


def _latest_version(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()

    def naive(values: pd.Series) -> pd.Series:
        # DataHub 输出带 Asia/Shanghai 时区，策略内部统一用无时区日期。
        parsed = pd.to_datetime(values)
        return parsed.dt.tz_localize(None) if parsed.dt.tz is not None else parsed

    frame["f_ann_date"] = naive(frame["f_ann_date"]).fillna(naive(frame["ann_date"]))
    frame["end_date"] = naive(frame["end_date"])
    if "update_flag" in frame:
        frame = frame.sort_values("update_flag", kind="stable")
    # 更正报告沿用首次公告日：避免因更正延后可用日期，但数值取更正后口径。
    first_ann = frame.groupby(["symbol", "end_date"])["f_ann_date"].transform("min")
    frame = frame.assign(f_ann_date=first_ann).drop_duplicates(["symbol", "end_date"], keep="last")
    return frame.drop(columns=[c for c in ("ann_date", "update_flag", "report_type", "table", "source") if c in frame])


def _ttm(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """累计口径 → TTM：TTM(P) = YTD(P) + 上年年报 − 上年同期 YTD；年报直接取值。"""
    base = frame[["symbol", "end_date", *columns]]
    keys = frame[["symbol", "end_date"]]
    year = keys["end_date"].dt.year
    prev_annual_key = keys.assign(end_date=pd.to_datetime((year - 1).astype(str) + "-12-31"))
    prev_same_key = keys.assign(end_date=keys["end_date"] - pd.DateOffset(years=1))
    prev_annual = prev_annual_key.merge(base, on=["symbol", "end_date"], how="left")[columns].to_numpy(float)
    prev_same = prev_same_key.merge(base, on=["symbol", "end_date"], how="left")[columns].to_numpy(float)
    current = base[columns].to_numpy(float)
    is_annual = (keys["end_date"].dt.month == 12).to_numpy()[:, None]
    values = np.where(is_annual, current, current + prev_annual - prev_same)
    return pd.DataFrame(values, columns=[f"{c}_ttm" for c in columns], index=frame.index)


def build_fundamentals(income: pd.DataFrame, cashflow: pd.DataFrame, balance: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (报告期指标, 年报指标)；每行带 ``avail_date``，即该行全部输入均已公告的日期。"""
    inc, cf, bs = (_latest_version(f) for f in (income, cashflow, balance))
    cf = cf.assign(
        # 资本开支取“购建固定/无形/长期资产支付的现金”毛额：与官方成分对账，毛额重合度更高（79.5% vs 77.6%）。
        capex=cf["c_pay_acq_const_fiolta"],
        da=cf["depr_fa_coga_dpba"]
        + cf[["amort_intang_assets", "lt_amort_deferred_exp", "use_right_asset_dep"]].fillna(0.0).sum(axis=1),
    )
    cf["fcf"] = cf["n_cashflow_act"] - cf["capex"]
    merged = (
        cf[["symbol", "end_date", "f_ann_date", "n_cashflow_act", "capex", "fcf", "da"]]
        .merge(inc[["symbol", "end_date", "f_ann_date", "operate_profit", "fin_exp", "n_income_attr_p"]],
               on=["symbol", "end_date"], how="inner", suffixes=("", "_inc"))
        .merge(bs[["symbol", "end_date", "f_ann_date", "total_assets", "total_liab", "money_cap", "trad_asset",
                   "total_hldr_eqy_exc_min_int"]], on=["symbol", "end_date"], how="inner", suffixes=("", "_bs"))
    )
    merged["f_ann_date"] = merged[["f_ann_date", "f_ann_date_inc", "f_ann_date_bs"]].max(axis=1)
    merged = merged.drop(columns=["f_ann_date_inc", "f_ann_date_bs"]).sort_values(["symbol", "end_date"]).reset_index(drop=True)
    merged["fin_exp"] = merged["fin_exp"].fillna(0.0)

    flows = ["n_cashflow_act", "fcf", "operate_profit", "fin_exp", "n_income_attr_p"]
    merged = pd.concat([merged, _ttm(merged, flows)], axis=1)
    # 折旧摊销只在半年报/年报披露：在 S/A 期计算 TTM，再前向填充到 Q1/Q3。
    semi = merged.loc[merged["end_date"].dt.month.isin([6, 12])]
    merged["da_ttm"] = _ttm(semi, ["da"])["da_ttm"].reindex(merged.index)
    merged["da_ttm"] = merged.groupby("symbol")["da_ttm"].ffill()
    merged["ebitda_ttm"] = merged["operate_profit_ttm"] + merged["fin_exp_ttm"] + merged["da_ttm"]
    # 上年同期/上年年报在当期之前公告，TTM 的可用日期即当期公告日。
    merged["avail_date"] = merged["f_ann_date"]

    annual = merged[merged["end_date"].dt.month == 12].copy()
    grouped = annual.groupby("symbol")
    years = annual["end_date"].dt.year
    ocf_cols = []
    for k in range(5):
        # 只接受连续年度：第 k 个滞后年报的年份必须正好早 k 年，否则视为缺失。
        contiguous = years - grouped["end_date"].shift(k).dt.year == k
        annual[f"ocf_l{k}"] = grouped["n_cashflow_act"].shift(k).where(contiguous)
        annual[f"capex_l{k}"] = grouped["capex"].shift(k).where(contiguous)
        ocf_cols.append(f"ocf_l{k}")
    annual["ocf_positive_years"] = (annual[ocf_cols] > 0).sum(axis=1)
    recent = annual[["capex_l0", "capex_l1"]].mean(axis=1)
    prior = annual[["capex_l2", "capex_l3", "capex_l4"]].mean(axis=1, skipna=False)
    # 资本开支成长性 = 前 3/4/5 年资本开支均值 / 近 2 年均值（近年开支收缩 → 值越大）。
    annual["capex_growth"] = (prior / recent).where(recent > 0)
    annual = annual[["symbol", "end_date", "avail_date", "ocf_positive_years", "capex_growth"]].reset_index(drop=True)
    return merged, annual


def asof_snapshot(table: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """每只股票取 ``avail_date <= date`` 的最新报告期。"""
    visible = table[table["avail_date"] <= date]
    return visible.sort_values(["symbol", "end_date"]).drop_duplicates("symbol", keep="last").set_index("symbol")


# ---------------------------------------------------------------------------
# 选样
# ---------------------------------------------------------------------------


def _pct_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average")


def candidate_pool(
    date: pd.Timestamp,
    market: pd.DataFrame,
    fundamentals: pd.DataFrame,
    annual: pd.DataFrame,
    params: FreeCashFlowParams = FreeCashFlowParams(),
) -> pd.DataFrame:
    """返回候选池及各因子。

    ``market`` 索引为 symbol，列：total_mv(元)、pb、avg_amount、list_date、is_st、industry。
    """
    p = params
    m = market.copy()
    age = (date - pd.to_datetime(m["list_date"])).dt.days
    code = m.index.to_series()
    min_age = np.where(code.str.startswith("688"), p.min_listed_days_star,
                       np.where(code.str.endswith(".BJ"), p.min_listed_days_bj, p.min_listed_days_main))
    m = m[(~m["is_st"].fillna(False).astype(bool)) & (age >= min_age) & m["total_mv"].gt(0)]
    # 流动性：在样本空间内剔除过去一年日均成交额后 20%。
    m = m[_pct_rank(m["avg_amount"]) > 1 - p.liquidity_keep]
    m = m[~m["industry"].isin(FINANCE_REAL_ESTATE)]

    f = asof_snapshot(fundamentals, date).reindex(m.index)
    a = asof_snapshot(annual, date).reindex(m.index)
    frame = m.join(f.drop(columns=["end_date", "avail_date", "f_ann_date"], errors="ignore"))
    frame["ocf_positive_years"] = a["ocf_positive_years"]
    frame["capex_growth"] = a["capex_growth"]

    frame["quality"] = (frame["n_cashflow_act_ttm"] - frame["operate_profit_ttm"]) / frame["total_assets"]
    frame = frame[frame["quality"].notna()]
    frame = frame[_pct_rank(frame["quality"]) > 1 - p.quality_keep]

    frame["ev"] = frame["total_mv"] + frame["total_liab"] - frame["money_cap"].fillna(0.0)
    frame["ev1"] = frame["ev"] - frame["trad_asset"].fillna(0.0)
    frame = frame[(frame["fcf_ttm"] > 0) & (frame["ev"] > 0) & (frame["ocf_positive_years"] >= p.ocf_years)]

    frame["fcf_yield"] = frame["fcf_ttm"] / frame["ev"]
    frame["fcf_yield1"] = (frame["fcf_ttm"] / frame["ev1"]).where(frame["ev1"] > 0)
    frame["fcf_ebitda"] = (frame["fcf_ttm"] / frame["ebitda_ttm"]).where(frame["ebitda_ttm"] > 0)
    roe = frame["n_income_attr_p_ttm"] / frame["total_hldr_eqy_exc_min_int"].where(frame["total_hldr_eqy_exc_min_int"] > 0)
    frame["capex_roepb"] = frame["capex_growth"] * roe / frame["pb"].where(frame["pb"] > 0)
    ranks = pd.concat([_pct_rank(frame[c]) for c in FACTORS], axis=1)
    frame["composite"] = ranks.mean(axis=1, skipna=True).where(ranks.notna().sum(axis=1) >= 2)
    return frame


def cap_weights(raw: pd.Series, cap: float) -> pd.Series:
    """按 raw 比例分配并迭代封顶，超出部分按比例分给未封顶样本。"""
    weights = raw.clip(lower=0) / raw.clip(lower=0).sum()
    if cap * len(weights) < 1:
        return pd.Series(1 / len(weights), index=weights.index)
    for _ in range(100):
        over = weights > cap + 1e-12
        if not over.any():
            break
        excess = (weights[over] - cap).sum()
        weights[over] = cap
        free = ~over & (weights < cap)
        weights[free] += excess * weights[free] / weights[free].sum()
    return weights


def select(pool: pd.DataFrame, score: str, *, size: int, weighting: str, cap: float) -> pd.Series:
    picked = pool[pool[score].notna()].nlargest(size, score)
    if picked.empty:
        return pd.Series(dtype=float)
    if weighting == "fcf":
        return cap_weights(picked["fcf_ttm"], cap)
    return pd.Series(1 / len(picked), index=picked.index)


def quantile_groups(pool: pd.DataFrame, score: str, groups: int = 5, first_size: int | None = None) -> list[pd.Index]:
    """分组：等数量 ``groups`` 组；``first_size`` 给定时首组固定该数量，剩余 groups-1 等分。"""
    ordered = pool[pool[score].notna()].sort_values(score, ascending=False).index
    if first_size is None:
        return [pd.Index(chunk) for chunk in np.array_split(ordered, groups)]
    head = ordered[:first_size]
    return [pd.Index(head), *[pd.Index(chunk) for chunk in np.array_split(ordered[first_size:], groups - 1)]]


# ---------------------------------------------------------------------------
# 调仓日与回测
# ---------------------------------------------------------------------------


def rebalance_dates(trading_days: pd.DatetimeIndex, start: str, end: str) -> list[pd.Timestamp]:
    """3/6/9/12 月第二个周五（非交易日取之前最近交易日）作为定样日，生效于下一交易日。"""
    result = []
    for month in pd.date_range(pd.Timestamp(start) - pd.offsets.MonthBegin(1), end, freq="MS"):
        if month.month not in (3, 6, 9, 12):
            continue
        fridays = pd.date_range(month, month + pd.offsets.MonthEnd(0), freq="W-FRI")
        target = fridays[1]
        pos = trading_days.searchsorted(target, side="right") - 1
        if pos >= 0 and trading_days[pos].month == target.month:
            day = trading_days[pos]
            if pd.Timestamp(start) - pd.Timedelta(days=100) <= day <= pd.Timestamp(end):
                result.append(day)
    return result


def selection_cutoff(trading_days: pd.DatetimeIndex, rebalance_day: pd.Timestamp) -> pd.Timestamp:
    """定样数据截止日：调样月上月最后一个交易日（与官方成分对账，重合度 82% vs 当日 80%）。"""
    return trading_days[trading_days < rebalance_day.replace(day=1)][-1]


def backtest_weights(
    returns: pd.DataFrame, targets: dict[pd.Timestamp, pd.Series], commission: float = 0.0
) -> pd.DataFrame:
    """定样日收盘按目标权重建仓，期间权重随价格漂移；返回逐日收益与换手。

    ``returns``：日期 × 股票 的日收益（停牌/缺失按 0）。
    """
    dates = sorted(targets)
    out_ret = pd.Series(np.nan, index=returns.index)
    turnover = pd.Series(0.0, index=returns.index)
    holdings = pd.Series(dtype=float)
    for i, day in enumerate(dates):
        target = targets[day]
        end = dates[i + 1] if i + 1 < len(dates) else returns.index[-1]
        period = returns.loc[(returns.index > day) & (returns.index <= end)]
        if period.empty:
            continue
        aligned = pd.concat([holdings, target], axis=1).fillna(0.0)
        trade = (aligned.iloc[:, 1] - aligned.iloc[:, 0]).abs().sum() if not holdings.empty else target.abs().sum()
        turnover.loc[period.index[0]] = trade
        if target.empty:
            out_ret.loc[period.index] = 0.0
            holdings = pd.Series(dtype=float)
            continue
        r = period.reindex(columns=target.index).fillna(0.0)
        value = (1 + r).cumprod().mul(target, axis=1)
        nav = value.sum(axis=1)
        prev = pd.concat([pd.Series([1.0], index=[day]), nav.iloc[:-1]])
        daily = nav.to_numpy() / prev.to_numpy() - 1
        daily[0] -= trade * commission
        out_ret.loc[period.index] = daily
        holdings = value.iloc[-1] / nav.iloc[-1]
    return pd.DataFrame({"return": out_ret, "turnover": turnover}).dropna(subset=["return"])


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
