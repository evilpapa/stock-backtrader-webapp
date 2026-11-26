"""合并新增指数快照，准备独立的基准版本和下一交易日执行行情。"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

if str(Path(__file__).resolve().parent) in sys.path:
    sys.path.remove(str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import create_service, DataRequest
from src.datahub.duckdb_frames import frame_exists, promote_frame, read_frame, write_frame
from src.datahub.models import DataKind
from src.datahub.storage import SQLiteRepository
from scripts.fetch_csi500_history import changes_between_snapshots
from src.strategy.intraday_artifacts import sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("data/intraday_factors/refresh_20261030"))
    p.add_argument("--end", default="2026-10-30")
    p.add_argument("--base-root", type=Path, help="已验证的上次刷新目录")
    p.add_argument("--valuation-end", help="参考日线终点，默认取因子终点的下一交易日")
    args = p.parse_args()
    if args.base_root and args.base_root.resolve() == args.root.resolve():
        p.error("--base-root 与 --root 必须是不同的目录")
    old_path = promote_frame((args.base_root or Path("data/intraday_factors")) / "csi500/snapshots.duckdb")
    new_path = promote_frame(args.root / "csi500_new/snapshots.duckdb")
    snapshots = pd.concat([read_frame(old_path), read_frame(new_path)], ignore_index=True).drop_duplicates()
    if snapshots.duplicated(["trade_date", "con_code"]).any():
        raise ValueError("成分快照重复")
    snapshots = snapshots.sort_values(["trade_date", "con_code"]).reset_index(drop=True)
    counts = snapshots.groupby("trade_date").con_code.nunique()
    if not counts.eq(500).all():
        raise ValueError("并非每个快照500只")
    dates = pd.to_datetime(counts.index.astype(str), format="%Y%m%d")
    reference = args.root / "reference_data"
    (reference / "reference").mkdir(parents=True, exist_ok=True)
    base_reference = args.base_root / "reference_data" if args.base_root else Path("data/micro_cap_timing_plus")
    raw = reference / "raw"
    repo = SQLiteRepository(args.root / "reference_downloads.sqlite")
    service = create_service(repository=repo)

    def get(kind, request):
        cached = repo.query(kind, request, source="tushare")
        if cached is not None:
            return cached.data
        frame = service.query(kind, request, persist=True)
        if frame.attrs.get("source") != "tushare":
            raise ValueError(f"参考数据来源不是 Tushare: {kind}")
        return frame

    try:
        end = pd.Timestamp(args.end)
        cal = get(DataKind.TRADE_CALENDAR, DataRequest(
            start="20210104", end=(end + pd.Timedelta(days=14)).strftime("%Y%m%d"),
            exchange="SSE", options={"is_open": "1"}))
        days = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_open.astype(str).eq("1"), "trade_date"])).sort_values()
        if days.has_duplicates or end not in days or not (days > end).any():
            raise ValueError("截止日非交易日")
        calendar = args.root / "calendar.duckdb"
        write_frame(calendar, pd.DataFrame({"date": days}))
        next_day = days[days > end][0]
        valuation_end = pd.Timestamp(args.valuation_end) if args.valuation_end else next_day
        if valuation_end not in days or valuation_end < end or (dates > end).any():
            raise ValueError("估值截止日或快照日期超出允许范围")
        month = end.to_period("M")
        missing = set(pd.period_range(dates.min(), end, freq="M")) - set(dates.to_period("M"))
        pending = missing & {month} if (days[days > end].to_period("M") == month).any() else set()
        if missing - pending:
            raise ValueError(f"缺少月份 {sorted(missing)}")
        dst = args.root / "csi500"
        dst.mkdir(parents=True, exist_ok=True)
        snapshot_path = dst / "snapshots.duckdb"
        if not frame_exists(snapshot_path) or not snapshots.equals(read_frame(snapshot_path)):
            write_frame(snapshot_path, snapshots)
        write_frame(dst / "observed_changes.duckdb", changes_between_snapshots(snapshots))
        (dst / "manifest.json").write_text(json.dumps(dict(
            source="tushare", interface="index_weight", snapshot_lag_days=31,
            start=str(dates.min().date()), end=str(dates.max().date()), snapshot_count=len(counts),
            unique_stocks=int(snapshots.con_code.nunique()), pending_months=sorted(map(str, pending)),
            parent_inputs={str(old_path): sha(old_path), str(new_path): sha(new_path)},
            snapshot_sha256=sha(snapshot_path),
            limitations="月末权重滞后31自然日近似，非精确生效和公告日期。"
        ), ensure_ascii=False, indent=2))
        basic = reference / "reference/stock_basic.duckdb"
        base_basic = promote_frame(base_reference / "reference/stock_basic.duckdb")
        basics = read_frame(base_basic)
        missing_codes = sorted(set(snapshots.con_code) - set(basics.ts_code))
        for symbol in missing_codes:
            updated = get(DataKind.STOCK_BASIC, DataRequest(symbols=(symbol,))).copy()
            if updated.symbol.tolist() != [symbol]:
                raise ValueError(f"基础信息缺失或代码不一致: {symbol}")
            for column in ("list_date", "delist_date"):
                updated[column] = pd.to_datetime(updated[column], errors="coerce").dt.strftime("%Y%m%d")
            if updated.list_date.isna().any():
                raise ValueError(f"缺少上市日期: {symbol}")
            basic_row = updated.rename(columns={"symbol": "ts_code"}).reindex(columns=basics.columns)
            basics = pd.concat([basics, basic_row], ignore_index=True)
        if not set(snapshots.con_code).issubset(set(basics.ts_code)) or basics.ts_code.duplicated().any():
            raise ValueError("基础信息不全或存在重复证券")
        if frame_exists(basic):
            basic = promote_frame(basic)
        elif missing_codes or base_basic.suffix != ".duckdb":
            write_frame(basic, basics)
        else:
            basic.hardlink_to(base_basic.resolve())
        days = days[days <= valuation_end]
        for day in days:
            for kind, folder in [(DataKind.DAILY_BULK, "daily"), (DataKind.ST, "stock_st")]:
                # ST只用于信号资格，无需执行日ST。
                if kind == DataKind.ST and day > end:
                    continue
                path = raw / folder / f"{day:%Y%m%d}.duckdb"
                if frame_exists(path):
                    promote_frame(path)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                base_path = base_reference / "raw" / folder / path.name
                if frame_exists(base_path):
                    base_path = promote_frame(base_path)
                    if base_path.suffix == ".duckdb":
                        path.hardlink_to(base_path)
                    else:
                        write_frame(path, read_frame(base_path))
                    continue
                frame = get(kind, DataRequest(start=day, end=day, frequency="1d", adjust="none",
                                               options={"trade_date": f"{day:%Y%m%d}"}))
                if frame.empty or not frame.trade_date.astype(str).eq(f"{day:%Y%m%d}").all():
                    raise ValueError(f"缺失日线/ST {kind} {day}")
                write_frame(path, frame)
                print("补充", folder, day.date(), len(frame), flush=True)
        bench_old = base_reference / "reference/index_000905.SH.duckdb"
        benchmark = read_frame(bench_old)
        start = pd.Timestamp(str(benchmark.trade_date.max())) + pd.Timedelta(days=1)
        if start <= valuation_end:
            extra = get(DataKind.INDEX_DAILY, DataRequest(symbols=("000905.SH",), start=start, end=valuation_end,
                                                         frequency="1d", adjust="none"))
            benchmark = pd.concat([benchmark, extra], ignore_index=True)
        if benchmark.trade_date.astype(str).duplicated().any():
            raise ValueError("基准日期重复")
        benchmark = benchmark[benchmark.trade_date.astype(str).le(valuation_end.strftime("%Y%m%d"))]
        benchmark = benchmark.sort_values("trade_date").reset_index(drop=True)
        if not set(days.strftime("%Y%m%d")).issubset(set(benchmark.trade_date.astype(str))):
            raise ValueError("基准未覆盖所有回测日")
        bench_path = reference / "reference/index_000905.SH.duckdb"
        write_frame(bench_path, benchmark)
        (args.root / "input_manifest.json").write_text(json.dumps(dict(
            factor_end=args.end, valuation_end=str(valuation_end.date()), next_session=str(next_day.date()),
            calendar_dates=len(cal),
            benchmark_sha256=sha(bench_path), basic_sha256=sha(basic), snapshots_sha256=sha(snapshot_path),
            calendar_sha256=sha(calendar),
            retrieval_date=str(datetime.now(ZoneInfo("Asia/Shanghai")).date()),
        ), ensure_ascii=False, indent=2))
        print("因子截止", args.end, "下一开市日", next_day.date(), "股票集合", snapshots.con_code.nunique(), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
