from argparse import Namespace
from datetime import date, datetime
from hashlib import sha256
import json
import sqlite3

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import sync_qmt_minute as job
from src.datahub import DataRouter, DataSourceTimeout, DataValidationError, MarketDataService, Normalizer, load_config
from src.datahub.exceptions import ProviderCapacityError
from src.datahub.providers.xtquant import XtQuantProvider


DAY = date(2026, 11, 23)
SYMBOLS = ("000001.SZ", "600000.SH", "920001.BJ", "920002.BJ")
SUSPENDED = SYMBOLS[-1]


class FakeBridge:
    def __init__(self):
        self.downloads = []
        self.cached = set(SYMBOLS)
        self.fail_read_after_download = False
        self.fail_next_read = False
        self.capacity = None
        self.reads = []
        self.daily_placeholder = False
        self.broken_symbol = SYMBOLS[2]
        self.breakage = "missing"

    def call_method(self, method, **kwargs):
        assert method == "download_history_data2"
        symbols = tuple(kwargs["stock_list"])
        if kwargs["period"] == "1d":
            assert (kwargs["start_time"], kwargs["end_time"]) == ("20261123", "20261123")
            self.downloads.append(symbols)
            return True
        assert kwargs["period"] == "1m"
        assert kwargs["start_time"] == "20261123093000"
        assert kwargs["end_time"] == "20261123160000"
        self.downloads.append(symbols)
        self.cached.update(symbols)
        if self.fail_read_after_download:
            self.fail_read_after_download = False
            self.fail_next_read = True
        return True

    def get_stock_list_in_sector(self, sector, real_timetag=-1):
        return {
            "沪深A股": list(SYMBOLS[:2]), "京市A股": list(SYMBOLS[2:]), "沪深京A股": list(SYMBOLS),
        }[sector]

    def get_market_data_ex(self, *, stock_list, period, subscribe, fill_data, **kwargs):
        assert subscribe is False
        self.reads.append((period, tuple(stock_list)))
        if period == "1m" and self.capacity is not None and len(stock_list) > self.capacity:
            raise RuntimeError("MemoryError: bad allocation")
        if period == "1m" and self.fail_next_read:
            self.fail_next_read = False
            raise TimeoutError("bridge read timed out")
        frames = {}
        times = [f"{minute // 60:02d}{minute % 60:02d}00" for minute in sorted(job.REGULAR_MINUTES)]
        for symbol in stock_list:
            if period == "1m" and (symbol == SUSPENDED or symbol not in self.cached):
                continue
            if symbol == SUSPENDED and not fill_data:
                continue
            amount = len(times) * 1000
            if period == "1d":
                if self.daily_placeholder and not fill_data:
                    continue
                suspended = symbol == SUSPENDED or self.daily_placeholder
                rows = [("20261123", 0 if suspended else len(times),
                         0 if suspended else amount, int(suspended))]
            else:
                rows = [(f"20261123{minute}", 1, 1000, 0) for minute in times]
                if symbol == self.broken_symbol and self.breakage == "missing":
                    rows.pop()
                if symbol == self.broken_symbol and self.breakage == "duplicate":
                    rows.append(rows[-1])
                if symbol == self.broken_symbol and self.breakage == "volume":
                    rows[0] = (rows[0][0], 4, 1000, 0)
            frames[symbol] = pd.DataFrame(rows, columns=["time", "volume", "amount", "suspendFlag"]).assign(
                open=10, high=10, low=10, close=10,
            )
        return frames


def fake_service(bridge):
    config = load_config()
    return MarketDataService(
        DataRouter({"xtquant": XtQuantProvider(xtdata_client=bridge)}),
        Normalizer(unit_configs=config.units),
    )


def test_missing_batch_resumes_and_publishes_with_market_coverage(tmp_path):
    bridge = FakeBridge()
    service = fake_service(bridge)
    output = job.partition(tmp_path, DAY)
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE batch (day TEXT, key TEXT, payload BLOB, inactive TEXT, PRIMARY KEY(day, key));
        """)
        with pytest.raises(DataValidationError, match="1 批未通过"):
            job.sync_day(db, service, tmp_path, DAY, 2)
        assert not output.exists()
        assert db.execute("SELECT count(*) FROM batch").fetchone() == (1,)
        output.parent.mkdir(parents=True)
        output.write_bytes(b"original partition")
        bridge.breakage = None
        job.sync_day(db, service, tmp_path, DAY, 2)
        job.sync_day(db, service, tmp_path, DAY, 2)
        assert bridge.downloads == [(bridge.broken_symbol,)]
        assert db.execute("SELECT count(*) FROM batch").fetchone() == (0,)
    result = pq.ParquetFile(output)
    assert result.metadata.num_rows == 723
    assert result.schema_arrow.metadata[b"zero_trade_symbols"] == b'["920002.BJ"]'
    assert set(result.read(columns=["ts_code"])["ts_code"].to_pylist()) == set(SYMBOLS[:-1])
    backup, = output.parent.glob("*.previous-*")
    assert backup.read_bytes() == b"original partition"


@pytest.mark.parametrize(("breakage", "error"), [("duplicate", "重复行情主键"), ("volume", "分钟汇总与日线不符")])
def test_rejects_duplicate_and_unreconciled_bars(breakage, error):
    bridge = FakeBridge()
    bridge.breakage = breakage
    with pytest.raises(DataValidationError, match=error):
        job.pull_batch(fake_service(bridge), DAY, SYMBOLS)
    assert bridge.downloads == [(bridge.broken_symbol,)]


def test_read_timeout_after_download_reuses_qmt_cache_and_saved_batch(tmp_path):
    bridge = FakeBridge()
    bridge.breakage = None
    bridge.cached.difference_update(SYMBOLS[2:])
    bridge.fail_read_after_download = True
    service = fake_service(bridge)
    output = job.partition(tmp_path, DAY)
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE batch (day TEXT, key TEXT, payload BLOB, inactive TEXT, PRIMARY KEY(day, key));
        """)
        with pytest.raises(DataSourceTimeout, match="bridge read timed out"):
            job.sync_day(db, service, tmp_path, DAY, 2)
        assert not output.exists()
        assert db.execute("SELECT count(*) FROM batch").fetchone() == (1,)
        bridge.cached.difference_update(SYMBOLS[:2])
        job.sync_day(db, service, tmp_path, DAY, 2)
        assert bridge.downloads == [(SYMBOLS[2],)]
    assert pq.ParquetFile(output).metadata.num_rows == 723


def test_mixed_batch_downloads_only_stock_missing_from_qmt_cache():
    bridge = FakeBridge()
    bridge.breakage = None
    bridge.cached.remove(SYMBOLS[2])
    table, inactive = job.pull_batch(fake_service(bridge), DAY, SYMBOLS)
    assert bridge.downloads == [(SYMBOLS[2],)]
    assert table.num_rows == 723
    assert set(table["ts_code"].to_pylist()) == set(SYMBOLS[:-1])
    assert inactive == [SUSPENDED]


def test_allocation_failure_splits_repair_read_without_duplicate_download():
    bridge = FakeBridge()
    bridge.breakage = None
    bridge.cached.clear()
    bridge.capacity = 2
    table, inactive = job.pull_batch(fake_service(bridge), DAY, SYMBOLS)
    assert bridge.downloads == [SYMBOLS[:-1]]
    assert [symbols for period, symbols in bridge.reads if period == "1m"] == [
        SYMBOLS, SYMBOLS[:2], SYMBOLS[2:], SYMBOLS[:-1], SYMBOLS[:1], SYMBOLS[1:3],
    ]
    assert table.num_rows == 723
    assert inactive == [SUSPENDED]


def test_request_cap_preserves_suspension_flags_across_chunks(monkeypatch):
    monkeypatch.setattr(job, "QMT_REQUEST_SIZE", 2)
    bridge = FakeBridge()
    frame = job.fetch_bars(fake_service(bridge), DAY, SYMBOLS, period="1d", fill=True)
    assert bridge.reads == [("1d", SYMBOLS[:2]), ("1d", SYMBOLS[2:])]
    assert frame.attrs["zero_trade_symbols"] == [SUSPENDED]


def test_single_stock_allocation_failure_is_reported():
    bridge = FakeBridge()
    bridge.capacity = 0
    with pytest.raises(ProviderCapacityError, match="共 1 只"):
        job.fetch_bars(fake_service(bridge), DAY, SYMBOLS[:1], period="1m")
    assert bridge.downloads == []


def test_all_zero_legacy_checkpoint_must_be_revalidated(monkeypatch):
    monkeypatch.setattr(job, "MIN_PLACEHOLDER_BATCH_SIZE", len(SYMBOLS))
    bridge = FakeBridge()
    bridge.breakage = None
    bridge.daily_placeholder = True
    service = fake_service(bridge)
    key = sha256(f"{job.VERSION}:{','.join(SYMBOLS)}".encode()).hexdigest()
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_batches([], schema=job.SCHEMA), sink)
    payload = sink.getvalue().to_pybytes()
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE batch (day TEXT, key TEXT, payload BLOB, inactive TEXT, PRIMARY KEY(day, key))")
        db.execute("INSERT INTO batch VALUES (?, ?, ?, ?)", (DAY.isoformat(), key, payload, json.dumps(SYMBOLS)))
        with pytest.raises(DataValidationError, match="整批没有有效成交日线"):
            job.checkpoint(db, service, DAY, SYMBOLS)
        assert bridge.downloads == [SYMBOLS]
        assert db.execute("SELECT payload FROM batch").fetchone() == (payload,)
        bridge.daily_placeholder = False
        table, inactive, _, restored = job.checkpoint(db, service, DAY, SYMBOLS)
        assert table.num_rows == 723
        assert inactive == [SUSPENDED]
        assert restored is False
        assert job.checkpoint(db, service, DAY, SYMBOLS)[-1] is True
        assert bridge.downloads == [SYMBOLS]


def test_single_suspended_stock_can_be_archived():
    bridge = FakeBridge()
    table, inactive = job.pull_batch(fake_service(bridge), DAY, (SUSPENDED,))
    assert table.num_rows == 0
    assert inactive == [SUSPENDED]
    assert bridge.downloads == []


def test_opening_placeholder_is_retained_but_first_trade_matches_daily_open():
    class OpeningPlaceholderBridge(FakeBridge):
        def get_market_data_ex(self, *, stock_list, period, subscribe, fill_data, **kwargs):
            frames = super().get_market_data_ex(
                stock_list=stock_list, period=period, subscribe=subscribe, fill_data=fill_data, **kwargs,
            )
            for frame in frames.values():
                if period == "1m":
                    frame.loc[0, ["open", "high", "low", "close", "volume", "amount"]] = [9, 9, 9, 9, 0, 0]
                else:
                    frame.loc[0, "volume"] -= 1
                    frame.loc[0, "amount"] -= 989
            return frames

    bridge = OpeningPlaceholderBridge()
    bridge.breakage = None
    table, inactive = job.pull_batch(fake_service(bridge), DAY, SYMBOLS[:1])
    opening_bar = table.slice(0, 1).to_pylist()[0]
    assert table.num_rows == 241
    assert opening_bar["trade_time"].endswith("09:30:00")
    assert (opening_bar["open"], opening_bar["vol"]) == (9, 0)
    assert inactive == []
    assert bridge.downloads == []


def test_shanghai_cutoff_keeps_previous_day_before_four():
    assert job.latest_due(datetime(2026, 11, 23, 15, 59, tzinfo=job.SHANGHAI)) == date(2026, 11, 22)
    assert job.latest_due(datetime(2026, 11, 23, 16, 0, tzinfo=job.SHANGHAI)) == DAY


def test_scheduled_run_keeps_failed_date_and_retries_even_without_new_due_day(monkeypatch, tmp_path):
    next_day = date(2026, 11, 24)
    monkeypatch.setattr(job, "latest_due", lambda now: next_day)
    monkeypatch.setattr(job, "trading_days", lambda service, first, last: [DAY, next_day])
    monkeypatch.setattr(job, "notify", lambda db, day, exc: None)
    attempts = []

    def sync(db, service, root, day, batch_size):
        attempts.append(day)
        if attempts == [DAY]:
            raise TimeoutError("test outage")

    monkeypatch.setattr(job, "sync_day", sync)
    args = Namespace(date=None, output_dir=tmp_path, batch_size=64)
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO state VALUES ('next_day', '2026-11-23');
            CREATE TABLE pending (day TEXT PRIMARY KEY);
        """)
        assert job.run(args, db, None) == 1
        assert db.execute("SELECT day FROM pending").fetchall() == [("2026-11-23",)]
        assert job.run(args, db, None) == 0
        assert not db.execute("SELECT day FROM pending").fetchall()
    assert attempts == [DAY, next_day, DAY]
