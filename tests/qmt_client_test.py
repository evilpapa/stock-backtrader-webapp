import json
import unittest

import pandas as pd

from utils.qmt_client import fetch_history_ohlcv, market_data_payload_to_ohlcv


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class QmtClientTest(unittest.TestCase):
    def test_normalizes_dataframe_to_dict_field_payload(self):
        payload = {
            "open": {"20240102": 10.0, "20240103": 10.5},
            "high": {"20240102": 11.0, "20240103": 11.5},
            "low": {"20240102": 9.5, "20240103": 10.1},
            "close": {"20240102": 10.8, "20240103": 11.2},
            "volume": {"20240102": 1000, "20240103": 1200},
        }

        frame = market_data_payload_to_ohlcv(payload, "000001.SZ")

        self.assertEqual(frame.columns.tolist(), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(frame["date"].dt.strftime("%Y%m%d").tolist(), ["20240102", "20240103"])
        self.assertEqual(frame["close"].tolist(), [10.8, 11.2])

    def test_normalizes_index_orient_payload(self):
        payload = {
            "20240102": {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8, "volume": 1000},
            "20240103": {"open": 10.5, "high": 11.5, "low": 10.1, "close": 11.2, "volume": 1200},
        }

        frame = market_data_payload_to_ohlcv(payload, "000001.SZ")

        self.assertEqual(frame["date"].dt.strftime("%Y%m%d").tolist(), ["20240102", "20240103"])
        self.assertEqual(frame["open"].tolist(), [10.0, 10.5])

    def test_normalizes_get_market_data_ex_payload(self):
        payload = {
            "000001.SZ": {
                "20240102": {"open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8, "volume": 1000},
                "20240103": {"open": 10.5, "high": 11.5, "low": 10.1, "close": 11.2, "volume": 1200},
            }
        }

        frame = market_data_payload_to_ohlcv(payload, "000001.SZ")

        self.assertEqual(frame["date"].dt.strftime("%Y%m%d").tolist(), ["20240102", "20240103"])
        self.assertEqual(frame["close"].tolist(), [10.8, 11.2])

    def test_fetch_history_posts_qmt_api_request_and_normalizes(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append((req, timeout))
            return FakeHttpResponse(
                {
                    "data": {
                        "open": {"20240102": 10.0},
                        "high": {"20240102": 11.0},
                        "low": {"20240102": 9.5},
                        "close": {"20240102": 10.8},
                        "volume": {"20240102": 1000},
                    }
                }
            )

        frame = fetch_history_ohlcv(
            "000001",
            pd.Timestamp("2024-01-02"),
            "2024-01-03",
            dividend_type="qfq",
            base_url="http://127.0.0.1:10086/",
            token="secret",
            timeout=3.0,
            urlopen_func=fake_urlopen,
        )

        req, timeout = calls[0]
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(req.full_url, "http://127.0.0.1:10086/api/data/market_data")
        self.assertEqual(req.headers["X-token"], "secret")
        self.assertEqual(timeout, 3.0)
        self.assertEqual(body["stock_code"], "000001.SZ")
        self.assertEqual(body["fields"], "open,high,low,close,volume")
        self.assertEqual(body["start_time"], "20240102")
        self.assertEqual(body["dividend_type"], "front")
        self.assertEqual(frame["close"].tolist(), [10.8])


if __name__ == "__main__":
    unittest.main()
