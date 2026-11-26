"""量稳换手率选股策略复现（东吴证券 2021-12-07《改进 STR——换手率要比别人稳，也要比自己稳》）。

运行示例：

    .venv/bin/python -m examples.turnover_stability

数据说明：
- 全 A 日频行情、日频估值/换手、ST 列表与行业/基础信息复用本地已缓存的 DataHub DuckDB 数据；
- 沪深 300（000300.SH）与中证 500（000905.SH）历史成分股权重通过 DataHub 按半年分片拉取并缓存到
  ``data/turnover_stability/cache/``，后续运行直接读取本地缓存。
- 复现结果保存在 ``examples/turnover_stability/``。本脚本仅执行离线研究与回测，不会下单。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.datahub.duckdb_frames import frame_exists, frame_paths, read_frame, write_frame
from src.strategy_evaluation import summarize_research_returns
from src.strategy.turnover_stability import (
    ALL_FACTOR_NAMES,
    FACTOR_NAMES,
    TurnoverStabilityParams,
    backtest_weights,
    compute_cross_section_factors,
    evaluate_factor_monthly,
    month_end_dates,
    performance,
    precompute_pct_turn_base,
    select_equal_weight,
    summarize_factor,
    yearly_factor_table,
)
from src.trading.strategies import write_native_weights

DAILY_DIR = Path("data") / "micro_cap_timing_plus" / "raw"
REF_DIR = Path("data") / "free_cash_flow" / "reference"
CACHE_DIR = Path("data") / "turnover_stability" / "cache"
OUTPUT_DIR = Path("examples") / "turnover_stability"

IN_SAMPLE_START = "2013-01-01"
IN_SAMPLE_END = "2021-10-31"
OOS_START = "2021-11-01"
OOS_END = "2026-10-30"

BENCHMARKS = {
    "中证全指": "000985.CSI",
    "沪深300全收益": "H00300.CSI",
    "中证500全收益": "H00905.CSI",
}

PARAM_K_GRID = (10, 20, 30, 40, 60)
PARAM_X_GRID = (20, 30, 40, 50, 60)


# ---------------------------------------------------------------------------
# 数据加载（复用本地缓存 + DataHub 扩展查询缓存）
# ---------------------------------------------------------------------------


def _load_daily_table(api: str, columns: list[str], start: str) -> pd.DataFrame:
    start_key = start.replace("-", "")
    files = [path for path in frame_paths(DAILY_DIR / api) if path.stem >= start_key]
    if not files:
        raise FileNotFoundError(f"未找到本地日频缓存: {DAILY_DIR / api}")
    frames = [read_frame(path, columns=columns) for path in files]
    frame = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def load_market_panels(data_start: str) -> dict[str, pd.DataFrame]:
    daily = _load_daily_table("daily", ["ts_code", "trade_date", "pct_chg"], data_start)
    basic = _load_daily_table(
        "daily_basic",
        ["ts_code", "trade_date", "turnover_rate", "total_mv", "pb", "pe_ttm"],
        data_start,
    )
    st = _load_daily_table("stock_st", ["ts_code", "trade_date"], data_start)

    def pivot(frame: pd.DataFrame, col: str) -> pd.DataFrame:
        return frame.pivot_table(index="trade_date", columns="ts_code", values=col, aggfunc="last").sort_index()

    returns = pivot(daily, "pct_chg") / 100.0
    idx = returns.index
    cols = returns.columns
    st["flag"] = 1.0

    return {
        "returns": returns,
        "turnover": pivot(basic, "turnover_rate").reindex(index=idx, columns=cols),
        "total_mv": pivot(basic, "total_mv").reindex(index=idx, columns=cols) * 1e4,  # 万元 -> 元
        "pb": pivot(basic, "pb").reindex(index=idx, columns=cols),
        "pe_ttm": pivot(basic, "pe_ttm").reindex(index=idx, columns=cols),
        "is_st": pivot(st, "flag").reindex(index=idx, columns=cols).notna(),
    }


def load_reference() -> tuple[pd.Series, pd.DataFrame]:
    basic = read_frame(REF_DIR / "stock_basic.duckdb").drop_duplicates("ts_code").set_index("ts_code")
    list_date = pd.to_datetime(basic["list_date"], errors="coerce")
    members = read_frame(REF_DIR / "citic_member.duckdb")
    members["in_date"] = pd.to_datetime(members["in_date"], errors="coerce").fillna(pd.Timestamp("1990-01-01"))
    members["out_date"] = pd.to_datetime(members["out_date"], errors="coerce").fillna(pd.Timestamp("2099-12-31"))
    return list_date, members


def industry_asof(members: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    active = (
        members[(members["in_date"] <= date) & (members["out_date"] > date)]
        .sort_values("in_date")
        .drop_duplicates("ts_code", keep="last")
    )
    latest = members.sort_values("in_date").drop_duplicates("ts_code", keep="last")
    return active.set_index("ts_code")["l1_name"].combine_first(latest.set_index("ts_code")["l1_name"])


def load_benchmark_returns(trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    series = {}
    for name, code in BENCHMARKS.items():
        frame = read_frame(REF_DIR / f"index_{code}.duckdb")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        close = frame.set_index("trade_date")["close"].sort_index()
        series[name] = close.reindex(trading_days).pct_change(fill_method=None)
    return pd.DataFrame(series, index=trading_days)


def load_index_weights(index_code: str, start_year: int = 2012, end_year: int = 2026) -> pd.DataFrame:
    """读取/拉取指数历史成分权重（严格经 DataHub，按半年分片避免单次行数截断）。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"index_weight_{index_code}.duckdb"
    if frame_exists(path):
        df = read_frame(path)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    from src.utils.datahub_client import DataHubClient

    client = DataHubClient(token=os.environ.get("TUSHARE_TOKEN"))
    chunks: list[pd.DataFrame] = []
    for yr in range(start_year, end_year + 1):
        for s_md, e_md in (("0101", "0630"), ("0701", "1231")):
            part = client.query(
                "index_weight",
                index_code=index_code,
                start_date=f"{yr}{s_md}",
                end_date=f"{yr}{e_md}",
            )
            if part is not None and not part.empty:
                chunks.append(part[["index_code", "con_code", "trade_date", "weight"]])
    if not chunks:
        raise RuntimeError(f"DataHub 未返回 {index_code} 历史成分权重")
    df = pd.concat(chunks, ignore_index=True).drop_duplicates(["con_code", "trade_date"])
    write_frame(path, df)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def index_constituents_asof(weights: pd.DataFrame, date: pd.Timestamp) -> list[str]:
    """返回 ``<= date`` 最近一期公布的指数成分股代码列表（无前视偏差）。"""
    avail = weights[weights["trade_date"] <= date]
    if avail.empty:
        return []
    snap_date = avail["trade_date"].max()
    return avail.loc[avail["trade_date"] == snap_date, "con_code"].dropna().unique().tolist()


# ---------------------------------------------------------------------------
# 回测与评估主流程
# ---------------------------------------------------------------------------


def slice_factor_summary(ev: dict[str, object], start: str, end: str) -> dict[str, float]:
    ic = ev["ic_series"].loc[start:end]
    ric = ev["rank_ic_series"].loc[start:end]
    dm = ev["decile_monthly"].loc[start:end]
    return summarize_factor(ic, ric, dm, g1_turnover=ev["summary"].get("多头月均单边换手", np.nan))


def run_universe_factors(
    rebalance_days: list[pd.Timestamp],
    panels: dict[str, pd.DataFrame],
    list_date: pd.Series,
    members: pd.DataFrame,
    params: TurnoverStabilityParams,
    *,
    universe_fn=None,
    include_pure_scr: bool = False,
) -> dict[str, dict[pd.Timestamp, pd.Series]]:
    names = ALL_FACTOR_NAMES if include_pure_scr else FACTOR_NAMES
    factors: dict[str, dict[pd.Timestamp, pd.Series]] = {name: {} for name in names}
    precomp = precompute_pct_turn_base(
        panels["turnover"],
        x_window=params.x_window,
        min_base_ratio=params.min_base_ratio,
    )
    for day in rebalance_days:
        codes = universe_fn(day) if universe_fn is not None else None
        ind = industry_asof(members, day) if include_pure_scr else None
        cs = compute_cross_section_factors(
            day,
            turnover=panels["turnover"],
            total_mv=panels["total_mv"].loc[day],
            is_st=panels["is_st"].loc[day],
            list_date=list_date,
            params=params,
            universe_codes=codes,
            pct_turn_base_mean=precomp,
            returns=panels["returns"] if include_pure_scr else None,
            pb=panels["pb"].loc[day] if include_pure_scr else None,
            pe_ttm=panels["pe_ttm"].loc[day] if include_pure_scr else None,
            industry=ind,
            include_pure_scr=include_pure_scr,
        )
        if cs.empty:
            continue
        for name in names:
            if name in cs:
                factors[name][day] = cs[name].dropna()
    return factors


def run_param_sensitivity(
    rebalance_days: list[pd.Timestamp],
    panels: dict[str, pd.DataFrame],
    list_date: pd.Series,
    base_params: TurnoverStabilityParams,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """复现研报表 9：不同 (K, X) 参数组合下 SCR 因子 10 分组多空信息比率（样本内 & 发表后样本外）。"""
    from src.strategy.turnover_stability import (
        decile_groups,
        eligible_universe,
        neutralize_by_size,
        period_forward_returns,
    )

    grid_is = pd.DataFrame(index=PARAM_K_GRID, columns=PARAM_X_GRID, dtype=float)
    grid_oos = pd.DataFrame(index=PARAM_K_GRID, columns=PARAM_X_GRID, dtype=float)
    grid_is.index.name = grid_oos.index.name = "K"

    clean_turn = panels["turnover"].astype(float).where(lambda df: df > 0)
    # 预先按月底截面计算有效股票池与下月收益，避免在 25 组参数网格中重复计算
    pools = {
        day: eligible_universe(
            day,
            turnover_today=panels["turnover"].loc[day],
            total_mv=panels["total_mv"].loc[day],
            is_st=panels["is_st"].loc[day],
            list_date=list_date,
            params=base_params,
        )
        for day in rebalance_days
    }
    fwd_by_pair = {
        (rebalance_days[i], rebalance_days[i + 1]): period_forward_returns(
            panels["returns"], rebalance_days[i], rebalance_days[i + 1]
        )
        for i in range(len(rebalance_days) - 1)
    }

    # 预计算不同窗口的日度滚动标准差与有效天数
    roll_std: dict[int, pd.DataFrame] = {}
    for w in sorted(set(PARAM_K_GRID) | set(PARAM_X_GRID)):
        min_obs = max(2, int(np.ceil(w * base_params.min_cur_ratio)))
        roll_std[w] = clean_turn.rolling(w, min_periods=min_obs).std(ddof=1)

    for k_win in PARAM_K_GRID:
        cur_std_all = roll_std[k_win]
        for x_win in PARAM_X_GRID:
            base_std_all = roll_std[x_win].shift(k_win)
            scr_panel = (cur_std_all / base_std_all.where(base_std_all > 0) - 1.0).loc[rebalance_days]

            ls_rows: dict[pd.Timestamp, float] = {}
            for i in range(len(rebalance_days) - 1):
                day, next_day = rebalance_days[i], rebalance_days[i + 1]
                pool = pools[day]
                if len(pool) < base_params.deciles:
                    continue
                score = neutralize_by_size(
                    scr_panel.loc[day].reindex(pool),
                    panels["total_mv"].loc[day].reindex(pool),
                    mad_scale=base_params.mad_scale,
                ).dropna()
                if len(score) < base_params.deciles:
                    continue
                groups = decile_groups(score, groups=base_params.deciles, ascending=True)
                fwd = fwd_by_pair[(day, next_day)]
                g1 = float(fwd.reindex(groups[0]).dropna().mean())
                g10 = float(fwd.reindex(groups[-1]).dropna().mean())
                if np.isfinite(g1) and np.isfinite(g10) and (1.0 + g10) > 0:
                    ls_rows[next_day] = (1.0 + g1) / (1.0 + g10) - 1.0

            ls_series = pd.Series(ls_rows, dtype=float).sort_index()
            grid_is.loc[k_win, x_win] = performance(ls_series.loc[IN_SAMPLE_START:IN_SAMPLE_END], periods=12)["夏普比率"]
            grid_oos.loc[k_win, x_win] = performance(ls_series.loc[OOS_START:OOS_END], periods=12)["夏普比率"]
    return grid_is, grid_oos


def _plot_results(
    all_a_evals: dict[str, dict[str, object]],
    long_only_daily: pd.DataFrame,
    csi300_daily: pd.DataFrame | None,
    out: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Sarasa Gothic SC",
        "WenQuanYi Micro Hei",
        "SimHei",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    pub_date = pd.Timestamp("2021-12-07")

    # 图 1：多空对冲净值 + 全 A 纯多头组合 + 沪深 300 组合
    n_rows = 3 if csi300_daily is not None else 2
    fig, axes = plt.subplots(n_rows, 1, figsize=(12, 4.2 * n_rows), sharex=False)
    if n_rows == 2:
        axes = list(axes)

    ls_labels = {
        "turn20": ("Turn20 多空", "#6b7280", 1.3),
        "pct_turn20": ("PctTurn20 多空", "#8b5cf6", 1.3),
        "str": ("STR 多空", "#0f766e", 1.8),
        "scr": ("SCR 多空", "#dc2626", 2.0),
        "pure_scr": ("纯净 SCR 多空", "#2563eb", 1.6),
    }
    ax0 = axes[0]
    for key, (label, color, lw) in ls_labels.items():
        if key not in all_a_evals:
            continue
        dm = all_a_evals[key]["decile_monthly"]["ls"].dropna()
        nav = (1.0 + dm).cumprod()
        ax0.plot(nav.index, nav.values, label=label, color=color, linewidth=lw)
    ax0.axvline(pub_date, color="#111827", linestyle="--", linewidth=1.0, label="研报发布日 (2021-12-07)")
    ax0.set_yscale("log")
    ax0.set_title("全 A 换手率因子族 10 分组多空对冲净值（对数坐标，月频）")
    ax0.legend(loc="upper left", ncol=3, frameon=False)
    ax0.grid(alpha=0.3)

    ax1 = axes[1]
    lo_cols = [
        ("全A_STR_Top10%", "#0f766e", 1.8),
        ("全A_SCR_Top10%", "#dc2626", 1.9),
        ("全A_SCR_Top50", "#ea580c", 1.5),
        ("全A_PureSCR_Top10%", "#2563eb", 1.5),
        ("中证全指", "#6b7280", 1.3),
    ]
    for col, color, lw in lo_cols:
        if col in long_only_daily:
            nav = (1.0 + long_only_daily[col].fillna(0.0)).cumprod()
            ax1.plot(nav.index, nav.values, label=col, color=color, linewidth=lw)
    ax1.axvline(pub_date, color="#111827", linestyle="--", linewidth=1.0)
    ax1.set_yscale("log")
    ax1.set_title("全 A 纯多头月频选股组合 vs 中证全指（含万 0.854 佣金，对数坐标）")
    ax1.legend(loc="upper left", ncol=3, frameon=False)
    ax1.grid(alpha=0.3)

    if csi300_daily is not None:
        ax2 = axes[2]
        for col, color, lw in (
            ("沪深300_Turn20_Top10%", "#6b7280", 1.4),
            ("沪深300_STR_Top10%", "#0f766e", 1.7),
            ("沪深300_SCR_Top10%", "#dc2626", 2.0),
            ("沪深300全收益", "#111827", 1.3),
        ):
            if col in csi300_daily:
                nav = (1.0 + csi300_daily[col].fillna(0.0)).cumprod()
                ax2.plot(nav.index, nav.values, label=col, color=color, linewidth=lw)
        ax2.axvline(pub_date, color="#111827", linestyle="--", linewidth=1.0)
        ax2.set_yscale("log")
        ax2.set_title("沪深 300 成分内 Top10% 月频组合 vs 沪深 300 全收益（研报 4.5 节）")
        ax2.legend(loc="upper left", ncol=4, frameon=False)
        ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out / "nav.png", dpi=130)
    plt.close(fig)

    # 图 2：10 分组年化收益单调性 + 组内收益标准差对比（对应研报图 3 / 图 9）
    fig, (bx1, bx2) = plt.subplots(1, 2, figsize=(13, 5))
    groups = [f"G{g}" for g in range(1, 11)]
    x = np.arange(len(groups))
    width = 0.25
    for offset, key, label, color in (
        (-width, "turn20", "Turn20", "#6b7280"),
        (0.0, "str", "STR", "#0f766e"),
        (width, "scr", "SCR", "#dc2626"),
    ):
        dm = all_a_evals[key]["decile_monthly"][groups]
        ann = [performance(dm[g].dropna(), periods=12)["年化收益"] * 100 for g in groups]
        bx1.bar(x + offset, ann, width=width, label=label, color=color, alpha=0.9)
        disp = all_a_evals[key]["group_dispersion"][groups].to_numpy() * 100
        bx2.plot(x, disp, marker="o", label=label, color=color, linewidth=1.8)

    bx1.set_xticks(x, groups)
    bx1.set_ylabel("年化收益率 (%)")
    bx1.set_title("全区间 10 分组年化收益（G1 多头 → G10 空头）")
    bx1.legend(frameon=False)
    bx1.grid(axis="y", alpha=0.3)

    bx2.set_xticks(x, groups)
    bx2.set_ylabel("下月组内收益横截面标准差均值 (%)")
    bx2.set_title("10 分组组内收益离散度对比（复现研报图 3 / 图 9）")
    bx2.legend(frameon=False)
    bx2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out / "deciles.png", dpi=130)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="量稳换手率选股策略复现（东吴证券 STR / SCR）")
    parser.add_argument("--data-start", default="2012-10-01")
    parser.add_argument("--start", default=IN_SAMPLE_START)
    parser.add_argument("--end", default=OOS_END)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--skip-param-grid", action="store_true")
    parser.add_argument("--skip-index-universes", action="store_true")
    args = parser.parse_args()

    params = TurnoverStabilityParams()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    print("1/6 加载本地日频行情、换手率、ST、基础信息与行业数据...")
    panels = load_market_panels(args.data_start)
    list_date, members = load_reference()
    trading_days = panels["returns"].index
    bench_ret = load_benchmark_returns(trading_days)

    # 首个信号取 2012-12 月底，次月 2013-01 首个交易日起计收益；覆盖至 args.end
    signal_start = (pd.Timestamp(args.start) - pd.DateOffset(months=1)).strftime("%Y-%m-01")
    rebalance_days = month_end_dates(trading_days, signal_start, args.end)
    print(f"   交易日范围: {trading_days[0].date()} ~ {trading_days[-1].date()} ({len(trading_days)} 天), 月底截面: {len(rebalance_days)} 期")

    print("2/6 计算全 A 截面因子（Turn20 / PctTurn20 / STR / SCR / PureSCR）...")
    all_a_factors = run_universe_factors(
        rebalance_days,
        panels,
        list_date,
        members,
        params,
        include_pure_scr=True,
    )

    all_a_evals: dict[str, dict[str, object]] = {}
    factor_rows: list[dict[str, object]] = []
    decile_ann_rows: dict[str, dict[str, float]] = {}
    dispersion_rows: dict[str, pd.Series] = {}

    for name in ALL_FACTOR_NAMES:
        ev = evaluate_factor_monthly(all_a_factors[name], panels["returns"], deciles=params.deciles, commission=0.0)
        all_a_evals[name] = ev
        for period_name, p_start, p_end in (
            ("全区间(2013-2026)", args.start, args.end),
            ("研报重叠(2013-2021.10)", IN_SAMPLE_START, IN_SAMPLE_END),
            ("发表后样本外(2021.11-2026.10)", OOS_START, OOS_END),
        ):
            row = {"因子": name, "区间": period_name, **slice_factor_summary(ev, p_start, p_end)}
            factor_rows.append(row)
        dm_full = ev["decile_monthly"].loc[args.start:args.end]
        decile_ann_rows[name] = {
            f"G{g}": performance(dm_full[f"G{g}"].dropna(), periods=12)["年化收益"]
            for g in range(1, params.deciles + 1)
        }
        dispersion_rows[name] = ev["group_dispersion"]

    factor_summary_df = pd.DataFrame(factor_rows)
    decile_ann_df = pd.DataFrame(decile_ann_rows).T
    dispersion_df = pd.DataFrame(dispersion_rows).T

    yearly_str = yearly_factor_table(all_a_evals["str"]["decile_monthly"].loc[args.start:args.end])
    yearly_scr = yearly_factor_table(all_a_evals["scr"]["decile_monthly"].loc[args.start:args.end])
    yearly_pure_scr = yearly_factor_table(all_a_evals["pure_scr"]["decile_monthly"].loc[args.start:args.end])

    print("3/6 构建全 A 纯多头月频可交易组合（含万 0.854 佣金）...")
    long_targets: dict[str, dict[pd.Timestamp, pd.Series]] = {
        "全A_Turn20_Top10%": {},
        "全A_STR_Top10%": {},
        "全A_SCR_Top10%": {},
        "全A_PureSCR_Top10%": {},
        "全A_STR_Top50": {},
        "全A_SCR_Top50": {},
        "全A_PureSCR_Top50": {},
    }
    for day in rebalance_days:
        for fac, label in (
            ("turn20", "全A_Turn20_Top10%"),
            ("str", "全A_STR_Top10%"),
            ("scr", "全A_SCR_Top10%"),
            ("pure_scr", "全A_PureSCR_Top10%"),
        ):
            if day in all_a_factors[fac]:
                long_targets[label][day] = select_equal_weight(all_a_factors[fac][day], top_fraction=params.top_fraction)
        for fac, label in (
            ("str", "全A_STR_Top50"),
            ("scr", "全A_SCR_Top50"),
            ("pure_scr", "全A_PureSCR_Top50"),
        ):
            if day in all_a_factors[fac]:
                long_targets[label][day] = select_equal_weight(all_a_factors[fac][day], top_n=params.top_n)

    long_bt = {name: backtest_weights(panels["returns"], tgt, commission=params.commission) for name, tgt in long_targets.items()}
    long_daily = pd.DataFrame({name: r["return"] for name, r in long_bt.items()}).loc[args.start:args.end]
    long_daily = long_daily.join(bench_ret.reindex(long_daily.index))

    perf_rows: list[dict[str, object]] = []
    for period_name, p_start, p_end in (
        ("全区间(2013-2026)", args.start, args.end),
        ("研报重叠(2013-2021.10)", IN_SAMPLE_START, IN_SAMPLE_END),
        ("发表后样本外(2021.11-2026.10)", OOS_START, OOS_END),
    ):
        sub = long_daily.loc[p_start:p_end]
        for col in sub.columns:
            m = summarize_research_returns(sub[col].dropna())
            turn = np.nan
            if col in long_bt:
                t_s = long_bt[col]["turnover"].loc[p_start:p_end]
                pos = t_s[t_s > 0]
                turn = float(pos.mean() / 2.0) if not pos.empty else 0.0
            perf_rows.append({"组合": col, "区间": period_name, **m, "月均单边换手": turn})

    csi300_daily: pd.DataFrame | None = None
    index_summary_rows: list[dict[str, object]] = []
    csi300_targets: dict[str, dict[pd.Timestamp, pd.Series]] = {}

    if not args.skip_index_universes:
        print("4/6 测试沪深 300 与中证 500 成分股子样本及沪深 300 Top10% 投资组合（研报 4.4 / 4.5 节）...")
        for idx_label, idx_code in (("沪深300", "000300.SH"), ("中证500", "000905.SH")):
            w_df = load_index_weights(idx_code)
            u_factors = run_universe_factors(
                rebalance_days,
                panels,
                list_date,
                members,
                params,
                universe_fn=lambda d, w=w_df: index_constituents_asof(w, d),
                include_pure_scr=False,
            )
            for fac in ("turn20", "str", "scr"):
                ev = evaluate_factor_monthly(u_factors[fac], panels["returns"], deciles=params.deciles, commission=0.0)
                for period_name, p_start, p_end in (
                    ("全区间(2013-2026)", args.start, args.end),
                    ("研报重叠(2013-2021.10)", IN_SAMPLE_START, IN_SAMPLE_END),
                    ("发表后样本外(2021.11-2026.10)", OOS_START, OOS_END),
                ):
                    index_summary_rows.append(
                        {"样本空间": idx_label, "因子": fac, "区间": period_name, **slice_factor_summary(ev, p_start, p_end)}
                    )
            if idx_label == "沪深300":
                for fac, label in (
                    ("turn20", "沪深300_Turn20_Top10%"),
                    ("str", "沪深300_STR_Top10%"),
                    ("scr", "沪深300_SCR_Top10%"),
                ):
                    csi300_targets[label] = {
                        day: select_equal_weight(u_factors[fac][day], top_fraction=params.top_fraction)
                        for day in rebalance_days
                        if day in u_factors[fac]
                    }
                csi300_bt = {
                    name: backtest_weights(panels["returns"], tgt, commission=params.commission)
                    for name, tgt in csi300_targets.items()
                }
                csi300_daily = pd.DataFrame({name: r["return"] for name, r in csi300_bt.items()}).loc[args.start:args.end]
                csi300_daily = csi300_daily.join(bench_ret[["沪深300全收益"]].reindex(csi300_daily.index))
                for period_name, p_start, p_end in (
                    ("全区间(2013-2026)", args.start, args.end),
                    ("研报重叠(2013-2021.10)", IN_SAMPLE_START, IN_SAMPLE_END),
                    ("发表后样本外(2021.11-2026.10)", OOS_START, OOS_END),
                ):
                    sub = csi300_daily.loc[p_start:p_end]
                    for col in sub.columns:
                        if col == "沪深300全收益":
                            continue
                        m = summarize_research_returns(sub[col].dropna())
                        t_s = csi300_bt[col]["turnover"].loc[p_start:p_end]
                        pos = t_s[t_s > 0]
                        turn = float(pos.mean() / 2.0) if not pos.empty else 0.0
                        perf_rows.append({"组合": col, "区间": period_name, **m, "月均单边换手": turn})

    param_is_df = pd.DataFrame()
    param_oos_df = pd.DataFrame()
    if not args.skip_param_grid:
        print("5/6 运行 SCR 参数敏感性网格 (K x X，对应研报表 9)...")
        param_is_df, param_oos_df = run_param_sensitivity(rebalance_days, panels, list_date, params)

    print("6/6 导出结果文件与图表...")
    perf_df = pd.DataFrame(perf_rows)
    factor_summary_df.to_csv(out / "factor_summary.csv", index=False)
    perf_df.to_csv(out / "performance_metrics.csv", index=False)
    decile_ann_df.to_csv(out / "decile_annual_returns.csv")
    dispersion_df.to_csv(out / "group_dispersion.csv")
    yearly_str.to_csv(out / "yearly_str.csv")
    yearly_scr.to_csv(out / "yearly_scr.csv")
    yearly_pure_scr.to_csv(out / "yearly_pure_scr.csv")
    (1.0 + long_daily.fillna(0.0)).cumprod().to_csv(out / "cumulative_returns.csv")
    if index_summary_rows:
        pd.DataFrame(index_summary_rows).to_csv(out / "index_universe_summary.csv", index=False)
    if not param_is_df.empty:
        param_is_df.to_csv(out / "param_sensitivity_is.csv")
        param_oos_df.to_csv(out / "param_sensitivity_oos.csv")

    # 导出最新一期 SCR Top50 持仓与标准 native_weights
    for name in ("全A_SCR_Top50", "全A_STR_Top50"):
        write_native_weights(long_targets[name], out / "trading" / name / "native_weights.csv")
    if "沪深300_SCR_Top10%" in csi300_targets:
        write_native_weights(
            csi300_targets["沪深300_SCR_Top10%"],
            out / "trading" / "沪深300_SCR_Top10%" / "native_weights.csv",
        )

    latest_day = max(all_a_factors["scr"])
    latest_scr = all_a_factors["scr"][latest_day].sort_values(ascending=True).head(params.top_n)
    latest_scr.rename("scr_zscore").to_csv(out / "latest_scr_top50.csv")

    _plot_results(all_a_evals, long_daily, csi300_daily, out)

    summary_payload = {
        "data_range": {"start": str(trading_days[0].date()), "end": str(trading_days[-1].date())},
        "rebalance_months": len(rebalance_days),
        "commission": params.commission,
        "in_sample": [IN_SAMPLE_START, IN_SAMPLE_END],
        "post_publication": [OOS_START, OOS_END],
        "latest_signal_date": str(latest_day.date()),
    }
    (out / "summary.json").write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    print("\n=== 全 A 因子汇总（IC / RankIC / 多空对冲） ===")
    show_cols = ["因子", "区间", "月度IC均值", "年化ICIR", "月度RankIC均值", "年化RankICIR", "多空年化收益", "多空年化波动", "多空信息比率", "多空月度胜率", "多空最大回撤"]
    print(factor_summary_df[show_cols].to_string(index=False))

    print("\n=== 纯多头组合回测绩效（含万 0.854 佣金） ===")
    print(perf_df.to_string(index=False))

    if index_summary_rows:
        idx_df = pd.DataFrame(index_summary_rows)
        print("\n=== 沪深 300 / 中证 500 样本空间多空对冲 ===")
        print(idx_df[["样本空间", "因子", "区间", "多空年化收益", "多空年化波动", "多空信息比率", "多空月度胜率", "多空最大回撤"]].to_string(index=False))

    print("\n=== STR 分年度表现（2013-2026） ===")
    print(yearly_str.to_string())
    print("\n=== SCR 分年度表现（2013-2026） ===")
    print(yearly_scr.to_string())

    if not param_is_df.empty:
        print("\n=== SCR 参数敏感性 IR（研报重叠 2013-2021.10） ===")
        print(param_is_df.to_string())
        print("\n=== SCR 参数敏感性 IR（发表后样本外 2021.11-2026.10） ===")
        print(param_oos_df.to_string())


if __name__ == "__main__":
    main()
