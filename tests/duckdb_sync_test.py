"""Offline tests for the QMT-to-DuckDB synchronisation layer."""

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

import pandas as pd

from scripts.duckdb.config import load_sector_map
from scripts.duckdb.fetcher import fetch_batches
from src.utils.bigqmt_client import QmtDataClient as QmtRpc
from scripts.duckdb.store import DuckDBStore
from scripts.duckdb.sync import (
    _partition_bars_by_asset_type,
    fetch_instrument_details,
    filter_instruments_by_open_date,
)
from scripts.duckdb.universe import UniverseDiscovery
from scripts.targets import parse_targets


class DuckDbSyncTest(unittest.TestCase):
    def test_sector_config_does_not_restore_commented_default_groups(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "universe.yaml"
            path.write_text(
                "asset_groups:\n  stock:\n    - 沪深A股\n  etf:\n    - 沪深ETF\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_sector_map(path),
                {"stock": ["沪深A股"], "etf": ["沪深ETF"]},
            )

    def test_instrument_details_are_upserted_with_normalized_dates(self):
        with TemporaryDirectory() as temp_dir:
            store = DuckDBStore(Path(temp_dir) / "stock.duckdb")
            try:
                store.initialize()
                details = pd.DataFrame([{
                    "symbol": "600000.SH", "asset_type": "stock", "market": "SH",
                    "instrument_name": "浦发银行", "open_date": "19991110",
                    "expire_date": None, "detail_json": '{"OpenDate": 19991110}',
                    "fetched_at": pd.Timestamp("2026-09-22"),
                }])
                store.upsert_instrument_details(details)
                row = store.connection.execute(
                    "SELECT symbol, open_date, detail_json FROM instrument_details"
                ).fetchone()
                self.assertEqual(row, ("600000.SH", pd.Timestamp("1999-11-10").date(), details.iloc[0]["detail_json"]))
            finally:
                store.close()

    def test_open_date_filter_skips_future_instruments(self):
        instruments = pd.DataFrame([
            {"symbol": "600000.SH", "asset_type": "stock"},
            {"symbol": "600001.SH", "asset_type": "stock"},
            {"symbol": "600002.SH", "asset_type": "stock"},
        ])
        details = pd.DataFrame([
            {"symbol": "600000.SH", "open_date": pd.Timestamp("1999-11-10")},
            {"symbol": "600001.SH", "open_date": pd.Timestamp("2027-01-01")},
        ])
        filtered, skipped = filter_instruments_by_open_date(
            instruments,
            details,
            end_date=pd.Timestamp("2026-09-22").date(),
        )
        self.assertEqual(filtered["symbol"].tolist(), ["600000.SH", "600002.SH"])
        self.assertEqual(skipped, 1)

    def test_fetch_instrument_details_normalizes_open_date(self):
        class FakeQmt:
            def instrument_detail(self, symbol, **_kwargs):
                return {
                    "InstrumentName": f"name-{symbol}",
                    "OpenDate": 20270101 if symbol == "600001.SH" else 19991110,
                    "ExpireDate": 99999999,
                }

        details, errors = fetch_instrument_details(
            FakeQmt(),
            pd.DataFrame([
                {"symbol": "600000.SH", "asset_type": "stock", "market": "SH"},
                {"symbol": "600001.SH", "asset_type": "stock", "market": "SH"},
            ]),
        )
        self.assertEqual(errors, [])
        self.assertEqual(details["open_date"].dt.strftime("%Y%m%d").tolist(), ["19991110", "20270101"])
        self.assertTrue(details["expire_date"].isna().all())

    def test_duckdb_upserts_are_idempotent(self):
        with TemporaryDirectory() as temp_dir:
            store = DuckDBStore(Path(temp_dir) / "market.duckdb")
            try:
                store.initialize()
                instruments = pd.DataFrame([{
                    "symbol": "600000.SH", "market": "SH", "asset_type": "stock",
                    "source_sectors": "沪深A股",
                }])
                bars = pd.DataFrame([{
                    "symbol": "600000.SH", "market": "SH", "asset_type": "stock",
                    "trade_date": pd.Timestamp("2024-01-02"), "open": 10.0, "high": 11.0,
                    "low": 9.0, "close": 10.5, "volume": 100.0, "amount": 1050.0,
                    "dividend_type": "none", "source": "test",
                    "ingested_at": pd.Timestamp("2024-01-03"),
                }])
                store.upsert_instruments(instruments)
                store.upsert_bars(bars)
                store.upsert_bars(bars.assign(close=12.0))
                self.assertEqual(store.connection.execute("SELECT count(*) FROM daily_bars").fetchone()[0], 1)
                self.assertEqual(store.connection.execute("SELECT close FROM daily_bars").fetchone()[0], 12.0)
            finally:
                store.close()

    def test_universe_deduplicates_and_prefers_etf_classification(self):
        class FakeXtdata:
            def get_stock_list_in_sector(self, sector_name):
                return {
                    "沪深A股": ["600000.SH", "510300.SH"],
                    "沪深基金": ["510300.SH", "159919.SZ"],
                }[sector_name]

        discovery = UniverseDiscovery(xtdata_client=FakeXtdata())
        frame, failures = discovery.discover({"stock": ["沪深A股"], "etf": ["沪深基金"]})

        self.assertEqual(failures, [])
        self.assertEqual(frame.set_index("symbol").loc["510300.SH", "asset_type"], "etf")
        self.assertEqual(frame["symbol"].tolist(), ["510300.SH", "159919.SZ", "600000.SH"])

    def test_qmt_daily_bars_keeps_batch_when_amount_is_missing(self):
        calls = []

        class FakeXtdata:
            def get_market_data_ex(self, **params):
                calls.append(("get_market_data_ex", params))
                return {
                    "600000.SH": [{"time": "20240102", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}],
                    "000001.SZ": [{"time": "20240102", "open": 8, "high": 9, "low": 7, "close": 8.5, "volume": 200, "amount": 1700}],
                }

        client = QmtRpc(xtdata_client=FakeXtdata())
        result = client.daily_bars(["600000.SH", "000001.SZ"], "20240101", "20240103")

        self.assertEqual(set(result), {"600000.SH", "000001.SZ"})
        self.assertTrue(pd.isna(result["600000.SH"]["amount"].iloc[0]))
        self.assertEqual(result["000001.SZ"]["amount"].iloc[0], 1700)
        self.assertEqual(calls[0][0], "get_market_data_ex")

    def test_qmt_download_missing_uses_supported_download_params(self):
        calls = []

        class FakeXtdata:
            def get_market_data_ex(self, **params):
                calls.append(("get_market_data_ex", params))
                if len([item for item in calls if item[0] == "get_market_data_ex"]) == 1:
                    return {"000001.SZ": []}
                return {
                    "000001.SZ": [{
                        "time": "20240102", "open": 8, "high": 9, "low": 7,
                        "close": 8.5, "volume": 200, "amount": 1700,
                    }],
                }

            def download_history_data2(self, **params):
                calls.append(("download_history_data2", params))
                return None

        client = QmtRpc(xtdata_client=FakeXtdata())
        result = client.daily_bars(
            ["000001.SZ"], "20240101", "20240103", download_missing=True,
        )

        self.assertEqual(len(result["000001.SZ"]), 1)
        self.assertEqual(calls[1][0], "download_history_data2")
        self.assertNotIn("dividend_type", calls[1][1])
        self.assertEqual(calls[1][1]["end_time"], "20240103")
        self.assertEqual(calls[2][0], "get_market_data_ex")

    def test_sector_list_explicitly_allows_qmt_fallback(self):
        calls = []

        class FakeXtdata:
            def get_sector_list(self, **params):
                calls.append(("get_sector_list", params))
                return ["沪深A股", "沪深ETF"]

        client = QmtRpc(xtdata_client=FakeXtdata())
        self.assertEqual(client.sector_list(allow_fallback=True), ["沪深A股", "沪深ETF"])
        self.assertEqual(calls[0][1], {"allow_fallback": True})

    def test_market_bars_normalizes_tick_fields_for_kdb(self):
        class FakeXtdata:
            def get_market_data_ex(self, **params):
                if params["period"] != "tick":
                    raise AssertionError("expected tick period")
                return {
                    "600000.SH": [{
                        "time": 1704168600000,
                        "lastPrice": 10.1,
                        "volume": 100,
                        "amount": 1010,
                        "bidPrice": 10.0,
                        "askPrice": 10.2,
                        "bidVol": 50,
                        "askVol": 60,
                    }],
                }

        client = QmtRpc(xtdata_client=FakeXtdata())
        frame = client.market_bars(["600000.SH"], "20240102", "20240102", period="tick")["600000.SH"]

        self.assertEqual(frame["last"].iloc[0], 10.1)
        self.assertEqual(frame["bid"].iloc[0], 10.0)
        self.assertEqual(frame["ask_volume"].iloc[0], 60)
        self.assertTrue(pd.isna(frame["close"].iloc[0]))

    def test_parse_targets_deduplicates_and_rejects_unknown_targets(self):
        self.assertEqual(parse_targets("duckdb,kdb,duckdb"), ["duckdb", "kdb"])
        with self.assertRaises(ValueError):
            parse_targets("duckdb,parquet")

    def test_fetch_batches_records_empty_symbol_without_losing_other_symbols(self):
        class FakeQmt:
            def market_bars(self, symbols, start_date, end_date, **kwargs):
                return {
                    symbols[0]: pd.DataFrame([{
                        "bar_time": pd.Timestamp("2024-01-02"), "open": 1, "high": 2,
                        "low": 0.5, "close": 1.5, "last": float("nan"), "volume": 10, "amount": 15,
                        "bid": float("nan"), "ask": float("nan"), "bid_volume": float("nan"), "ask_volume": float("nan"),
                    }]),
                    symbols[1]: pd.DataFrame(),
                }

        instruments = pd.DataFrame([
            {"symbol": "600000.SH", "market": "SH", "asset_type": "stock", "source_sectors": "沪深A股"},
            {"symbol": "159919.SZ", "market": "SZ", "asset_type": "etf", "source_sectors": "沪深ETF"},
        ])
        result = next(fetch_batches(FakeQmt(), instruments, "20240101", "20240103", batch_size=10, dividend_type="none"))

        self.assertEqual(len(result.bars), 1)
        self.assertEqual(result.bars.iloc[0]["symbol"], "600000.SH")
        self.assertEqual(result.errors[0]["symbol"], "159919.SZ")

    def test_empty_bar_batch_is_safe_to_partition(self):
        self.assertEqual(_partition_bars_by_asset_type(pd.DataFrame(), {"stock", "etf"}), {})


if __name__ == "__main__":
    unittest.main()
