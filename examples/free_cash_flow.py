"""增强型自由现金流策略复现（国泰海通 2026-10-17 研报）。

先缓存数据（Tushare，经 DataHub）：

    uv run python -m scripts.fetch_free_cash_flow_data
    uv run python -m examples.free_cash_flow

结果保存在 examples/free_cash_flow/。本脚本只读取本地缓存并执行回测，不会下单。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.strategy.free_cash_flow import (
    FACTORS,
    FreeCashFlowParams,
    backtest_weights,
    build_fundamentals,
    candidate_pool,
    performance,
    quantile_groups,
    rebalance_dates,
    select,
    selection_cutoff,
)

DATA_DIR = Path("data") / "free_cash_flow"
DAILY_DIR = Path("data") / "micro_cap_timing_plus" / "raw"
OUTPUT_DIR = Path("examples") / "free_cash_flow"
BENCHMARKS = {
    "中证现金流全收益": "932365CNY010.CSI",
    "中证现金流": "932365.CSI",
    "300现金流": "932366.CSI",
    "500现金流": "932367.CSI",
    "中证红利全收益": "H00922.CSI",
    "上证50全收益": "H00016.CSI",
    "沪深300全收益": "H00300.CSI",
    "中证500全收益": "H00905.CSI",
    "创业板指全收益": "399606.SZ",
}


# ---------------------------------------------------------------------------
# 数据装配
# ---------------------------------------------------------------------------


def _load_daily(api: str, columns: list[str], start: str) -> pd.DataFrame:
    files = sorted(p for p in (DAILY_DIR / api).glob("*.parquet") if p.stem >= start.replace("-", ""))
    frames = [pd.read_parquet(p, columns=columns) for p in files]
    frame = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def load_panels(start: str) -> dict[str, pd.DataFrame]:
    daily = _load_daily("daily", ["ts_code", "trade_date", "pct_chg", "amount"], start)
    basic = _load_daily("daily_basic", ["ts_code", "trade_date", "total_mv", "pb"], start)
    st = _load_daily("stock_st", ["ts_code", "trade_date"], start)

    def pivot(frame: pd.DataFrame, column: str) -> pd.DataFrame:
        return frame.pivot_table(index="trade_date", columns="ts_code", values=column, aggfunc="last").sort_index()

    returns = pivot(daily, "pct_chg") / 100
    amount = pivot(daily, "amount").reindex(returns.index)
    st["flag"] = 1.0
    return {
        "returns": returns,
        # 日均成交额：停牌日视为 0，窗口一年；成交额单位千元（仅用于排序）
        "avg_amount": amount.fillna(0.0).rolling(252, min_periods=20).mean(),
        "total_mv": pivot(basic, "total_mv").reindex(returns.index) * 1e4,  # 万元 → 元
        "pb": pivot(basic, "pb").reindex(returns.index),
        "is_st": pivot(st, "flag").reindex(index=returns.index).notna(),
    }


def load_financials() -> tuple[pd.DataFrame, pd.DataFrame]:
    tables = {}
    for table in ("income", "cashflow", "balancesheet"):
        files = sorted((DATA_DIR / "financial" / table).glob("*.parquet"))
        tables[table] = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    return build_fundamentals(tables["income"], tables["cashflow"], tables["balancesheet"])


def industry_asof(members: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    """中信一级行业 point-in-time：in_date <= date < out_date；历史缺失时回退到最新分类。"""
    m = members.copy()
    m["in_date"] = pd.to_datetime(m["in_date"], errors="coerce").fillna(pd.Timestamp("1990-01-01"))
    m["out_date"] = pd.to_datetime(m["out_date"], errors="coerce").fillna(pd.Timestamp("2099-12-31"))
    active = m[(m["in_date"] <= date) & (m["out_date"] > date)].sort_values("in_date").drop_duplicates("ts_code", keep="last")
    latest = m.sort_values("in_date").drop_duplicates("ts_code", keep="last")
    return active.set_index("ts_code")["l1_name"].combine_first(latest.set_index("ts_code")["l1_name"])


def market_snapshot(panels: dict[str, pd.DataFrame], basic: pd.DataFrame, members: pd.DataFrame,
                    date: pd.Timestamp) -> pd.DataFrame:
    codes = panels["total_mv"].columns
    frame = pd.DataFrame({
        "total_mv": panels["total_mv"].loc[date],
        "pb": panels["pb"].loc[date],
        "avg_amount": panels["avg_amount"].loc[date].reindex(codes),
        "is_st": panels["is_st"].loc[date].reindex(codes, fill_value=False).astype(bool),
    })
    frame = frame[frame["total_mv"].notna()]
    frame["list_date"] = basic.reindex(frame.index)["list_date"]
    frame["industry"] = industry_asof(members, date).reindex(frame.index)
    return frame


def load_index(code: str) -> pd.Series:
    frame = pd.read_parquet(DATA_DIR / "reference" / f"index_{code}.parquet")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")["close"].sort_index()


def index_members(code: str) -> pd.DataFrame:
    """中证自由现金流官方成分（Tushare 仅 2024-12 起），缓存到本地。"""
    path = DATA_DIR / "reference" / f"index_weight_{code}.parquet"
    if not path.exists():
        from src.utils.datahub_client import DataHubClient

        client = DataHubClient(token=os.environ.get("TUSHARE_TOKEN"))
        client.query("index_weight", index_code=code, start_date="20130101", end_date="20261231").to_parquet(path)
    frame = pd.read_parquet(path)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="增强型自由现金流策略复现")
    parser.add_argument("--data-start", default="2012-10-01")
    parser.add_argument("--start", default="2014-01-01", help="绩效统计起点")
    parser.add_argument("--end", default="2026-10-30")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    params = FreeCashFlowParams()

    panels = load_panels(args.data_start)
    fundamentals, annual = load_financials()
    basic = pd.read_parquet(DATA_DIR / "reference" / "stock_basic.parquet").drop_duplicates("ts_code").set_index("ts_code")
    basic["list_date"] = pd.to_datetime(basic["list_date"], errors="coerce")
    members = pd.read_parquet(DATA_DIR / "reference" / "citic_member.parquet")

    trading_days = panels["returns"].index
    dates = [d for d in rebalance_dates(trading_days, "2012-12-01", args.end) if d >= pd.Timestamp("2012-12-01")]
    targets: dict[str, dict[pd.Timestamp, pd.Series]] = {k: {} for k in ("复现指数", "增强-FCF加权", "增强-等权")}
    group_targets: dict[str, dict[pd.Timestamp, pd.Series]] = {}
    holdings_log, pool_sizes = [], {}
    for day in dates:
        # 用上月末数据定样，第二个周五收盘按目标权重调仓（下一交易日起计收益）。
        cutoff = selection_cutoff(trading_days, day)
        pool = candidate_pool(cutoff, market_snapshot(panels, basic, members, cutoff), fundamentals, annual, params)
        pool_sizes[day] = len(pool)
        targets["复现指数"][day] = select(pool, "fcf_yield", size=params.size, weighting="fcf", cap=params.weight_cap)
        enhanced = select(pool, "composite", size=params.size, weighting="fcf", cap=params.weight_cap)
        targets["增强-FCF加权"][day] = enhanced
        targets["增强-等权"][day] = select(pool, "composite", size=params.size, weighting="equal", cap=1.0)
        holdings_log.append(pd.DataFrame({
            "date": day, "symbol": enhanced.index, "weight": enhanced.values,
            "industry": pool.loc[enhanced.index, "industry"].values,
        }))
        # 单因子与复合因子 5 组等数量分组（组内等权）；复合因子另做“首组固定 100、剩余四等分”
        for factor in ("fcf_yield", *FACTORS, "composite"):
            for g, idx in enumerate(quantile_groups(pool, factor), start=1):
                group_targets.setdefault(f"{factor}|G{g}", {})[day] = pd.Series(1 / len(idx), index=idx) if len(idx) else pd.Series(dtype=float)
        for g, idx in enumerate(quantile_groups(pool, "composite", first_size=params.size), start=1):
            group_targets.setdefault(f"composite_fixed100|G{g}", {})[day] = pd.Series(1 / len(idx), index=idx) if len(idx) else pd.Series(dtype=float)

    returns = panels["returns"]
    period = slice(args.start, args.end)
    strat = {name: backtest_weights(returns, t, params.commission) for name, t in targets.items()}
    daily = pd.DataFrame({name: r["return"] for name, r in strat.items()}).loc[period]
    bench = pd.DataFrame({name: load_index(code) for name, code in BENCHMARKS.items()}).reindex(daily.index).pct_change(fill_method=None)
    bench.iloc[0] = np.nan
    daily = daily.join(bench)
    daily = daily.loc[daily.index[1]:]  # 首日为基准对齐
    metrics = pd.DataFrame({name: performance(daily[name].dropna()) for name in daily}).T
    metrics["平均单边换手/季"] = pd.Series({name: r["turnover"].loc[period][r["turnover"].loc[period] > 0].mean() / 2 for name, r in strat.items()})
    excess = {
        f"增强-FCF加权 vs {name}": (1 + daily["增强-FCF加权"]).prod() ** (252 / len(daily)) - (1 + daily[name].fillna(0)).prod() ** (252 / len(daily))
        for name in BENCHMARKS
    }
    te = (daily["复现指数"] - daily["中证现金流全收益"]).std() * np.sqrt(252)

    yearly = (1 + daily).groupby(daily.index.year).prod() - 1
    group_rows = {}
    for key, t in group_targets.items():
        factor, g = key.split("|")
        group_rows.setdefault(factor, {})[g] = performance(backtest_weights(returns, t, params.commission)["return"].loc["2013-01-01":args.end])["年化收益"]
    groups = pd.DataFrame(group_rows).T

    # 与官方成分重合度（2024-12 起）
    official = index_members("932365.CSI")
    overlap = {}
    for day, w in targets["复现指数"].items():
        snap = official[(official["trade_date"] > day) & (official["trade_date"] <= day + pd.Timedelta(days=40))]
        if snap.empty:
            continue
        first = snap[snap["trade_date"] == snap["trade_date"].min()]
        overlap[day.date()] = len(set(first["con_code"]) & set(w.index)) / len(first)

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(out / "performance_metrics.csv")
    yearly.to_csv(out / "yearly_returns.csv")
    groups.to_csv(out / "group_annual_returns.csv")
    (1 + daily.fillna(0)).cumprod().to_csv(out / "cumulative_returns.csv")
    pd.concat(holdings_log).to_csv(out / "enhanced_holdings.csv", index=False)
    pd.Series(pool_sizes, name="pool_size").to_csv(out / "pool_size.csv")
    pd.Series(overlap, name="overlap").to_csv(out / "official_overlap.csv")
    _plot(daily, out)

    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.width", 200)
    print(metrics)
    print("\n超额年化:", {k: round(v, 4) for k, v in excess.items()})
    print(f"复现指数 vs 中证现金流全收益 跟踪误差: {te:.4f}")
    print("与官方成分重合度:", {str(k): round(v, 2) for k, v in overlap.items()})
    print("\n分组年化（2013 起，组内等权）:\n", groups)
    print("\n年度收益:\n", yearly[["复现指数", "增强-FCF加权", "增强-等权", "中证现金流全收益", "中证红利全收益", "沪深300全收益"]])
    print("\n候选池规模:", {str(k.date()): v for k, v in list(pool_sizes.items())[::8]})


def _plot(daily: pd.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Sans CJK JP", "Sarasa Gothic SC", "WenQuanYi Micro Hei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    cols = ["增强-FCF加权", "复现指数", "中证现金流全收益", "中证红利全收益", "沪深300全收益"]
    nav = (1 + daily[cols].fillna(0)).cumprod()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for col in cols:
        ax1.plot(nav.index, nav[col], label=col, linewidth=2.0 if col == "增强-FCF加权" else 1.2)
    ax1.set_yscale("log")
    ax1.set_title("增强型自由现金流策略 vs 基准（对数坐标）")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)
    main = nav["增强-FCF加权"]
    ax2.fill_between(main.index, main / main.cummax() - 1, 0, color="tab:red", alpha=0.4)
    ax2.set_title("增强策略回撤")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "nav.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
