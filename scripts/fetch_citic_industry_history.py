"""按中信一级行业和当前/历史状态分批获取成员区间（经 DataHub）。

一级行业代码从现有全量成员缓存提取，不保证包含该缓存遗漏的行业。
输出与原缓存分开，不覆盖原始数据；每个行业分片便于断点重试。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.utils.datahub_client import DataHubClient
from src.datahub.duckdb_frames import frame_exists, read_frame, write_frame

REFERENCE = Path('data/free_cash_flow/reference')
SOURCE = REFERENCE / 'citic_member.duckdb'
BATCH_DIR = REFERENCE / 'citic_industry_batches'
OUTPUT = REFERENCE / 'citic_member_by_industry.duckdb'
MANIFEST = REFERENCE / 'citic_member_by_industry_manifest.json'
PAGE_SIZE = 3000


def fetch_batch(client, code: str, status: str) -> pd.DataFrame:
    pages = []
    offset = 0
    while True:
        page = client.query('ci_index_member', l1_code=code, is_new=status, offset=offset, limit=PAGE_SIZE)
        if len(page) and pages and page.reset_index(drop=True).equals(pages[-1].reset_index(drop=True)):
            raise RuntimeError(f'{code}/{status} 分页响应重复，拒绝继续')
        pages.append(page)
        offset += len(page)
        if len(page) < PAGE_SIZE:
            break
    return pd.concat(pages, ignore_index=True)


def fetch_all(client, codes, batch_dir: Path = BATCH_DIR) -> tuple[pd.DataFrame, list[dict]]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    frames, records = [], []
    for code in sorted(codes):
        for status in ('Y', 'N'):
            path = batch_dir / f'{code}_{status}.duckdb'
            if frame_exists(path):
                frame = read_frame(path)
            else:
                frame = fetch_batch(client, code, status)
                write_frame(path, frame)
            if not frame.empty and not frame['l1_code'].eq(code).all():
                raise ValueError(f'{code}/{status} 返回了其他行业数据')
            frames.append(frame)
            records.append({'l1_code': code, 'is_new': status, 'rows': len(frame), 'path': str(path)})
            print(code, status, len(frame), flush=True)
    return pd.concat(frames, ignore_index=True).drop_duplicates(ignore_index=True), records


def main() -> None:
    if not frame_exists(SOURCE):
        raise FileNotFoundError(f'缺少一级行业代码种子: {SOURCE}')
    old = read_frame(SOURCE)
    codes = sorted(old.l1_code.dropna().unique())
    if not codes:
        raise ValueError('行业代码种子为空')
    client = DataHubClient()
    try:
        data, records = fetch_all(client, codes)
    finally:
        client.close()
    write_frame(OUTPUT, data)
    manifest = {'source': 'tushare', 'data_kind': 'index_member', 'provider_api': 'ci_index_member',
                'retrieved_at_utc': datetime.now(timezone.utc).isoformat(), 'code_source': str(SOURCE),
                'code_count': len(codes), 'rows': len(data), 'batches': records,
                'notes': '代码来自原缓存；入选日期含当日，剔除日期不含当日为研究假设。'}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'完成: {len(codes)} 个行业, {len(data)} 条记录 -> {OUTPUT}')


if __name__ == '__main__':
    main()
