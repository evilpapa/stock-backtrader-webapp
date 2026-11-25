"""在独立目录复用验证后的旧因子，并以相同公式补齐近期分钟与竞价因子。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

script_dir = str(Path(__file__).resolve().parent)
if script_dir in sys.path:
    sys.path.remove(script_dir)  # scripts/duckdb 不能遮蔽依赖包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.datahub import DataRequest
from src.datahub.models import DataKind
from src.datahub.local_minute_repository import LocalMinuteRepository
from src.datahub.auction_tick_repository import DEFAULT_AUCTION_DIR, AuctionTickRepository
from src.datahub.service import MarketDataService
from src.datahub.router import DataRouter
from src.strategy.intraday_factors_fast import daily_factors_fast
from src.strategy.intraday_factors import daily_factors
from src.strategy.auction_factors import auction_daily_factors_vectorized
from src.strategy.intraday_artifacts import sha, load_factors
from scripts.build_local_minute_factors import normalize_bars


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("data/intraday_factors/refresh_20261030"))
    p.add_argument("--end", default="2026-10-30")
    p.add_argument("--base-root", type=Path, help="上次完整刷新，复用已验证且股票池未受影响的日因子")
    p.add_argument("--auction-dir", type=Path, default=DEFAULT_AUCTION_DIR)
    args = p.parse_args()
    snapshots = args.root / "csi500/snapshots.parquet"
    snap = pd.read_parquet(snapshots)
    symbols = sorted(snap.con_code.unique())
    old_snap = args.base_root / "csi500/snapshots.parquet" if args.base_root else snapshots
    if args.base_root and args.base_root.resolve() == args.root.resolve():
        p.error("--base-root 与 --root 必须是不同的目录")
    old_symbols = sorted(pd.read_parquet(old_snap).con_code.unique())
    base_manifest = json.loads((args.base_root / "factor_manifest.json").read_text()) if args.base_root else {}
    base_end = pd.Timestamp(base_manifest["end"]) if base_manifest else None
    extra = set(symbols) - set(old_symbols)
    first_extra = pd.to_datetime(snap.loc[snap.con_code.isin(extra), "trade_date"].astype(str),
                                 format="%Y%m%d").min() + pd.Timedelta(days=31)
    calendar = pd.DatetimeIndex(pd.read_parquet(args.root / "calendar.parquet").date)
    end = pd.Timestamp(args.end)
    if end not in calendar or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("交易日历无效或不覆盖截止日")
    days = calendar[calendar <= end]
    common = dict(schema_version=2, snapshot_sha256=sha(snapshots),
                  symbols_sha256=hashlib.sha256("\n".join(symbols).encode()).hexdigest(),
                  refresh_builder_sha256=sha(__file__), union_size=len(symbols))
    minute_repo = LocalMinuteRepository("data/tick_1m_parquet")
    minute_service = MarketDataService(DataRouter({}), repository=minute_repo)
    auction_repo = AuctionTickRepository(args.auction_dir)
    auction_service = MarketDataService(DataRouter({}), repository=auction_repo)
    summaries = []
    parity_checked = False
    try:
        for i, day in enumerate(days, 1):
            key = f"{day:%Y%m%d}"
            counts = {}
            for auction in [False, True]:
                folder = "auction/daily" if auction else "minute"
                output = args.root / folder / f"{key}.parquet"
                output.parent.mkdir(parents=True, exist_ok=True)
                impl = sha("src/strategy/auction_factors.py" if auction else "src/strategy/intraday_factors.py")
                if output.exists() and output.with_suffix(".json").exists():
                    result, metadata = load_factors(output, day, symbols, snapshots, auction=auction)
                    if auction and metadata["mode"] == "computed":
                        source = auction_repo.csv_path(key)
                        if metadata.get("source_csv_sha256") != sha(source):
                            raise ValueError(f"竞价 CSV 来源或内容已变更，请使用新的输出目录: {source}")
                    counts[folder] = len(result)
                    continue
                meta = dict(common, date=key, implementation_sha256=impl)
                # 为新增证券的五日滚动窗口留出余量。
                if base_end is not None and day <= base_end and (not extra or day + pd.Timedelta(days=14) < first_extra):
                    parent = args.base_root / folder / output.name
                    result, old = load_factors(parent, day, old_symbols, old_snap, auction=auction)
                    if old["refresh_builder_sha256"] != base_manifest["refresh_builder_sha256"]:
                        raise ValueError(f"父缓存构建版本与其清单不一致: {parent}")
                    if auction:
                        meta.update(auction_data_version=old["auction_data_version"])
                    else:
                        meta.update(input_sha256=old["input_sha256"], source_path=old["source_path"],
                                    repository_sha256=sha("src/datahub/local_minute_repository.py"))
                        if "fast_implementation_sha256" in old:
                            meta["fast_implementation_sha256"] = old["fast_implementation_sha256"]
                    meta.update(mode="reused", parent_file=str(parent), parent_sha256=sha(parent),
                                parent_metadata={k: v for k, v in old.items() if k != "parent_metadata"},
                                computed_symbols=old.get("computed_symbols", old_symbols))
                    os.link(parent, output)
                else:
                    request = DataRequest(symbols=tuple(symbols), start=day, end=day,
                                          frequency="tick" if auction else "1m", adjust="none")
                    service = auction_service if auction else minute_service
                    raw = service.get_cached(DataKind.TICK if auction else DataKind.MINUTE, request)
                    if raw is None or raw.empty:
                        raise ValueError(f"原始数据缺失 {day} {folder}")
                    if auction:
                        f, quality = auction_daily_factors_vectorized(raw)
                        result = f.merge(quality[["symbol", "date", "auction_open", "auction_pre_close",
                                                  "stage1_valid", "stage2_valid"]], on=["symbol", "date"], validate="one_to_one")
                        meta.update(auction_data_version=raw.attrs["data_version"],
                                    source_csv_sha256=raw.attrs["source_csv_sha256"],
                                    source_path=raw.attrs["source_path"], duplicates_removed=raw.attrs["duplicates_removed"])
                    else:
                        normalized = normalize_bars(raw)
                        traded = normalized.groupby("symbol").volume.sum().loc[lambda v: v > 0].index
                        normalized = normalized[normalized.symbol.isin(traded)]
                        result = daily_factors_fast(normalized)
                        if not parity_checked:
                            subset = normalized[normalized.symbol.isin(normalized.symbol.unique()[:10])]
                            reference = daily_factors(subset)
                            actual = daily_factors_fast(subset)
                            pd.testing.assert_frame_equal(actual[reference.columns], reference, rtol=1e-10, atol=1e-12)
                            parity_checked = True
                            print("真实数据10只股票39因子与原实现逐项一致", key, flush=True)
                        meta.update(input_sha256=raw.attrs["data_version"], source_path=raw.attrs["path"],
                                    repository_sha256=sha("src/datahub/local_minute_repository.py"),
                                    fast_implementation_sha256=sha("src/strategy/intraday_factors_fast.py"))
                    meta.update(mode="computed", computed_symbols=symbols, source=raw.attrs["source"],
                                frequency="tick" if auction else "1m", adjust="none_assumed" if not auction else "none")
                    if result.empty:
                        raise ValueError(f"因子结果为空 {day} {folder}")
                    result.to_parquet(output, index=False)
                meta.update(rows=len(result), output_sha256=sha(output))
                output.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
                counts[folder] = len(result)
            summaries.append(dict(date=key, **counts))
            if i % 25 == 0 or i == len(days):
                print(f"{i}/{len(days)} {key} {counts}", flush=True)
        pd.DataFrame(summaries).to_csv(args.root / "factor_coverage.csv", index=False)
        (args.root / "factor_manifest.json").write_text(json.dumps(dict(
            **common, start=str(days.min().date()), end=str(days.max().date()), dates=len(days),
            old_union=len(old_symbols), added_symbols=sorted(extra),
            first_added_available=str(first_extra.date()) if extra else None,
            base_root=str(args.base_root) if args.base_root else None,
            auction_dir=str(args.auction_dir), window=5, factors=46,
            note="历史日因子复用保留父来源及输出哈希。新增竞价数据直接读取 CSV。"
        ), ensure_ascii=False, indent=2))
    finally:
        minute_service.close()
        auction_service.close()


if __name__ == "__main__":
    main()
