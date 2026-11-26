"""分钟/竞价因子文件的版本与行级校验，兼容原始缓存和增量刷新缓存。"""
from __future__ import annotations
import hashlib
import json
import pandas as pd
from src.datahub.duckdb_frames import file_sha256, matches_frame_hash, promote_frame, read_frame_with_metadata

LEGACY_MINUTE_BUILDER_SHA256 = "955768cc106ebfd28ccfa1cb4aeac861fff37836fe03709fb2c82873cd6d5f0a"

sha = file_sha256


def load_factors(path, day, symbols, snapshots, *, auction=False):
    path = promote_frame(path)
    info = json.loads(path.with_suffix(".json").read_text())
    data, storage = read_frame_with_metadata(path)
    output_hash = info.get("output_sha256")
    if output_hash and output_hash != storage.get("legacy_sha256") and output_hash != sha(path):
        raise ValueError(f"因子输出校验失败 {path}")
    if len(data) != info["rows"] or not pd.to_datetime(data.date).eq(day).all():
        raise ValueError(f"日期或行数异常 {path}")
    if data.duplicated(["symbol", "date"]).any() or not set(data.symbol).issubset(symbols):
        raise ValueError(f"证券范围或主键异常 {path}")
    impl = "src/strategy/auction_factors.py" if auction else "src/strategy/intraday_factors.py"
    if info.get("implementation_sha256") != sha(impl):
        raise ValueError(f"因子公式版本变化 {path}")
    symbol_hash = hashlib.sha256("\n".join(symbols).encode()).hexdigest()
    if info.get("schema_version") == 2:
        if (not matches_frame_hash(snapshots, info["snapshot_sha256"])
                or info["symbols_sha256"] != symbol_hash or not output_hash):
            raise ValueError(f"刷新缓存来源不匹配 {path}")
        if not auction and (info["mode"] == "computed" or "fast_implementation_sha256" in info):
            if info["fast_implementation_sha256"] != sha("src/strategy/intraday_factors_fast.py"):
                raise ValueError(f"加速实现变化 {path}")
        if not auction and info["repository_sha256"] != sha("src/datahub/local_minute_repository.py"):
            raise ValueError(f"分钟仓库版本变化 {path}")
        if info["mode"] == "reused":
            parent = info["parent_metadata"]
            if parent["implementation_sha256"] != sha(impl):
                raise ValueError(f"父因子版本变化 {path}")
    elif auction:
        if info["symbols_sha256"] != symbol_hash:
            raise ValueError(f"竞价缓存股票集合变化 {path}")
    else:
        legacy = path.suffix == ".parquet" or output_hash == storage.get("legacy_sha256")
        builder_hash = LEGACY_MINUTE_BUILDER_SHA256 if legacy else sha("scripts/build_local_minute_factors.py")
        if (not output_hash or info["symbols"] != symbols or info["builder_sha256"] != builder_hash
                or info["repository_sha256"] != sha("src/datahub/local_minute_repository.py")
                or not matches_frame_hash(snapshots, info["snapshot_sha256"])):
            raise ValueError(f"分钟缓存来源变化 {path}")
    return data, info
