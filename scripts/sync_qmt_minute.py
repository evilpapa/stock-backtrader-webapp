"""Download, validate and publish the Big QMT daily A-share minute partition."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
import fcntl
from hashlib import sha256
from itertools import batched
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.datahub import (
    DataKind, DataRequest, DataRouter, DataValidationError, MarketDataService,
    Normalizer, ProviderFactory, TickerMapper, load_config,
)
from src.datahub.exceptions import ProviderCapacityError

LOGGER = logging.getLogger("qmt-minute-sync")
SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKETS = {"SH", "SZ", "BJ"}
QMT_REQUEST_SIZE = 16
MIN_PLACEHOLDER_BATCH_SIZE = 8
PRICE_FIELDS = ["open", "high", "low", "close"]
VALUE_FIELDS = [*PRICE_FIELDS, "volume", "amount"]
REGULAR_MINUTES = frozenset(range(9 * 60 + 30, 11 * 60 + 31)) | frozenset(range(13 * 60 + 1, 15 * 60 + 1))
ALLOWED_MINUTES = REGULAR_MINUTES | frozenset(range(15 * 60 + 1, 15 * 60 + 31))
VERSION = "qmt-postclose-1m-v1"
SCHEMA = pa.schema([
    ("ts_code", pa.string()), ("trade_time", pa.string()), ("close", pa.float64()),
    ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()),
    ("vol", pa.float64()), ("amount", pa.float64()),
])


def build_service() -> MarketDataService:
    config = load_config()
    provider = ProviderFactory.create("xtquant", config, require_bridge=True)
    normalizer = Normalizer(ticker_mapper=config.ticker_mapper, unit_configs=config.units)
    return MarketDataService(DataRouter({"xtquant": provider}), normalizer)


def latest_due(now: datetime) -> date:
    return now.date() if now.time() >= time(16) else now.date() - timedelta(days=1)


def trading_days(service: MarketDataService, first: date, last: date) -> list[date]:
    calendar = service.get_trade_calendar(DataRequest(
        start=first - timedelta(days=21), end=last, exchange="SH",
    ), use_cache=False)
    if calendar.empty or calendar["trade_date"].isna().any():
        raise DataValidationError("QMT 交易日历为空或日期无效，请检查行情桥接")
    days = calendar.loc[calendar["is_open"].eq(1), "trade_date"].dt.date
    if days.empty or max(days) < last - timedelta(days=14):
        raise DataValidationError(f"QMT 交易日历过期，目标日期 {last}")
    return sorted({day for day in days if first <= day <= last})


def stock_universe(service: MarketDataService, day: date) -> tuple[str, ...]:
    latest_session = latest_due(datetime.now(SHANGHAI))
    as_of = datetime.combine(day, time(15), SHANGHAI) if day < latest_session else None
    sectors = {"沪深A股": {"SH", "SZ"}, "京市A股": {"BJ"}}
    market_sets = {}
    for sector, expected_markets in sectors.items():
        response = service.query(DataKind.SECTOR_MEMBER, DataRequest(
            as_of=as_of, options={"sector_name": sector, "postclose": True},
        ), use_cache=False)
        codes = {TickerMapper.normalize(code) for code in response["symbol"]}
        observed_markets = set(map(TickerMapper.to_exchange, codes))
        if observed_markets != expected_markets:
            raise DataValidationError(f"QMT {sector} 股票池不完整 {sorted(observed_markets)}，请检查 QMT 端板块接口")
        market_sets[sector] = codes
    market_counts = Counter(
        TickerMapper.to_exchange(symbol) for symbols in market_sets.values() for symbol in symbols
    )
    response = service.query(DataKind.SECTOR_MEMBER, DataRequest(
        as_of=as_of, options={"sector_name": "沪深京A股", "postclose": True},
    ), use_cache=False)
    combined = {TickerMapper.normalize(code) for code in response["symbol"]}
    if combined != set.union(*market_sets.values()):
        raise DataValidationError("QMT 沪深京 A 股总板块与分板块成分不一致")
    LOGGER.info("%s 股票池 %s", day, dict(sorted(market_counts.items())))
    return tuple(sorted(combined))


def fetch_bars(service: MarketDataService, day: date, symbols: tuple[str, ...], *,
               period: str, download: bool = False, fill: bool = False) -> pd.DataFrame:
    frames = []
    for chunk in batched(symbols, QMT_REQUEST_SIZE):
        frames.extend(fetch_bar_chunk(service, day, chunk, period=period, download=download, fill=fill))
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        return frames[0]
    zero_trade = {symbol for frame in nonempty for symbol in frame.attrs.get("zero_trade_symbols", ())}
    combined = pd.concat(nonempty, ignore_index=True) if len(nonempty) > 1 else nonempty[0]
    if zero_trade:
        combined.attrs["zero_trade_symbols"] = sorted(zero_trade)
    return combined


def fetch_bar_chunk(service: MarketDataService, day: date, symbols: tuple[str, ...], *,
                    period: str, download: bool, fill: bool) -> list[pd.DataFrame]:
    kind = DataKind.MINUTE if period == "1m" else DataKind.DAILY
    fields = ("time", *VALUE_FIELDS, *(("suspendFlag",) if kind == DataKind.DAILY else ()))
    try:
        frame = service.get(kind, DataRequest(
            symbols=symbols, start=day, end=day, frequency=period, fields=fields,
            options={"download": download, "fill_data": fill, "postclose": True},
        ), use_cache=False)
    except ProviderCapacityError:
        if len(symbols) == 1:
            raise
        middle = len(symbols) // 2
        LOGGER.warning("%s %s QMT 内存不足，缩小读取请求 %d -> %d + %d",
                       day, period, len(symbols), middle, len(symbols) - middle)
        left = fetch_bar_chunk(service, day, symbols[:middle], period=period, download=False, fill=fill)
        right = fetch_bar_chunk(service, day, symbols[middle:], period=period, download=False, fill=fill)
        return left + right
    if not frame.empty:
        keys = frame[["symbol", "datetime"]]
        values = frame[VALUE_FIELDS].to_numpy(dtype="float64", na_value=np.nan)
        if (not keys["datetime"].dt.date.eq(day).all() or
                not set(keys["symbol"]).issubset(symbols) or not np.isfinite(values).all() or
                (values[:, -2:] < 0).any() or keys.duplicated().any()):
            raise DataValidationError(f"{day} {period} 含越界日期、异常数值或重复主键")
    return [frame]


def cached_minutes(service: MarketDataService, day: date,
                   symbols: tuple[str, ...]) -> tuple[pd.DataFrame, set[str]]:
    try:
        return fetch_bars(service, day, symbols, period="1m"), set()
    except DataValidationError:
        if len(symbols) == 1:
            return pd.DataFrame(columns=["symbol", "datetime", *VALUE_FIELDS]), set(symbols)
        middle = len(symbols) // 2
        left, bad_left = cached_minutes(service, day, symbols[:middle])
        right, bad_right = cached_minutes(service, day, symbols[middle:])
        if left.empty or right.empty:
            return (right if left.empty else left), bad_left | bad_right
        return pd.concat([left, right], ignore_index=True), bad_left | bad_right


def reconcile(active: pd.DataFrame, minutes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    if active.empty:
        return minutes.iloc[0:0], {}
    bars = minutes.loc[minutes["symbol"].isin(active.index)].copy()
    if bars.empty:
        return bars, dict.fromkeys(active.index, "活跃股票缺少分钟线")
    bars = bars.sort_values(["symbol", "datetime"])
    timestamp = bars["datetime"]
    bars["slot"] = timestamp.dt.hour * 60 + timestamp.dt.minute
    invalid_slots = ~timestamp.eq(timestamp.dt.floor("min")) | ~bars["slot"].isin(ALLOWED_MINUTES)
    required = bars.loc[bars["slot"].isin(REGULAR_MINUTES)].groupby("symbol")["slot"].nunique()
    missing = required.reindex(active.index, fill_value=0).ne(len(REGULAR_MINUTES))
    traded_bars = bars.loc[bars["volume"].gt(0) | bars["amount"].gt(0)]
    prices = traded_bars.groupby("symbol").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
    ).reindex(active.index)
    turnover = bars.groupby("symbol")[["volume", "amount"]].sum().reindex(active.index)
    fields_ok = pd.DataFrame(
        np.isclose(prices, active[PRICE_FIELDS], rtol=0, atol=1e-6), index=active.index, columns=PRICE_FIELDS,
    )
    fields_ok["volume"] = (turnover["volume"] - active["volume"]).abs().le(100)
    fields_ok["amount"] = (turnover["amount"] - active["amount"]).abs().le(active["amount"].mul(0.0005).clip(lower=300))
    issues = dict.fromkeys(bars.loc[invalid_slots, "symbol"], "分钟时间戳超出交易时段")
    for symbol in active.index[missing]:
        issues.setdefault(symbol, "缺少交易时段分钟")
    for symbol in fields_ok.index[~fields_ok.all(axis=1) & ~missing]:
        fields = fields_ok.columns[~fields_ok.loc[symbol]]
        issues.setdefault(symbol, f"分钟汇总与日线不符({','.join(fields)})")
    return bars, issues


def check_minutes(traded: pd.DataFrame, inactive: set[str],
                  minutes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    bars, issues = reconcile(traded, minutes)
    unexpected = minutes.loc[minutes["symbol"].isin(inactive) &
                             (minutes["volume"].gt(0) | minutes["amount"].gt(0)), "symbol"]
    issues.update(dict.fromkeys(unexpected, "零成交日线与有成交分钟线冲突"))
    return bars, issues


def pull_batch(service: MarketDataService, day: date, symbols: tuple[str, ...]) -> tuple[pa.Table, list[str]]:
    daily = fetch_bars(service, day, symbols, period="1d")
    if daily["symbol"].duplicated().any():
        raise DataValidationError(f"{day} 同一证券有多条日线")
    traded = daily.loc[daily["volume"].gt(0) & daily["amount"].gt(0)].set_index("symbol")
    check_placeholder = len(symbols) >= MIN_PLACEHOLDER_BATCH_SIZE
    inactive = set(symbols) - set(traded.index)
    if inactive:
        confirmed = set(daily.attrs.get("zero_trade_symbols", ()))
        if check_placeholder and traded.empty:
            confirmed.clear()
        else:
            suspects = tuple(sorted(inactive - confirmed))
            if suspects:
                confirmation = fetch_bars(service, day, suspects, period="1d", fill=True)
                confirmed.update(confirmation.attrs.get("zero_trade_symbols", ()))
        unresolved = inactive - confirmed
        if unresolved:
            repaired = fetch_bars(service, day, tuple(sorted(unresolved)), period="1d", download=True, fill=True)
            repaired_trades = repaired.loc[repaired["volume"].gt(0) & repaired["amount"].gt(0)]
            if repaired_trades["symbol"].duplicated().any():
                raise DataValidationError(f"{day} 同一证券有多条补下载日线")
            traded = pd.concat([traded, repaired_trades.set_index("symbol")])
            inactive -= set(repaired_trades["symbol"])
            confirmed.update(repaired.attrs.get("zero_trade_symbols", ()))
            unresolved = inactive - confirmed
            if unresolved:
                raise DataValidationError(f"{day} 缺少可确认的日线或停牌状态 {','.join(sorted(unresolved))}")
    if check_placeholder and traded.empty:
        raise DataValidationError(f"{day} 整批没有有效成交日线，QMT 可能返回了占位行情 {symbols[0]}–{symbols[-1]}")
    minutes, invalid_cache = cached_minutes(service, day, symbols)
    validated, issues = check_minutes(traded, inactive, minutes)
    missing = tuple(sorted(issues.keys() | invalid_cache))
    if missing:
        LOGGER.info("%s 1m 缓存复用 %d 只，补下载 %d 只", day, len(symbols) - len(missing), len(missing))
        repaired = fetch_bars(service, day, missing, period="1m", download=True)
        retained = minutes.loc[~minutes["symbol"].isin(missing)]
        if retained.empty or repaired.empty:
            minutes = repaired if retained.empty else retained
        else:
            minutes = pd.concat([retained, repaired], ignore_index=True)
        validated, issues = check_minutes(traded, inactive, minutes)
        if issues:
            details = " ".join(f"{symbol}({reason})" for symbol, reason in sorted(issues.items()))
            raise DataValidationError(f"{day} {details}")
    output = validated.rename(columns={"symbol": "ts_code", "datetime": "trade_time", "volume": "vol"}).copy()
    if output.empty:
        return pa.Table.from_batches([], schema=SCHEMA), sorted(inactive)
    output["trade_time"] = output["trade_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return pa.Table.from_pandas(output[SCHEMA.names], schema=SCHEMA, preserve_index=False), sorted(inactive)


def partition(root: Path, day: date) -> Path:
    return root / f"year={day:%Y}/month={day:%m}/day={day:%d}/{day:%Y%m%d}.parquet"


def is_published(path: Path, day: date) -> bool:
    if not path.is_file():
        return False
    try:
        file = pq.ParquetFile(path)
    except pa.ArrowInvalid:
        return False
    metadata = file.schema_arrow.metadata or {}
    return (metadata.get(b"validation") == VERSION.encode() and
            metadata.get(b"trade_date") == day.isoformat().encode() and
            metadata.get(b"rows") == str(file.metadata.num_rows).encode() and
            file.schema_arrow.equals(SCHEMA))


def publish(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp") as temporary:
        pq.write_table(table, temporary.name, compression="zstd")
        persisted = pq.read_table(temporary.name, partitioning=None)
        if not persisted.equals(table, check_metadata=True):
            raise DataValidationError(f"Parquet 写后校验失败 {path}")
        os.fchmod(temporary.fileno(), (path.stat().st_mode & 0o777) if path.exists() else 0o600)
        os.fsync(temporary.fileno())
        if path.exists():
            version = sha256(path.read_bytes()).hexdigest()[:12]
            backup = path.with_name(f"{path.stem}.previous-{version}")
            try:
                os.link(path, backup)
            except FileExistsError:
                if not backup.samefile(path):
                    raise
            if not backup.samefile(path):
                raise DataValidationError(f"源分区在发布期间发生变化 {path}")
            LOGGER.info("保留原文件 %s", backup)
            os.replace(temporary.name, path)
        else:
            os.link(temporary.name, path)


def checkpoint(db: sqlite3.Connection, service: MarketDataService, day: date,
               symbols: tuple[str, ...]) -> tuple[pa.Table, list[str], str, bool]:
    key = sha256(f"{VERSION}:{','.join(symbols)}".encode()).hexdigest()
    saved = db.execute("SELECT payload, inactive FROM batch WHERE day=? AND key=?", (day.isoformat(), key)).fetchone()
    if saved is not None:
        payload, inactive = saved
        table = pq.read_table(pa.BufferReader(payload))
        if table.num_rows or len(symbols) < MIN_PLACEHOLDER_BATCH_SIZE:
            return table, json.loads(inactive), sha256(payload).hexdigest(), True
        LOGGER.warning("%s 旧断点整批为零成交，重新校验 %s–%s", day, symbols[0], symbols[-1])
    table, inactive = pull_batch(service, day, symbols)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    payload = sink.getvalue().to_pybytes()
    with db:
        db.execute("""
            INSERT INTO batch VALUES (?, ?, ?, ?)
            ON CONFLICT(day, key) DO UPDATE SET payload=excluded.payload, inactive=excluded.inactive
        """, (day.isoformat(), key, payload, json.dumps(inactive)))
    return table, inactive, sha256(payload).hexdigest(), False


def sync_day(db: sqlite3.Connection, service: MarketDataService, root: Path, day: date, batch_size: int) -> Path:
    path = partition(root, day)
    universe_key = f"universe:{day}"
    if not is_published(path, day):
        saved_universe = db.execute("SELECT value FROM state WHERE key=?", (universe_key,)).fetchone()
        if saved_universe:
            symbols = tuple(json.loads(saved_universe[0]))
        else:
            symbols = stock_universe(service, day)
            setting(db, universe_key, json.dumps(symbols))
        tables, inactive, failures = [], [], []
        version = sha256()
        for index, group in enumerate(batched(symbols, batch_size), start=1):
            try:
                table, zero_trade, digest, restored = checkpoint(db, service, day, group)
            except DataValidationError as exc:
                LOGGER.warning("第 %d 批校验失败 %s", index, exc)
                failures.append(index)
                continue
            tables.append(table)
            inactive.extend(zero_trade)
            version.update(digest.encode())
            LOGGER.info("%s 第 %d 批 %s %d 只 / %d 条，零成交 %d 只", day, index,
                        "断点复用" if restored else "校验完成", len(group), table.num_rows, len(zero_trade))
        if failures:
            raise DataValidationError(f"{day} 仍有 {len(failures)} 批未通过校验，见日志中的证券代码")
        table = pa.concat_tables(tables)
        counts = Counter(map(TickerMapper.to_exchange, set(table["ts_code"].to_pylist())))
        if counts.keys() != MARKETS or sum(counts.values()) + len(inactive) != len(symbols):
            raise DataValidationError(f"{day} 最终覆盖不全：有成交 {dict(counts)}，零成交 {len(inactive)}")
        metadata = {
            "validation": VERSION, "source": "xtquant", "trade_date": day.isoformat(),
            "frequency": "1m", "adjust": "none", "timezone": str(SHANGHAI), "data_version": version.hexdigest(),
            "rows": str(table.num_rows), "volume_unit": "share", "amount_unit": "CNY",
            "market_symbol_counts": json.dumps(dict(sorted(counts.items()))),
            "zero_trade_symbols": json.dumps(sorted(inactive)),
        }
        publish(path, table.replace_schema_metadata(metadata))
        LOGGER.info("已发布 %s，%d 条，有成交 %s，零成交 %d 只", path, table.num_rows, dict(counts), len(inactive))
    else:
        LOGGER.info("已存在通过本任务校验的日分区 %s", path)
    with db:
        db.execute("DELETE FROM batch WHERE day=?", (day.isoformat(),))
        db.execute("DELETE FROM state WHERE key=?", (universe_key,))
    return path


def setting(db: sqlite3.Connection, key: str, value: str) -> None:
    with db:
        db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, value))


def notify(db: sqlite3.Connection, day: date, problem: Exception) -> None:
    key = f"notified:{day}"
    previous = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    if previous == (day.isoformat(),):
        return
    setting(db, key, day.isoformat())
    program = shutil.which("notify-send")
    if program is not None:
        try:
            subprocess.run(
                [program, "--urgency=normal", "--app-name=QMT 分钟归档", "QMT 收盘下载待重试",
                 f"{day} {str(problem)[:350]}\n请检查 QMT 桥接端。任务将在 5 分钟后重试。"],
                timeout=5, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            LOGGER.warning("桌面通知投递失败")


def run(args: argparse.Namespace, db: sqlite3.Connection, service: MarketDataService) -> int:
    due = latest_due(datetime.now(SHANGHAI))
    if args.date is not None and args.date > due:
        LOGGER.error("%s 尚未到北京时间 16:00", args.date)
        return 2
    cursor = db.execute("SELECT value FROM state WHERE key='next_day'").fetchone()
    first = args.date or (date.fromisoformat(cursor[0]) if cursor else due)
    if args.date is None and not cursor:
        setting(db, "next_day", first.isoformat())
    if first <= due:
        try:
            days = trading_days(service, first, args.date or due)
        except Exception as exc:
            LOGGER.exception("%s 查询归档日历失败", first)
            if args.date is None:
                notify(db, first, exc)
            return 1
    else:
        days = []
    if args.date is None:
        with db:
            db.executemany("INSERT OR IGNORE INTO pending VALUES (?)", [(item.isoformat(),) for item in days])
            if first <= due:
                db.execute("UPDATE state SET value=? WHERE key='next_day'", ((due + timedelta(days=1)).isoformat(),))
        days = [date.fromisoformat(value) for (value,) in db.execute("SELECT day FROM pending ORDER BY day")]
    failed = False
    for day in days:
        try:
            sync_day(db, service, args.output_dir, day, args.batch_size)
        except Exception as exc:
            LOGGER.exception("%s 归档未完成", day)
            if args.date is None:
                notify(db, day, exc)
            failed = True
            continue
        if args.date is None:
            with db:
                db.execute("DELETE FROM pending WHERE day=?", (day.isoformat(),))
                db.execute("DELETE FROM state WHERE key=?", (f"notified:{day}",))
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, help="手动单次运行，日期为 YYYY-MM-DD")
    parser.add_argument("--output-dir", type=Path, default=Path("data/tick_1m_parquet"))
    parser.add_argument("--state-dir", type=Path, default=Path("data/qmt_minute_sync"))
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("src.datahub.router").setLevel(logging.WARNING)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOGGER.error("该状态目录已有一个归档进程")
            return 1
        db = sqlite3.connect(args.state_dir / "state.sqlite3")
        service = build_service()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pending (day TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS batch (
                    day TEXT NOT NULL, key TEXT NOT NULL, payload BLOB NOT NULL, inactive TEXT NOT NULL,
                    PRIMARY KEY (day, key)
                );
            """)
            return run(args, db, service)
        finally:
            service.close()
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
