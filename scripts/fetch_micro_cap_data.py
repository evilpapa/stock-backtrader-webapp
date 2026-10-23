"""拉取微盘股择时复现所需的 Tushare 全市场日频数据，按 接口/交易日 缓存为 parquet（可断点续传）。

    uv run python scripts/fetch_micro_cap_data.py --start 2015-10-01 --end 2026-10-23
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src.utils.datahub_client import DataHubClient

RAW_DIR = Path("data") / "micro_cap_timing_plus" / "raw"
APIS = ["daily", "daily_basic", "moneyflow", "stock_st"]


def fetch_one(client: DataHubClient, api: str, date: str) -> None:
    path = RAW_DIR / api / f"{date}.parquet"
    if path.exists():
        return
    for attempt in range(6):
        try:
            frame = client.query(api, trade_date=date)
            break
        except Exception:  # noqa: BLE001 - 限流/网络抖动，退避重试
            time.sleep(2 + attempt * 3)
    else:
        print("FAILED", api, date, flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)


INDEX_CODES = ["000300.SH", "000852.SH", "932000.CSI", "399303.SZ", "000985.CSI", "000905.SH"]


def fetch_reference(client: DataHubClient, start: str, end: str) -> None:
    """股票基础信息（上市/退市日期）与对照指数日线。"""
    ref = RAW_DIR.parent / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    basics = [client.query("stock_basic", list_status=s, fields="ts_code,name,list_date,delist_date,market,exchange") for s in "LDP"]
    pd.concat(basics).to_parquet(ref / "stock_basic.parquet")
    for code in INDEX_CODES:
        frame = client.query("index_daily", ts_code=code, start_date=start.replace("-", ""), end_date=end.replace("-", ""))
        frame.to_parquet(ref / f"index_{code}.parquet")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2015-10-01")
    parser.add_argument("--end", default="2026-10-23")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    client = DataHubClient(token=os.environ["TUSHARE_TOKEN"])
    cal = client.query(
        "trade_cal", exchange="SSE", start_date=args.start.replace("-", ""),
        end_date=args.end.replace("-", ""), is_open="1",
    )
    dates = sorted(cal.cal_date)
    (RAW_DIR.parent / "trade_cal.csv").write_text("\n".join(dates))
    fetch_reference(client, args.start, args.end)
    jobs = [(api, d) for d in dates for api in APIS]
    with ThreadPoolExecutor(args.workers) as pool:
        for i, _ in enumerate(pool.map(lambda j: fetch_one(client, *j), jobs)):
            if i % 400 == 0:
                print(f"{i}/{len(jobs)}", flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
