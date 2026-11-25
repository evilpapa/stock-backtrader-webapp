"""对刷新结果做时点、最新信号、成交费用与资金对账，并保存数据清洗审计。"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest
from src.datahub.models import DataKind
from src.datahub.auction_tick_repository import AuctionTickRepository
from src.datahub.service import MarketDataService
from src.datahub.router import DataRouter
from src.strategy.intraday_artifacts import sha, load_factors
from src.strategy.auction_factors import FACTOR_COLUMNS
from src.utils.commission import ChinaStockCommission
from examples.intraday_all_factor_backtest import weekly_execution_dates


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("data/intraday_factors/refresh_20261030"))
    p.add_argument("--results", type=Path, default=Path("examples/intraday_factors/refresh_20261030"))
    args = p.parse_args()
    out = args.results / "backtest"
    metrics = json.loads((out / "metrics.json").read_text())
    manifest = json.loads((args.root / "factor_manifest.json").read_text())
    cutoff = pd.Timestamp(manifest["end"])
    calendar = pd.DatetimeIndex(pd.read_parquet(args.root / "calendar.parquet").date)
    days = calendar[calendar <= cutoff]
    snapshots = args.root / "csi500/snapshots.parquet"
    symbols = sorted(pd.read_parquet(snapshots).con_code.unique())
    versions = []
    duplicates = []
    service = MarketDataService(DataRouter({}), repository=AuctionTickRepository(
        "data/tick_auction_parquet", storage="parquet"))
    try:
        for day in days:
            key = f"{day:%Y%m%d}"
            for auction in [False, True]:
                path = args.root / ("auction/daily" if auction else "minute") / (key + ".parquet")
                frame, meta = load_factors(path, day, symbols, snapshots, auction=auction)
                versions.append(dict(date=key, kind="auction" if auction else "minute",
                                     output_sha256=sha(path), rows=len(frame), mode=meta["mode"]))
                if auction:
                    source = meta
                    if meta["mode"] == "reused" and manifest.get("base_root"):
                        source = meta["parent_metadata"]
                        if source.get("source") != "auction_tick_csv":
                            continue  # 已校验历史因子输出，保留父缓存的原始来源。
                    if source.get("source") == "auction_tick_csv":
                        if sha(source["source_path"]) != source["source_csv_sha256"]:
                            raise ValueError(f"竞价 CSV 哈希不一致: {key}")
                        if source["duplicates_removed"]:
                            duplicates.append(dict(date=key, duplicates_removed=source["duplicates_removed"],
                                                   policy="dedup_exact_rows_v1"))
                        continue
                    raw_meta = json.loads((Path("data/tick_auction_parquet") / f"{day:%Y/%m/%Y%m%d}.json").read_text())
                    base = hashlib.sha256(f'{raw_meta["archive_sha256"]}:{key}:{raw_meta["version"]}'.encode()).hexdigest()[:20]
                    if base != meta["auction_data_version"]:
                        raw = service.get_cached(DataKind.TICK, DataRequest(
                            symbols=tuple(symbols), start=day, end=day, frequency="tick", adjust="none"))
                        if raw is None or raw.attrs["data_version"] != meta["auction_data_version"]:
                            raise ValueError("清洗版本无法复核")
                        duplicates.append(dict(date=key, duplicates_removed=raw.attrs["duplicates_removed"],
                                               retained_rows=len(raw), policy=raw.attrs["duplicate_policy"]))
    finally:
        service.close()
    pd.DataFrame(versions).to_csv(args.results / "factor_versions.csv", index=False)
    pd.DataFrame(duplicates).to_csv(args.results / "duplicate_cleanup.csv", index=False)
    cov = pd.read_parquet(args.results / "auction_history/coverage.parquet")
    cov["date"] = pd.to_datetime(cov.date)
    if not pd.DatetimeIndex(sorted(cov.date.unique())).equals(days):
        raise ValueError("资格与因子交易日不一致")
    ic = pd.read_csv(args.results / "factor_research/weekly_research.csv", parse_dates=["exit_date"])
    windows = pd.read_csv(out / "training_windows.csv", parse_dates=["signal_date", "first_exit", "last_exit"])
    if not (windows.last_exit.le(windows.signal_date).all() and windows.observations.eq(52).all()
            and ic.exit_date.le(cutoff).all()):
        raise ValueError("IC时点或窗口错误")
    selection = pd.read_csv(out / "latest_selection.csv")
    last_signal = pd.Timestamp(metrics["latest_signal_date"])
    schedule = weekly_execution_dates(calendar, cutoff, pd.Timestamp(metrics["end_date"]))
    if last_signal != max(schedule) or not pd.to_datetime(selection.trade_date).eq(schedule[last_signal]).all():
        raise ValueError("最近信号与完整交易周的执行日期不一致")
    selected_eligible = cov[cov.date.eq(last_signal)].set_index("symbol").eligible
    if not selected_eligible.reindex(selection.symbol).eq(True).all():
        raise ValueError("最新名单有不合格证券")
    last_days = days[days <= last_signal][-5:]
    pieces = []
    for day in last_days:
        key = f"{day:%Y%m%d}"
        minute = pd.read_parquet(args.root / "minute" / (key + ".parquet"))
        auction = pd.read_parquet(args.root / "auction/daily" / (key + ".parquet"))
        pieces.append(minute.merge(auction[["symbol", "date"] + FACTOR_COLUMNS], on=["symbol", "date"],
                                    how="outer", validate="one_to_one"))
    recent = pd.concat(pieces, ignore_index=True)
    recent = recent.replace([np.inf, -np.inf], np.nan)
    factors = [c for c in recent if c not in ("symbol", "date")]
    complete = recent.groupby("symbol")[factors].count().eq(5).all(axis=1)
    smooth = recent.groupby("symbol")[factors].mean().loc[complete]
    smooth = smooth.loc[smooth.index.intersection(selected_eligible[selected_eligible.eq(True)].index)]
    signs = windows[windows.signal_date.eq(last_signal)].set_index("factor").direction
    score = smooth.rank(pct=True, method="average").mul(signs).mean(axis=1).sort_values(ascending=False, kind="stable")
    if selection.symbol.tolist() != score.index[:math.ceil(len(score) * .1)].tolist():
        raise ValueError("最新因子排名无法复算")
    if not np.allclose(selection.score, score.reindex(selection.symbol).to_numpy(), rtol=1e-12, atol=1e-12):
        raise ValueError("最新分数无法复算")
    nav = pd.read_csv(out / "nav.csv", parse_dates=["date"])
    trades = pd.read_csv(out / "trades.csv")
    holdings = pd.read_csv(out / "latest_holdings.csv")
    commission = ChinaStockCommission()
    expected_fees = trades.notional.map(lambda value: commission.getcommission(value, 1.))
    if not np.allclose(expected_fees, trades.fee, rtol=1e-12, atol=1e-8):
        raise ValueError("手续费与项目定义不符")
    if not (np.allclose(nav.equity, nav.cash + nav.market_value) and nav.cash.ge(-1e-6).all()
            and np.isclose(holdings.market_value.sum() + metrics["final_cash"], metrics["final_equity"])
            and np.isclose(holdings.actual_weight.sum() + metrics["cash_weight"], 1)):
        raise ValueError("资金持仓无法对账")
    old = pd.read_csv("examples/intraday_factors/all_factor_backtest/nav.csv", parse_dates=["date"])
    overlap = old[old.date.lt("2026-01-01")].merge(nav, on="date", suffixes=("_old", "_new"))
    before_2026_delta = float((overlap.equity_old - overlap.equity_new).abs().max())
    last_pool = pd.read_csv(args.results / "auction_history/universe_snapshots.csv")
    used_snapshot = last_pool.loc[last_pool.date.eq(str(last_signal.date())), "snapshot_date"].iloc[0]
    summary = dict(
        factor_start=manifest["start"], factor_end=manifest["end"], latest_signal=str(last_signal.date()),
        minute_dates=len(days), auction_dates=len(days), factors=len(factors), symbols_union=len(symbols),
        monthly_snapshot_count=int(pd.read_parquet(snapshots).trade_date.nunique()),
        latest_snapshot=str(pd.read_parquet(snapshots).trade_date.max()), latest_used_snapshot=used_snapshot,
        latest_execution=str(schedule[last_signal].date()), latest_candidate_count=len(score), latest_targets=len(selection),
        latest_priced_targets=int(selection.can_price.sum()), latest_holdings=len(holdings),
        ic_latest_realized_exit=str(ic.exit_date.max().date()),
        latest_training_last_exit=str(windows[windows.signal_date.eq(last_signal)].last_exit.max().date()),
        future_ic_excluded=True, training_observations=52, latest_scores_independently_recomputed=True,
        fee_reconciliation=True, cash_position_reconciliation=True,
        before_2026_overlap_dates=len(overlap), before_2026_max_equity_difference=before_2026_delta,
        duplicate_cleanup=duplicates, auction_repository_sha256=sha("src/datahub/auction_tick_repository.py"),
        metrics_sha256=sha(out / "metrics.json"), coverage_sha256=sha(args.results / "auction_history/coverage.parquet")
    )
    (args.results / "audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
