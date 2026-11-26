"""逐股查询中信行业历史成员，按证券及在编状态分片；所有请求通过 DataHub。

    python -m scripts.fetch_citic_industry_by_stock --workers 2

默认请求 stock_basic 中全部合法 A 股证券，不覆盖按行业查询的缓存。
失败分片不会写入，可重跑补齐；只有全部成功才合并输出。
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.utils.datahub_client import DataHubClient
from src.datahub.duckdb_frames import frame_exists, read_frame, write_frame

REF = Path('data/free_cash_flow/reference')
SOURCE = REF / 'stock_basic.duckdb'
BATCH_DIR = REF / 'citic_stock_batches'
OUTPUT = REF / 'citic_member_by_stock.duckdb'
MANIFEST = REF / 'citic_member_by_stock_manifest.json'
PAGE_SIZE = 3000


def stock_codes(basic: pd.DataFrame) -> list[str]:
    return sorted({str(s) for s in basic['ts_code'].dropna()
                   if re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(s))})


def fetch_stock(client, symbol: str, status: str) -> pd.DataFrame:
    pages = []
    offset = 0
    while True:
        page = client.query('ci_index_member', ts_code=symbol, is_new=status, offset=offset, limit=PAGE_SIZE)
        if not page.empty and ('ts_code' not in page or not page['ts_code'].eq(symbol).all()):
            raise ValueError(f'{symbol}/{status} 查询返回其他证券')
        if pages and len(page) and page.reset_index(drop=True).equals(pages[-1].reset_index(drop=True)):
            raise RuntimeError(f'{symbol}/{status} 分页响应重复')
        pages.append(page)
        offset += len(page)
        if len(page) < PAGE_SIZE:
            return pd.concat(pages, ignore_index=True)


def fetch_all(codes: list[str], client_factory=DataHubClient, batch_dir: Path = BATCH_DIR,
              workers: int = 2, retries: int = 3) -> tuple[pd.DataFrame, list[dict]]:
    if workers < 1 or retries < 1:
        raise ValueError('workers 和 retries 必须为正')
    batch_dir.mkdir(parents=True, exist_ok=True)
    local = threading.local()
    clients = []
    lock = threading.Lock()

    def get_client():
        if not hasattr(local, 'client'):
            local.client = client_factory()
            with lock:
                clients.append(local.client)
        return local.client

    def one(job):
        code, status = job
        path = batch_dir / f'{code}_{status}.duckdb'
        if frame_exists(path):
            frame = read_frame(path)
        else:
            for attempt in range(retries):
                try:
                    frame = fetch_stock(get_client(), code, status)
                    write_frame(path, frame)
                    break
                except Exception:
                    if attempt + 1 == retries:
                        raise
                    time.sleep(2 * (attempt + 1))
        if not frame.empty and ('ts_code' not in frame or not frame.ts_code.eq(code).all()):
            raise ValueError(f'{path} 含其他证券')
        return frame, {'ts_code': code, 'is_new': status, 'rows': len(frame), 'path': str(path)}

    jobs = [(code, flag) for code in codes for flag in ('Y', 'N')]
    frames, records, errors = [], [], []
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(one, job): job for job in jobs}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    frame, record = future.result()
                    frames.append(frame)
                    records.append(record)
                except Exception as exc:
                    errors.append((futures[future], str(exc)))
                if i % 200 == 0 or i == len(jobs):
                    print(f'{i}/{len(jobs)} 批完成，失败 {len(errors)}', flush=True)
    finally:
        for client in clients:
            client.close()
    if errors:
        raise RuntimeError(f'{len(errors)} 个分片失败，未合并；重跑可补齐。示例: {errors[:5]}')
    return pd.concat(frames, ignore_index=True).drop_duplicates(ignore_index=True), records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--retries', type=int, default=3)
    args = parser.parse_args()
    basic = read_frame(SOURCE)
    codes = stock_codes(basic)
    if not codes:
        raise ValueError('股票代码池为空')
    data, records = fetch_all(codes, workers=args.workers, retries=args.retries)
    write_frame(OUTPUT, data)
    manifest = {'provider': 'tushare', 'data_kind': 'index_member', 'api': 'ci_index_member',
                'stock_universe': str(SOURCE), 'stock_count': len(codes), 'rows': len(data),
                'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'batches': records}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'完成: {len(codes)} 只股票，{len(data)} 条记录 -> {OUTPUT}', flush=True)


if __name__ == '__main__':
    main()
