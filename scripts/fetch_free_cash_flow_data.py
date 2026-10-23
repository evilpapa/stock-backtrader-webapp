"""拉取自由现金流策略复现所需的 Tushare 数据（全部经 DataHub，可断点续传）。

- 日频 daily / daily_basic / stock_st：与微盘择时共用 ``data/micro_cap_timing_plus/raw``，只补缺失交易日；
- 财务三表：按报告期全市场拉取，保存到 ``data/free_cash_flow/financial/{table}/{period}.parquet``；
- 参考数据：中信行业成分（含历史）、股票基础信息、对照指数日线。

    uv run python -m scripts.fetch_free_cash_flow_data --start 2012-10-01 --end 2026-10-30
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from scripts.fetch_micro_cap_data import RAW_DIR as DAILY_RAW_DIR
from scripts.fetch_micro_cap_data import fetch_one
from src.utils.datahub_client import DataHubClient

DATA_DIR = Path("data") / "free_cash_flow"
DAILY_APIS = ["daily", "daily_basic", "stock_st"]
KEYS = ["ts_code", "ann_date", "f_ann_date", "end_date", "report_type", "update_flag"]
FIN_FIELDS = {
    "income": KEYS + ["operate_profit", "total_profit", "income_tax", "fin_exp", "int_exp", "ebit", "ebitda", "n_income_attr_p"],
    "cashflow": KEYS + [
        "n_cashflow_act", "c_pay_acq_const_fiolta", "n_recp_disp_fiolta", "depr_fa_coga_dpba",
        "amort_intang_assets", "lt_amort_deferred_exp", "use_right_asset_dep", "free_cashflow",
    ],
    "balancesheet": KEYS + [
        "total_assets", "total_liab", "money_cap", "trad_asset", "total_cur_assets", "inventories", "accounts_receiv",
        "total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int", "st_borr", "lt_borr", "bond_payable",
        "lease_liab", "non_cur_liab_due_1y",
    ],
}
INDEX_CODES = [
    "932365.CSI", "932365CNY010.CSI", "932366.CSI", "932367.CSI", "H00922.CSI",
    "H00016.CSI", "H00300.CSI", "H00905.CSI", "399606.SZ", "000985.CSI",
]


def _retry(func, *args, **kwargs):
    for attempt in range(6):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 限流/网络抖动，退避重试
            last = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"多次重试失败: {last}")


def fetch_financials(client: DataHubClient, first_period: str, last_period: str) -> None:
    periods = pd.date_range(first_period, last_period, freq="QE").strftime("%Y%m%d")
    for table, fields in FIN_FIELDS.items():
        out = DATA_DIR / "financial" / table
        out.mkdir(parents=True, exist_ok=True)
        for period in periods:
            path = out / f"{period}.parquet"
            if path.exists():
                continue
            frame = _retry(client.financial_period, table, period, fields=fields)
            frame.to_parquet(path)
            print(table, period, len(frame), flush=True)


def _paged(client: DataHubClient, api: str, **kwargs) -> pd.DataFrame:
    pages, offset = [], 0
    while True:
        page = _retry(client.query, api, offset=offset, limit=3000, **kwargs)
        pages.append(page)
        offset += len(page)
        if len(page) < 3000:
            return pd.concat(pages, ignore_index=True)


def fetch_reference(client: DataHubClient, start: str, end: str) -> None:
    ref = DATA_DIR / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    industry = pd.concat([_paged(client, "ci_index_member", is_new=flag) for flag in "YN"], ignore_index=True)
    industry.to_parquet(ref / "citic_member.parquet")
    # stock_basic 复用微盘择时已缓存的版本（当前 Tushare 退市列表含 T600018 这类无法映射的代码）。
    basic_path = DAILY_RAW_DIR.parent / "reference" / "stock_basic.parquet"
    if not basic_path.exists():
        basics = [client.query("stock_basic", list_status=s, fields="ts_code,name,list_date,delist_date,market,exchange") for s in "L"]
        basic_path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(basics).to_parquet(basic_path)
    pd.read_parquet(basic_path).to_parquet(ref / "stock_basic.parquet")
    for code in INDEX_CODES:
        frame = _retry(client.query, "index_daily", ts_code=code, start_date=start.replace("-", ""), end_date=end.replace("-", ""))
        frame.to_parquet(ref / f"index_{code}.parquet")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2012-10-01")
    parser.add_argument("--end", default="2026-10-30")
    parser.add_argument("--first-period", default="2006-12-31", help="最早报告期（需覆盖回测起点前 5 个年报）")
    parser.add_argument("--last-period", default="2026-09-30")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    client = DataHubClient(token=os.environ["TUSHARE_TOKEN"])
    fetch_reference(client, args.start, args.end)
    fetch_financials(client, args.first_period, args.last_period)
    cal = client.query("trade_cal", exchange="SSE", start_date=args.start.replace("-", ""),
                       end_date=args.end.replace("-", ""), is_open="1")
    column = "cal_date" if "cal_date" in cal else "trade_date"
    dates = sorted(pd.to_datetime(cal[column]).dt.strftime("%Y%m%d").unique())
    jobs = [(api, d) for d in dates for api in DAILY_APIS if not (DAILY_RAW_DIR / api / f"{d}.parquet").exists()]
    print("daily jobs", len(jobs), flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for i, _ in enumerate(pool.map(lambda j: fetch_one(client, *j), jobs)):
            if i % 300 == 0:
                print(f"{i}/{len(jobs)}", flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
