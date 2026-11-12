"""将年月 RAR 内逐日集合竞价 CSV 无损整理为按日 Parquet。"""
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

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

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
    metadata = {b'source_archive': source['archive'].encode(), b'source_member': source['member'].encode(),
                b'archive_sha256': source['archive_sha256'].encode(), b'organizer_version': str(VERSION).encode(),
                b'price_adjust': b'unknown', b'volume_unit': b'provider_raw'}
    schema = reader.schema.with_metadata(metadata)
    rows = 0
    min_time = None
    max_time = None
    with pq.ParquetWriter(target, schema, compression='zstd') as writer:
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
            writer.write_batch(batch)
            rows += batch.num_rows
    if rows == 0:
        raise ValueError(f'{date} 文件无行情行')
    return {'rows': rows, 'min_md_time': min_time, 'max_md_time': max_time}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('data/tick_auction'))
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
            target = dest_dir / f'{date}.parquet'
            info_path = dest_dir / f'{date}.json'
            source = {'archive': str(archive), 'member': member, 'archive_sha256': archive_hash}
            if target.exists() or info_path.exists():
                if target.exists() and info_path.exists():
                    old = json.loads(info_path.read_text(encoding='utf-8'))
                    pf = pq.ParquetFile(target)
                    meta = pf.schema_arrow.metadata or {}
                    consistent = (old.get('archive_sha256') == archive_hash
                                  and old.get('rows') == pf.metadata.num_rows
                                  and meta.get(b'archive_sha256') == archive_hash.encode()
                                  and meta.get(b'source_member') == member.encode())
                    file_version = meta.get(b'organizer_version', b'').decode()
                    if consistent and old.get('version') in (1, VERSION) and file_version in ('1', str(VERSION)):
                        if file_version == '1':
                            # 原版本数量列为整数；安全检查后升级为统一 float64 类型。
                            table = pf.read()
                            float_fields = [k for k,v in TYPES.items() if pa.types.is_float64(v)]
                            for name in float_fields:
                                col = table[name]
                                if pa.types.is_integer(col.type) and len(col):
                                    max_abs = pc.max(pc.abs(col)).as_py()
                                    if max_abs is not None and max_abs > 2**53:
                                        raise ValueError(f'{target}: {name} 超过 float64 精确整数范围')
                            new_meta = dict(meta)
                            new_meta[b'organizer_version'] = str(VERSION).encode()
                            new_schema = pa.schema([pa.field(name, TYPES[name]) for name in FIELDS], metadata=new_meta)
                            upgraded = table.cast(new_schema)
                            temp = dest_dir / (date + '.' + uuid.uuid4().hex + '.partial')
                            pq.write_table(upgraded, temp, compression='zstd')
                            os.replace(temp, target)
                        if file_version == '1' or old.get('version') != VERSION:
                            old['version'] = VERSION
                            old['parquet_bytes'] = target.stat().st_size
                            atomic_json(info_path, old)
                        n_skip += 1
                        continue
                raise RuntimeError(f'已存在不匹配或不完整的输出，请检查: {target} {info_path}')
            tmp = dest_dir / (date + '.' + uuid.uuid4().hex + '.partial')
            proc = subprocess.Popen(['unrar', 'p', '-inul', '-c-', str(archive), member], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                result = convert_stream(proc.stdout, tmp, date, source)
                proc.stdout.close()
                stderr = proc.stderr.read().decode('utf-8', errors='replace')
                code = proc.wait()
                if code:
                    raise RuntimeError(f'解压失败 {archive} {member}: {code} {stderr[:500]}')
            except BaseException:
                proc.kill()
                proc.wait()
                raise
            os.replace(tmp, target)
            info = {'date': date, 'version': VERSION, **source, **result, 'parquet_bytes': target.stat().st_size}
            atomic_json(info_path, info)
            n_new += 1
        print(f'{index}/{len(archives)} {archive.stem}: {len(files)} 天、新增 {n_new}、跳过 {n_skip}，{time.monotonic()-started:.1f} 秒', flush=True)
    print('逐日 Parquet 整理完成。')


if __name__ == '__main__':
    main()
