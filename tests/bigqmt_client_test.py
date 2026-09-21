import unittest

import pandas as pd

from src.utils.bigqmt_client import fetch_history_ohlcv, market_data_payload_to_ohlcv


class BigQmtClientTest(unittest.TestCase):
    """Big QMT 行情客户端转换与 RPC 参数组装测试。"""

    def test_normalizes_bigqmt_dataframe_payload(self):
        """验证 Big QMT DataFrame 载荷会被规范化为 OHLCV 表。"""
        payload = {
            "__bigqmt_type__": "DataFrame",
            "records": [
                {"time": "20240102", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8, "volume": 1000},
                {"time": "20240103", "open": 10.5, "high": 11.5, "low": 10.1, "close": 11.2, "volume": 1200},
            ],
        }

        frame = market_data_payload_to_ohlcv(payload, "000001.SZ")

        self.assertEqual(frame.columns.tolist(), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(frame["date"].dt.strftime("%Y%m%d").tolist(), ["20240102", "20240103"])
        self.assertEqual(frame["close"].tolist(), [10.8, 11.2])

    def test_fetch_history_uses_native_xtdata_contract(self):
        """验证历史行情接口按原生 xtdata 行情接口组装参数。"""
        calls = []

        class FakeXtdata:
            def get_market_data_ex(self, **params):
                calls.append(params)
                return {"000001.SZ": pd.DataFrame([{
                    "time": "20240102", "open": 10.0, "high": 11.0,
                    "low": 9.5, "close": 10.8, "volume": 1000,
                }])}

        frame = fetch_history_ohlcv(
            "000001",
            pd.Timestamp("2024-01-02"),
            "2024-01-03",
            dividend_type="qfq",
            timeout=3.0,
            xtdata_client=FakeXtdata(),
        )

        params = calls[0]
        self.assertEqual(params["stock_list"], ["000001.SZ"])
        self.assertEqual(params["field_list"], ["open", "high", "low", "close", "volume"])
        self.assertEqual(params["start_time"], "20240102")
        self.assertEqual(params["dividend_type"], "front")
        self.assertNotIn("timeout_seconds", params)
        self.assertEqual(frame["close"].tolist(), [10.8])

    def test_parses_native_xtdata_field_frames(self):
        payload = {
            field: pd.DataFrame([[value]], index=["000001.SZ"], columns=["20240102"])
            for field, value in {
                "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8, "volume": 1000,
            }.items()
        }

        frame = market_data_payload_to_ohlcv(payload, "000001.SZ")

        self.assertEqual(frame["date"].dt.strftime("%Y%m%d").tolist(), ["20240102"])
        self.assertEqual(frame["close"].tolist(), [10.8])

    def test_normalizes_12_digit_millisecond_timestamps(self):
        payload = {
            "__bigqmt_type__": "DataFrame",
            "records": {
                "time": [663004800000],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.8],
                "volume": [1000],
            },
        }

        frame = market_data_payload_to_ohlcv(payload, "000001.SZ")

        self.assertEqual(frame["date"].iloc[0], pd.Timestamp("1991-01-04 16:00:00"))


if __name__ == "__main__":
    unittest.main()
