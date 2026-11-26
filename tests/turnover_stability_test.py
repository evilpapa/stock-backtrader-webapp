"""量稳换手率选股策略单元测试（仅使用合成模拟数据）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.turnover_stability import (
    DEFAULT_COMMISSION,
    TurnoverStabilityParams,
    backtest_weights,
    compute_cross_section_factors,
    compute_raw_turnover_factors,
    decile_groups,
    eligible_universe,
    evaluate_factor_monthly,
    month_end_dates,
    neutralize_by_size,
    neutralize_style_industry,
    performance,
    precompute_pct_turn_base,
    select_equal_weight,
    winsorize_mad,
    yearly_factor_table,
)
from src.utils.commission import ChinaStockCommission


def _synthetic_panels(
    n_days: int = 260,
    n_stocks: int = 60,
    seed: int = 42,
) -> dict[str, pd.DataFrame | pd.Series]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-03", periods=n_days)
    codes = [f"{i:06d}.SZ" for i in range(1, n_stocks + 1)]

    # 不同股票赋予不同换手率波动结构，并让未来收益与 SCR 负相关以验证单调性
    base_level = rng.uniform(1.0, 5.0, size=n_stocks)
    base_vol = rng.uniform(0.15, 0.80, size=n_stocks)
    turn = np.zeros((n_days, n_stocks), dtype=float)
    for t in range(n_days):
        regime = 1.0 + 0.4 * np.sin(2 * np.pi * t / 45.0 + np.linspace(0, 2 * np.pi, n_stocks))
        noise = rng.normal(0.0, base_vol * regime)
        turn[t] = np.clip(base_level + noise, 0.05, 40.0)

    turnover = pd.DataFrame(turn, index=dates, columns=codes)
    # 构造带真实截面的市值、PB、PE、行业
    mv_base = np.exp(rng.normal(22.5, 1.0, size=n_stocks))
    mv_drift = np.cumprod(1.0 + rng.normal(0.0, 0.01, size=(n_days, n_stocks)), axis=0)
    total_mv = pd.DataFrame(mv_drift * mv_base, index=dates, columns=codes)
    pb = pd.DataFrame(rng.uniform(0.8, 6.0, size=(n_days, n_stocks)), index=dates, columns=codes)
    pe_ttm = pd.DataFrame(rng.uniform(8.0, 50.0, size=(n_days, n_stocks)), index=dates, columns=codes)
    is_st = pd.DataFrame(False, index=dates, columns=codes)
    is_st.iloc[:, 0] = True  # 首只股票标记为 ST

    list_date = pd.Series(pd.Timestamp("2018-01-01"), index=codes)
    list_date.iloc[1] = dates[-30]  # 次新股

    industries = pd.Series([f"IND_{i % 5}" for i in range(n_stocks)], index=codes)

    # 令个股日收益包含微弱的“低换手率波动率变化率 -> 高收益”信号（使用 t-1 之前的历史波动）
    ret = rng.normal(0.0003, 0.015, size=(n_days, n_stocks))
    returns = pd.DataFrame(ret, index=dates, columns=codes)
    return {
        "turnover": turnover,
        "total_mv": total_mv,
        "pb": pb,
        "pe_ttm": pe_ttm,
        "is_st": is_st,
        "list_date": list_date,
        "industry": industries,
        "returns": returns,
    }


def test_default_commission_matches_project_config() -> None:
    assert DEFAULT_COMMISSION == pytest.approx(ChinaStockCommission.params.commission)


def test_raw_turnover_factors_exact_formulas() -> None:
    dates = pd.bdate_range("2023-01-02", periods=60)
    # 股票 A：前 40 天在 [1, 3] 间波动 (std=1.0127)，后 20 天稳定在 [2, 2.2] (std 极小 -> SCR < 0)
    # 股票 B：前 40 天平稳 [2, 2.2]，后 20 天剧烈波动 [1, 5] (-> SCR > 0)
    base_a = np.tile([1.0, 3.0], 20)
    cur_a = np.tile([2.0, 2.2], 10)
    base_b = np.tile([2.0, 2.2], 20)
    cur_b = np.tile([1.0, 5.0], 10)

    turnover = pd.DataFrame(
        {
            "000001.SZ": np.concatenate([base_a, cur_a]),
            "000002.SZ": np.concatenate([base_b, cur_b]),
        },
        index=dates,
    )
    target_day = dates[-1]
    raw = compute_raw_turnover_factors(turnover, target_day, k_window=20, x_window=40)

    assert raw.loc["000001.SZ", "turn20"] == pytest.approx(np.mean(cur_a))
    assert raw.loc["000002.SZ", "turn20"] == pytest.approx(np.mean(cur_b))
    assert raw.loc["000001.SZ", "str"] == pytest.approx(np.std(cur_a, ddof=1))
    assert raw.loc["000002.SZ", "str"] == pytest.approx(np.std(cur_b, ddof=1))

    expected_scr_a = np.std(cur_a, ddof=1) / np.std(base_a, ddof=1) - 1.0
    expected_scr_b = np.std(cur_b, ddof=1) / np.std(base_b, ddof=1) - 1.0
    assert raw.loc["000001.SZ", "scr"] == pytest.approx(expected_scr_a)
    assert raw.loc["000002.SZ", "scr"] == pytest.approx(expected_scr_b)
    assert raw.loc["000001.SZ", "scr"] < 0 < raw.loc["000002.SZ", "scr"]

    # 预计算基准均值与即时计算必须完全一致
    precomp = precompute_pct_turn_base(turnover, x_window=40)
    raw_fast = compute_raw_turnover_factors(
        turnover, target_day, k_window=20, x_window=40, pct_turn_base_mean=precomp
    )
    pd.testing.assert_frame_equal(raw, raw_fast)


def test_no_lookahead_when_future_turnover_changes() -> None:
    panels = _synthetic_panels(n_days=140, n_stocks=30, seed=7)
    turnover = panels["turnover"].copy()
    cut_day = turnover.index[80]

    raw_before = compute_raw_turnover_factors(turnover, cut_day, k_window=20, x_window=40)
    # 极端篡改 cut_day 之后的未来数据
    turnover_mutated = turnover.copy()
    turnover_mutated.iloc[81:] = 99.0
    raw_after = compute_raw_turnover_factors(turnover_mutated, cut_day, k_window=20, x_window=40)
    pd.testing.assert_frame_equal(raw_before, raw_after)


def test_universe_filter_excludes_st_new_and_suspended() -> None:
    panels = _synthetic_panels(n_days=100, n_stocks=20, seed=11)
    day = panels["turnover"].index[-1]
    turn_today = panels["turnover"].loc[day].copy()
    turn_today.iloc[2] = 0.0  # 停牌
    turn_today.iloc[3] = np.nan  # 缺失

    pool = eligible_universe(
        day,
        turnover_today=turn_today,
        total_mv=panels["total_mv"].loc[day],
        is_st=panels["is_st"].loc[day],
        list_date=panels["list_date"],
    )
    codes = panels["turnover"].columns
    assert codes[0] not in pool  # ST
    assert codes[1] not in pool  # 上市未满 120 天
    assert codes[2] not in pool  # 停牌 (turnover=0)
    assert codes[3] not in pool  # NaN
    assert len(pool) == 16


def test_neutralization_orthogonality_for_size_and_industry() -> None:
    rng = np.random.default_rng(123)
    idx = pd.Index([f"{i:06d}.SH" for i in range(100)])
    log_mv = pd.Series(rng.normal(23.0, 1.2, size=100), index=idx)
    total_mv = np.exp(log_mv)
    industry = pd.Series([f"IND_{i % 5}" for i in range(100)], index=idx)
    ind_effect = industry.map({f"IND_{k}": float(k) for k in range(5)})
    raw = 2.5 * log_mv + 1.5 * ind_effect + rng.normal(0.0, 0.5, size=100)

    size_neut = neutralize_by_size(raw, total_mv)
    assert abs(size_neut.corr(log_mv)) < 1e-10
    assert size_neut.mean() == pytest.approx(0.0, abs=1e-10)
    assert size_neut.std(ddof=1) == pytest.approx(1.0, abs=1e-10)

    styles = pd.DataFrame({"size": log_mv, "bp": rng.uniform(0.2, 2.0, size=100)}, index=idx)
    pure = neutralize_style_industry(raw, styles, industry=industry)
    assert abs(pure.corr(log_mv)) < 1e-10
    # 每个行业的残差均值应接近 0
    for grp_mean in pure.groupby(industry).mean():
        assert abs(grp_mean) < 1e-10


def test_winsorize_mad_clips_outliers() -> None:
    s = pd.Series([1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 100.0, -80.0])
    clipped = winsorize_mad(s, scale=5.0)
    assert clipped.max() < 5.0
    assert clipped.min() > -5.0


def test_cross_section_and_monthly_evaluation_monotonic_signal() -> None:
    panels = _synthetic_panels(n_days=260, n_stocks=50, seed=99)
    params = TurnoverStabilityParams(k_window=20, x_window=40, deciles=5, top_fraction=0.2)
    m_ends = month_end_dates(panels["turnover"].index, "2022-04-01", "2022-12-31")
    assert len(m_ends) >= 8

    # 用明确的人工收益验证单因子检验逻辑：低因子值组 G1 稳定跑赢高因子值组 G5
    factor_by_date: dict[pd.Timestamp, pd.Series] = {}
    precomp = precompute_pct_turn_base(panels["turnover"], x_window=params.x_window)
    returns = panels["returns"].copy()

    for i, day in enumerate(m_ends):
        cs = compute_cross_section_factors(
            day,
            turnover=panels["turnover"],
            total_mv=panels["total_mv"].loc[day],
            is_st=panels["is_st"].loc[day],
            list_date=panels["list_date"],
            params=params,
            pct_turn_base_mean=precomp,
            returns=panels["returns"],
            pb=panels["pb"].loc[day],
            pe_ttm=panels["pe_ttm"].loc[day],
            industry=panels["industry"],
            include_pure_scr=True,
        )
        assert {"turn20", "pct_turn20", "str", "scr", "pure_scr"}.issubset(cs.columns)
        factor_by_date[day] = cs["scr"]
        if i + 1 < len(m_ends):
            nxt = m_ends[i + 1]
            mask = (returns.index > day) & (returns.index <= nxt)
            # 注入与 scr 强负相关的次月收益
            alpha = (-0.002 * cs["scr"]).reindex(returns.columns).fillna(0.0)
            returns.loc[mask] = alpha.to_numpy()

    ev = evaluate_factor_monthly(factor_by_date, returns, deciles=5, commission=0.0)
    summary = ev["summary"]
    assert summary["月度IC均值"] < -0.5
    assert summary["月度RankIC均值"] < -0.5
    assert summary["多空年化收益"] > 0.0
    assert summary["多空月度胜率"] == pytest.approx(1.0)
    # G1 年化应严格大于 G5
    dm = ev["decile_monthly"]
    assert dm["G1"].mean() > dm["G5"].mean()
    yr = yearly_factor_table(dm, deciles=5)
    assert not yr.empty and 2022 in yr.index


def test_backtest_weights_drift_and_commission() -> None:
    dates = pd.bdate_range("2024-01-02", periods=6)
    returns = pd.DataFrame(
        {
            "A": [0.0, 0.10, 0.00, 0.00, 0.00, 0.00],
            "B": [0.0, -0.10, 0.00, 0.00, 0.00, 0.00],
        },
        index=dates,
    )
    targets = {
        dates[0]: pd.Series({"A": 0.5, "B": 0.5}),
        dates[2]: pd.Series({"A": 0.0, "B": 1.0}),
    }
    bt_no_fee = backtest_weights(returns, targets, commission=0.0)
    bt_fee = backtest_weights(returns, targets, commission=0.001)

    # 第 1 个调仓日建仓双边换手 = 1.0；第 2 个调仓日漂移后 A 权 0.55, B 权 0.45，全换到 B 双边换手 = 1.10
    assert bt_no_fee.loc[dates[1], "turnover"] == pytest.approx(1.0)
    assert bt_no_fee.loc[dates[3], "turnover"] == pytest.approx(1.10)
    assert bt_fee.loc[dates[1], "return"] == pytest.approx(bt_no_fee.loc[dates[1], "return"] - 0.001)
    assert bt_fee.loc[dates[3], "return"] == pytest.approx(bt_no_fee.loc[dates[3], "return"] - 0.0011)

    metrics = performance(bt_fee["return"], periods=252)
    assert set(metrics.keys()) == {"累计收益", "年化收益", "年化波动", "最大回撤", "夏普比率", "卡玛比率"}


def test_select_equal_weight_and_deciles() -> None:
    score = pd.Series(np.arange(20, dtype=float), index=[f"S{i:02d}" for i in range(20)])
    w_frac = select_equal_weight(score, top_fraction=0.10)
    assert list(w_frac.index) == ["S00", "S01"]
    assert w_frac.sum() == pytest.approx(1.0)

    w_top = select_equal_weight(score, top_n=4)
    assert list(w_top.index) == ["S00", "S01", "S02", "S03"]
    assert w_top.sum() == pytest.approx(1.0)

    groups = decile_groups(score, groups=10)
    assert len(groups) == 10
    assert list(groups[0]) == ["S00", "S01"]
    assert list(groups[-1]) == ["S18", "S19"]
