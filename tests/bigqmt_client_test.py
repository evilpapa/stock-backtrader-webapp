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

    def test_fetch_history_uses_bigqmt_rpc_contract(self):
        """验证历史行情接口按 Big QMT RPC 协议组装请求参数。"""
        calls = []

        def fake_rpc(client, account_id, method, params, timeout_seconds):
            """记录 RPC 调用参数，并返回最小可解析的行情载荷。"""
            calls.append((client, account_id, method, params, timeout_seconds))
            return {
                "ok": True,
                "data": {
                    "__bigqmt_type__": "DataFrame",
                    "records": [
                        {"time": "20240102", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8, "volume": 1000}
                    ],
                },
            }

        client = object()
        frame = fetch_history_ohlcv(
            "000001",
            pd.Timestamp("2024-01-02"),
            "2024-01-03",
            dividend_type="qfq",
            account_id="account-1",
            timeout=3.0,
            redis_client=client,
            rpc_call=fake_rpc,
        )

        called_client, account_id, method, params, timeout = calls[0]
        self.assertIs(called_client, client)
        self.assertEqual(account_id, "account-1")
        self.assertEqual(method, "get_market_data_ex")
        self.assertEqual(params["stock_list"], ["000001.SZ"])
        self.assertEqual(params["field_list"], ["open", "high", "low", "close", "volume"])
        self.assertEqual(params["start_time"], "20240102")
        self.assertEqual(params["dividend_type"], "front")
        self.assertEqual(timeout, 3.0)
        self.assertEqual(frame["close"].tolist(), [10.8])


if __name__ == "__main__":
    unittest.main()
