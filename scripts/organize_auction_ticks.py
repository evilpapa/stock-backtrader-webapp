"""将指定目录的年月 RAR 无损整理为按日 DuckDB。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
if str(Path(__file__).resolve().parent) in sys.path:
    sys.path.remove(str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub.duckdb_frames import frame_exists, inspect_frame, promote_frame, read_frame, write_frame

FIELDS = ['security_id', 'md_date', 'md_time', 'min', 'max', 'pre_close', 'last', 'open',
          'num_trades', 'total_volume_trade', 'total_value_trade', 'bid1', 'bid2', 'bid_size1',
          'bid_size2', 'ask1', 'ask2', 'ask_size1', 'ask_size2']
TYPES = {name: pa.float64() for name in FIELDS}
TYPES['security_id'] = pa.string()
for name in ['md_date', 'md_time', 'num_trades']:
    TYPES[name] = pa.int64()
VERSION = 2


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def members(archive: Path) -> list[tuple[str, str]]:
    result = subprocess.run(['unrar', 'lb', '-c-', str(archive)], capture_output=True, check=True, text=True)
    found = []
    for member in result.stdout.splitlines():
        match = re.fullmatch(r'(\d{6})/(\d{8})\.csv', member.replace('\\', '/'))
        if match:
            month, date = match.groups()
            if month != archive.stem or not date.startswith(month):
                raise ValueError(f'压缩包内日期与月份不一致: {archive} {member}')
            found.append((date, member))
        elif member.replace('\\', '/').rstrip('/') != archive.stem:
            raise ValueError(f'未识别的压缩包成员: {archive} {member}')
    if not found or len({date for date, _ in found}) != len(found):
        raise ValueError(f'压缩包为空或日期重复: {archive}')
    return sorted(found)


def convert_stream(stream, target: Path, date: str, source: dict) -> dict:
    reader = csv.open_csv(stream, read_options=csv.ReadOptions(block_size=2 * 1024 * 1024),
                          convert_options=csv.ConvertOptions(column_types=TYPES))
    if reader.schema.names != FIELDS:
        raise ValueError(f'字段不一致: {reader.schema.names}')
    if any(reader.schema.field(k).type != v for k, v in TYPES.items()):
        raise ValueError('字段类型不一致')
    metadata = dict(source, source_member=source['member'], organizer_version=str(VERSION),
                    price_adjust='unknown', volume_unit='provider_raw')
    rows = 0
    min_time = None
    max_time = None
    batches = []
    for batch in reader:
        if batch.num_rows == 0:
            continue
        for col in ('security_id', 'md_date', 'md_time'):
            if batch.column(col).null_count:
                raise ValueError(f'{date} {col} 含空值')
        dates = batch.column('md_date')
        if pc.min(dates).as_py() != int(date) or pc.max(dates).as_py() != int(date):
            raise ValueError(f'{date} 文件含其他行情日期')
        tmin = pc.min(batch.column('md_time')).as_py()
        tmax = pc.max(batch.column('md_time')).as_py()
        min_time = tmin if min_time is None else min(min_time, tmin)
        max_time = tmax if max_time is None else max(max_time, tmax)
        batches.append(batch)
        rows += batch.num_rows
    if rows == 0:
        raise ValueError(f'{date} 文件无行情行')
    write_frame(target, pa.Table.from_batches(batches, schema=reader.schema), metadata=metadata)
    return {'rows': rows, 'min_md_time': min_time, 'max_md_time': max_time}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True, help='旧版年月 RAR 所在目录')
    parser.add_argument('--output-dir', type=Path, default=Path('data/tick_auction_parquet'))
    parser.add_argument('--start-month', default='202001')
    parser.add_argument('--end-month', default='202610')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{6}', args.start_month) or not re.fullmatch(r'\d{6}', args.end_month) or args.start_month > args.end_month:
        parser.error('月份必须为 YYYYMM，且开始不晚于结束')
    archives = sorted(p for p in args.input_dir.iterdir() if re.fullmatch(r'\d{6}\.rar', p.name) and args.start_month <= p.stem <= args.end_month)
    if not archives:
        parser.error('指定区间未找到压缩包')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, archive in enumerate(archives, 1):
        started = time.monotonic()
        files = members(archive)
        archive_hash = digest(archive)
        dest_dir = args.output_dir / archive.stem[:4] / archive.stem[4:]
        dest_dir.mkdir(parents=True, exist_ok=True)
        n_new = n_skip = 0
        for date, member in files:
            target = dest_dir / f'{date}.duckdb'
            info_path = dest_dir / f'{date}.json'
            source = {'archive': str(archive), 'member': member, 'archive_sha256': archive_hash}
            if frame_exists(target) or info_path.exists():
                if frame_exists(target) and info_path.exists():
                    old = json.loads(info_path.read_text(encoding='utf-8'))
                    rows, meta = inspect_frame(target)
                    consistent = (old.get('archive_sha256') == archive_hash
                                  and old.get('member') == member
                                  and old.get('rows') == rows
                                  and meta.get('archive_sha256') == archive_hash
                                  and meta.get('source_member', old.get('member')) == member)
                    file_version = meta.get('organizer_version', str(old.get('version')))
                    if consistent and old.get('version') in (1, VERSION) and file_version in ('1', str(VERSION)):
                        if file_version == '1':
                            # 原版本数量列为整数；安全检查后升级为统一 float64 类型。
                            frame = read_frame(target)
                            for name, dtype in TYPES.items():
                                if pa.types.is_float64(dtype) and frame[name].dtype.kind in 'iu':
                                    if frame[name].abs().max() > 2**53:
                                        raise ValueError(f'{target}: {name} 超过 float64 精确整数范围')
                            schema = pa.schema([pa.field(name, TYPES[name]) for name in FIELDS])
                            upgraded = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
                            write_frame(target, upgraded, metadata=dict(meta, organizer_version=str(VERSION)))
                        persisted = promote_frame(target)
                        if old.get('version') != VERSION or 'duckdb_bytes' not in old:
                            old['version'] = VERSION
                            old['duckdb_bytes'] = persisted.stat().st_size
                            atomic_json(info_path, old)
                        n_skip += 1
                        continue
                raise RuntimeError(f'已存在不匹配或不完整的输出，请检查: {target} {info_path}')
            with TemporaryDirectory(dir=dest_dir) as staging:
                tmp = Path(staging) / target.name
                with subprocess.Popen(['unrar', 'p', '-inul', '-c-', str(archive), member],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                    try:
                        result = convert_stream(proc.stdout, tmp, date, source)
                        proc.stdout.close()
                        stderr = proc.stderr.read().decode('utf-8', errors='replace')
                        code = proc.wait()
                        if code:
                            raise RuntimeError(f'解压失败 {archive} {member}: {code} {stderr[:500]}')
                    except BaseException:
                        proc.kill()
                        raise
                os.replace(tmp, target)
            info = {'date': date, 'version': VERSION, **source, **result, 'duckdb_bytes': target.stat().st_size}
            atomic_json(info_path, info)
            n_new += 1
        print(f'{index}/{len(archives)} {archive.stem}: {len(files)} 天、新增 {n_new}、跳过 {n_skip}，{time.monotonic()-started:.1f} 秒', flush=True)
    print('逐日 DuckDB 整理完成。')


if __name__ == '__main__':
    main()
