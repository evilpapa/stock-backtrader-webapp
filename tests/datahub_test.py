"""DataHub 离线单元测试：不访问 Tushare/QMT。"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from src.datahub.exceptions import DataValidationError, TickerMappingError
from src.datahub.models import DataKind, DataRequest, DataResult
from src.datahub.normalizer import Normalizer
from src.datahub.providers.tushare import TushareProvider
from src.datahub.providers.xtquant import XtQuantProvider
from src.datahub.providers.local_cache import DuckDBCacheProvider
from src.datahub.realtime import RealtimeDataService
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.datahub.storage import MemoryCache, ParquetRepository, SQLiteRepository
from src.datahub.ticker import TickerMapper
from src.datahub.mock import MockProvider


class TickerMapperTest(unittest.TestCase):
    def setUp(self):
        self.mapper = TickerMapper({"market_data": {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBJ"}})

    def test_normalizes_markets_and_legacy_xtquant_aliases(self):
        cases = {
            "000001": "000001.SZ", "000001.XSHE": "000001.SZ", "600000.XSHG": "600000.SH",
            "300750.SZ": "300750.SZ", "688001.SH": "688001.SH", "430047.BJ": "430047.BJ",
            "510300.SH": "510300.SH", "000300.SZ": "000300.SZ",
        }
        for raw, expected in cases.items():
            self.assertEqual(self.mapper.normalize(raw), expected)
        self.assertEqual(self.mapper.to_xtquant("000001.SZ", "market_data"), "000001.XSHE")
        self.assertEqual(self.mapper.to_exchange("600000.XSHG"), "SH")

    def test_rejects_unknown_code_or_market(self):
        for raw in ("abc", "000001.XX", "12345.SZ", "000001.SH.EXTRA"):
            with self.assertRaises(TickerMappingError):
                self.mapper.normalize(raw)
        self.assertFalse(self.mapper.validate("bad"))


class NormalizerTest(unittest.TestCase):
    def setUp(self):
        self.request = DataRequest(symbols=("000001.SZ",), start="2024-01-01", end="2024-01-02")

    def test_tushare_units_time_semantics_and_deduplication(self):
        raw = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20240102", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 12, "amount": 34},
            {"ts_code": "000001.SZ", "trade_date": "20240102", "open": 10, "high": 11, "low": 9, "close": 10.6, "vol": 13, "amount": 35},
        ])
        result = Normalizer().normalize(DataResult(raw, "tushare", DataKind.DAILY), self.request)
        frame = result.data
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.loc[0, "volume"], 1300)
        self.assertEqual(frame.loc[0, "amount"], 35000)
        self.assertEqual(str(frame.loc[0, "datetime"].tz), "Asia/Shanghai")
        self.assertEqual(frame.attrs["timestamp_semantics"], "start")
        self.assertEqual(len(frame.attrs["data_version"]), 20)

    def test_rejects_invalid_ohlc(self):
        raw = pd.DataFrame([{"symbol": "000001.SZ", "datetime": "2024-01-02", "open": 10, "high": 8, "low": 9, "close": 10, "volume": 1, "amount": 10}])
        with self.assertRaises(DataValidationError):
            Normalizer().normalize(DataResult(raw, "mock", DataKind.DAILY), self.request)

    def test_financial_as_of_filters_future_announcements(self):
        request = DataRequest(symbols=("000001.SZ",), as_of="2024-04-01")
        raw = pd.DataFrame([
            {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "2024-03-30", "f_ann_date": "2024-03-30", "report_type": "1", "revenue": 1},
            {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "2024-04-02", "f_ann_date": "2024-04-02", "report_type": "1", "revenue": 2},
        ])
        frame = Normalizer().normalize(DataResult(raw, "tushare", DataKind.FINANCIAL), request).data
        self.assertEqual(frame["revenue"].tolist(), [1])


class ProviderTest(unittest.TestCase):
    def test_tushare_extension_stays_inside_provider_adapter(self):
        calls = []

        class FakePro:
            def index_daily(self, **kwargs):
                calls.append(kwargs)
                return pd.DataFrame({"ts_code": ["000300.SH"], "trade_date": ["20240102"], "close": [3500.0]})

        provider = TushareProvider(pro_client=FakePro())
        router = DataRouter({"tushare": provider}, {DataKind.INDEX_DAILY: {"providers": ("tushare",)}})
        service = MarketDataService(router)
        frame = service.query(
            DataKind.INDEX_DAILY,
            DataRequest(start="20240101", end="20240102", options={"ts_code": "000300.SH"}),
        )
        self.assertEqual(calls[0]["ts_code"], "000300.SH")
        self.assertEqual(frame.loc[0, "close"], 3500.0)
        self.assertEqual(frame.attrs["source"], "tushare")

    def test_tushare_adapter_uses_documented_endpoint_and_is_normalized_by_service(self):
        calls = []

        class FakePro:
            def daily(self, **kwargs):
                calls.append(("daily", kwargs))
                return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240102", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 10, "amount": 20}])

        provider = TushareProvider(pro_client=FakePro())
        result = provider.get_daily(DataRequest(symbols=("000001.SZ",), start="20240101", end="20240102"))
        self.assertEqual(calls[0][0], "daily")
        self.assertEqual(calls[0][1]["ts_code"], "000001.SZ")
        frame = Normalizer().normalize(result, DataRequest(symbols=("000001.SZ",))).data
        self.assertEqual(frame["volume"].iloc[0], 1000)
        self.assertEqual(frame["amount"].iloc[0], 20000)

    def test_tushare_daily_uses_fund_daily_for_etf(self):
        calls = []

        class FakePro:
            def fund_daily(self, **kwargs):
                calls.append(kwargs)
                return pd.DataFrame([{
                    "ts_code": "510300.SH", "trade_date": "20240102",
                    "open": 4.0, "high": 4.1, "low": 3.9, "close": 4.05,
                    "vol": 10, "amount": 20,
                }])

        provider = TushareProvider(pro_client=FakePro())
        result = provider.get_daily(DataRequest(
            symbols=("510300.SH",), start="20240101", end="20240102", adjust="none",
        ))
        self.assertEqual(calls[0]["ts_code"], "510300.SH")
        self.assertEqual(result.data.iloc[0]["ts_code"], "510300.SH")

    def test_xtquant_adapter_downloads_then_reads_ex_data(self):
        calls = []

        class FakeXt:
            def download_history_data2(self, **kwargs):
                calls.append(("download", kwargs))

            def get_market_data_ex(self, **kwargs):
                calls.append(("get", kwargs))
                return {"000001.XSHE": pd.DataFrame([{"time": 1704153600000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1000}])}

        provider = XtQuantProvider(xtdata_client=FakeXt(), ticker_mapper=TickerMapper({"market_data": {"SZ": "XSHE"}}))
        result = provider.get_daily(DataRequest(symbols=("000001.SZ",), start="20240101", end="20240102"))
        self.assertEqual(calls[0][0], "download")
        self.assertEqual(calls[1][0], "get")
        frame = Normalizer().normalize(result, DataRequest(symbols=("000001.SZ",))).data
        self.assertEqual(frame["symbol"].iloc[0], "000001.SZ")
        self.assertEqual(frame["amount"].iloc[0], 1000)

    def test_xtquant_adapter_accepts_official_field_dataframe_shape(self):
        class FakeXt:
            def get_market_data(self, **_kwargs):
                return {
                    field: pd.DataFrame([[value]], index=["000001.SZ"], columns=["20240102"])
                    for field, value in {"open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1000}.items()
                }

        provider = XtQuantProvider(xtdata_client=FakeXt())
        result = provider.get_daily(DataRequest(symbols=("000001.SZ",), options={"download": False}))
        frame = Normalizer().normalize(result, DataRequest(symbols=("000001.SZ",))).data
        self.assertEqual(frame["close"].iloc[0], 10.5)
        self.assertEqual(frame["symbol"].iloc[0], "000001.SZ")

    def test_duckdb_cache_provider_reads_normalized_daily_data(self):
        import duckdb

        with TemporaryDirectory() as directory:
            database = f"{directory}/etf.duckdb"
            connection = duckdb.connect(database)
            connection.execute("""
                CREATE TABLE daily_bars (
                    symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
                    low DOUBLE, close DOUBLE, volume DOUBLE, amount DOUBLE,
                    dividend_type VARCHAR, source VARCHAR
                )
            """)
            connection.execute(
                "INSERT INTO daily_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "510300.SH", "2025-01-02", 4, 4.1, 3.9, 4.05, 100, 400, "none", "bigqmt",
                    "510300.SH", "2025-01-03", 4.05, 4.2, 4, 4.1, 120, 490, "none", "bigqmt",
                ],
            )
            connection.close()

            service = MarketDataService(
                DataRouter(
                    {"cache": DuckDBCacheProvider(database)},
                    {DataKind.DAILY: {"providers": ("cache",)}},
                )
            )
            frame = service.get_daily(DataRequest(
                symbols=("510300",), start="2025-01-01", end="2025-01-05", adjust="none",
            ))
            service.close()
            self.assertEqual(len(frame), 2)
            self.assertEqual(frame["symbol"].tolist(), ["510300.SH", "510300.SH"])
            self.assertEqual(frame["source"].unique().tolist(), ["cache"])


class RouterAndServiceTest(unittest.TestCase):
    def test_falls_back_only_after_primary_unavailable(self):
        request = DataRequest(symbols=("000001.SZ",))
        frame = pd.DataFrame([{"symbol": "000001.SZ", "datetime": "2024-01-02", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3, "amount": 6}])
        primary = MockProvider("primary", {DataKind.DAILY: frame}, available=False)
        backup = MockProvider("backup", {DataKind.DAILY: frame})
        router = DataRouter({"primary": primary, "backup": backup}, {DataKind.DAILY: {"providers": ("primary", "backup")}})
        result = router.route(DataKind.DAILY, request)
        self.assertEqual(result.source, "backup")
        self.assertTrue(any(trace.status == "unavailable" for trace in router.traces))

    def test_service_cache_and_sqlite_persistence(self):
        request = DataRequest(symbols=("000001.SZ",))
        frame = pd.DataFrame([{"symbol": "000001.SZ", "datetime": "2024-01-02", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3, "amount": 6}])
        provider = MockProvider("mock", {DataKind.DAILY: frame})
        with TemporaryDirectory() as directory:
            repo = SQLiteRepository(f"{directory}/data.db")
            service = MarketDataService(DataRouter({"mock": provider}, {DataKind.DAILY: {"providers": ("mock",)}}), cache=MemoryCache(), repository=repo)
            first = service.get_daily(request, persist=True)
            second = service.get_daily(request)
            self.assertEqual(len(provider.calls), 1)
            self.assertTrue(first.equals(second))
            stored = repo.query(DataKind.DAILY, request)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.data.iloc[0]["symbol"], "000001.SZ")
            repo.close()

    def test_parquet_repository_round_trip_and_idempotent_update(self):
        request = DataRequest(symbols=("000001.SZ",))
        frame = pd.DataFrame([{"symbol": "000001.SZ", "datetime": pd.Timestamp("2024-01-02"), "close": 10.0}])
        with TemporaryDirectory() as directory:
            repo = ParquetRepository(directory)
            result = DataResult(frame, "mock", DataKind.DAILY)
            first_version = repo.save(result, request)
            repo.save(DataResult(frame.assign(close=11.0), "mock", DataKind.DAILY), request)
            stored = repo.query(DataKind.DAILY, request)
            self.assertIsNotNone(stored)
            self.assertEqual(len(stored.data), 1)
            self.assertEqual(stored.data["close"].iloc[0], 11.0)
            self.assertEqual(len(first_version), 20)


class RealtimeTest(unittest.TestCase):
    def test_shared_subscription_lifecycle(self):
        class FakeRealtime:
            def __init__(self):
                self.calls = []
                self.callbacks = {}
                self.next_id = 1

            def subscribe_quote(self, symbols, callback=None):
                ident = str(self.next_id); self.next_id += 1
                self.calls.append(("subscribe", tuple(symbols)))
                self.callbacks[ident] = callback
                return ident

            def unsubscribe_quote(self, ident): self.calls.append(("unsubscribe", ident))
            def subscribe_tick(self, symbols, callback=None): return self.subscribe_quote(symbols, callback)
            def unsubscribe_tick(self, ident): return self.unsubscribe_quote(ident)
            def register_callback(self, callback): pass
            def close(self): self.calls.append(("close",))

        provider = FakeRealtime()
        service = RealtimeDataService(provider)
        received = []
        first = service.subscribe_quote(["000001.SZ"], received.append)
        second = service.subscribe_quote(["000001.SZ"], received.append)
        self.assertEqual(len([call for call in provider.calls if call[0] == "subscribe"]), 1)
        callback = provider.callbacks["1"]
        callback({"000001.SZ": {"time": 1704153600000, "lastPrice": 10.0}})
        self.assertEqual(len(received), 2)
        service.unsubscribe(first)
        self.assertFalse(any(call[0] == "unsubscribe" for call in provider.calls))
        service.unsubscribe(second)
        self.assertTrue(any(call[0] == "unsubscribe" for call in provider.calls))


if __name__ == "__main__":
    unittest.main()
