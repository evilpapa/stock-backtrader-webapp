"""从本地分钟 Parquet 按交易日构建因子，保存输入来源和可恢复结果。"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import pandas as pd
if str(Path(__file__).resolve().parent) in sys.path:
    sys.path.remove(str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub.local_minute_repository import LocalMinuteRepository
from src.datahub.duckdb_frames import frame_exists, frame_paths, matches_frame_hash, promote_frame, read_frame, write_frame
from src.datahub.models import DataKind, DataRequest
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.strategy.intraday_factors import daily_factors
from src.strategy.intraday_artifacts import LEGACY_MINUTE_BUILDER_SHA256, sha


def normalize_bars(raw):
    """保留分钟末标签 09:31–11:30、13:01–15:00，含收盘竞价。"""
    data = raw.copy()
    if data.duplicated(['symbol', 'datetime']).any():
        raise ValueError('存在重复分钟')
    minute = data.datetime.dt.hour * 60 + data.datetime.dt.minute
    data = data[((minute >= 571) & (minute <= 690)) | ((minute >= 781) & (minute <= 900))].copy()
    data = data[(data.datetime.dt.second == 0) & (data.datetime.dt.microsecond == 0)]
    counts = data.groupby('symbol').datetime.nunique()
    return data[data.symbol.isin(counts[counts == 240].index)].copy()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2021-01-04'); p.add_argument('--end', default='2025-12-31')
    p.add_argument('--input-dir', type=Path, default=Path('data/tick_1m_parquet'))
    p.add_argument('--output-dir', type=Path, default=Path('data/intraday_factors/local_minute_factors'))
    p.add_argument('--limit', type=int); p.add_argument('--max-days', type=int)
    args = p.parse_args()
    if pd.Timestamp(args.start) > pd.Timestamp(args.end) or (args.limit is not None and args.limit < 1) or (args.max_days is not None and args.max_days < 1):
        p.error('日期或限制参数无效')
    snapshots = promote_frame(Path('data/intraday_factors/csi500/snapshots.duckdb'))
    symbols = sorted(read_frame(snapshots).con_code.dropna().unique())[:args.limit]
    days = [pd.Timestamp(path.stem) for path in frame_paths(Path('data/micro_cap_timing_plus/raw/daily'))
            if len(path.stem) == 8 and path.stem.isdigit()
            and pd.Timestamp(args.start) <= pd.Timestamp(path.stem) <= pd.Timestamp(args.end)][:args.max_days]
    if not symbols or not days: raise ValueError('证券集合或本地交易日期为空')
    implementation = sha(Path('src/strategy/intraday_factors.py'))
    builder_hash = sha(Path(__file__))
    repo_hash = sha(Path('src/datahub/local_minute_repository.py'))
    snapshot_hash = sha(snapshots)
    local = MarketDataService(DataRouter({}), repository=LocalMinuteRepository(args.input_dir))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for i, day in enumerate(days, 1):
            name = day.strftime('%Y%m%d'); path = args.output_dir/(name+'.duckdb'); meta_path = path.with_suffix('.json')
            request = DataRequest(symbols=tuple(symbols), start=day, end=day, frequency='1m', adjust='none')
            bars = local.get_cached(DataKind.MINUTE, request, source='local_minute_parquet')
            if bars is None: raise ValueError(f'缺少源文件: {name}')
            version = bars.attrs['data_version']
            expected = {'input_sha256':version, 'implementation_sha256':implementation, 'builder_sha256':builder_hash, 'repository_sha256':repo_hash, 'snapshot_sha256':snapshot_hash, 'symbols':symbols}
            if frame_exists(path) and meta_path.exists():
                meta = json.loads(meta_path.read_text())
                if (all(meta.get(k) == expected[k] for k in ('input_sha256', 'implementation_sha256', 'repository_sha256', 'symbols'))
                        and meta.get('builder_sha256') in (builder_hash, LEGACY_MINUTE_BUILDER_SHA256)
                        and matches_frame_hash(snapshots, meta.get('snapshot_sha256', ''))
                        and matches_frame_hash(path, meta.get('output_sha256', ''))):
                    print(f'{i}/{len(days)} {name} 缓存 股票日={meta["rows"]}', flush=True); continue
            normalized = normalize_bars(bars)
            # 全日成交量为零的股票不能视为真实交易日。
            traded = normalized.groupby('symbol').volume.sum().loc[lambda x: x > 0].index
            normalized = normalized[normalized.symbol.isin(traded)]
            factors = daily_factors(normalized)
            if factors.empty: raise ValueError(f'{name} 无完整分钟股票日')
            write_frame(path, factors)
            meta = dict(expected, date=name, rows=len(factors), raw_rows=len(bars), normalized_rows=len(normalized),
                        source='local_minute_parquet', source_path=bars.attrs['path'], frequency='1m', adjust='none_assumed',
                        timestamp='end_assumed', closing_auction='15:00 retained',
                        note='原始供应商、复权和时间标签未完全核实；完整日并不等于实际可交易。', output_sha256=sha(path))
            tempmeta = meta_path.with_suffix('.json.tmp'); tempmeta.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(tempmeta,meta_path)
            print(f'{i}/{len(days)} {name} 计算 股票日={len(factors)} 原始行={len(bars)}', flush=True)
    finally: local.close()


if __name__ == '__main__': main()
