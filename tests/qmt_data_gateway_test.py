import json
import unittest
from datetime import datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from qmt.data_adapter import QmtDataAdapter, QmtDataAdapterError
from qmt.data_gateway import normalize_qmt_value, start_qmt_data_service, stop_qmt_data_service
from utils.qmt_data_client import QmtDataClient, to_backtrader_ohlcv


class FakeContextInfo:
    def __init__(self):
        self.calls = []
        self.universe = []

    def set_universe(self, stock_code):
        self.calls.append(("set_universe", stock_code))
        self.universe = list(stock_code)

    def get_history_data(self, length, period, field, dividend_type=0, skip_paused=True):
        self.calls.append(
            (
                "get_history_data",
                length,
                period,
                field,
                dividend_type,
                skip_paused,
            )
        )
        return {code: [1.0, 2.0] for code in self.universe}

    def get_market_data(
        self,
        fields,
        stock_code=None,
        start_time="",
        end_time="",
        skip_paused=True,
        period="1d",
        dividend_type="none",
        count=-1,
    ):
        self.calls.append(
            (
                "get_market_data",
                fields,
                stock_code,
                start_time,
                end_time,
                skip_paused,
                period,
                dividend_type,
                count,
            )
        )
        return pd.Series({"close": np.float64(10.5), "open": np.float64(10.0)})

    def get_market_data_ex(
        self,
        fields=None,
        stock_code=None,
        period="follow",
        start_time="",
        end_time="",
        count=-1,
        dividend_type="follow",
        fill_data=True,
        subscribe=True,
    ):
        self.calls.append(
            (
                "get_market_data_ex",
                fields,
                stock_code,
                period,
                start_time,
                end_time,
                count,
                dividend_type,
                fill_data,
                subscribe,
            )
        )
        return {
            code: pd.DataFrame(
                [
                    {"open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000},
                    {"open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 1200},
                ],
                index=pd.Index(["20240102", "20240103"], name="time"),
            )
            for code in stock_code
        }

    def get_full_tick(self, stock_code=None):
        self.calls.append(("get_full_tick", stock_code))
        return {code: {"lastPrice": 10.5, "volume": 100} for code in stock_code}

    def get_local_data(self, stock_code, start_time="", end_time="", period="1d", divid_type="none", count=-1):
        self.calls.append(("get_local_data", stock_code, start_time, end_time, period, divid_type, count))
        return {"20240102": {"open": 1.0, "close": 1.1}}


class QmtDataAdapterTest(unittest.TestCase):
    def test_rejects_unknown_method_and_params(self):
        adapter = QmtDataAdapter(FakeContextInfo())

        with self.assertRaises(QmtDataAdapterError):
            adapter.call("passorder", {})

        with self.assertRaises(QmtDataAdapterError):
            adapter.call("get_market_data_ex", {"fields": ["close"], "danger": True})

    def test_history_data_can_set_universe_before_call(self):
        context = FakeContextInfo()
        adapter = QmtDataAdapter(context)

        result = adapter.call(
            "get_history_data",
            {
                "stock_code": ["510300.SH"],
                "len": 2,
                "period": "1d",
                "field": "close",
            },
        )

        self.assertEqual(result, {"510300.SH": [1.0, 2.0]})
        self.assertEqual(context.calls[0], ("set_universe", ["510300.SH"]))
        self.assertEqual(context.calls[1][0], "get_history_data")


class QmtSerializationTest(unittest.TestCase):
    def test_normalizes_dataframe_series_numpy_and_nan(self):
        frame = pd.DataFrame(
            {"time": ["existing", "existing"], "close": [np.float64(1.1), np.nan]},
            index=pd.Index([datetime(2024, 1, 2), datetime(2024, 1, 3)], name="time"),
        )
        series = pd.Series({"close": np.float64(1.2), "bad": np.nan})

        normalized = normalize_qmt_value({"frame": frame, "series": series})

        self.assertEqual(normalized["frame"]["type"], "dataframe")
        self.assertEqual(normalized["frame"]["columns"][0], "time_1")
        self.assertEqual(normalized["frame"]["records"][0]["time_1"], "2024-01-02T00:00:00")
        self.assertEqual(normalized["frame"]["records"][0]["close"], 1.1)
        self.assertIsNone(normalized["frame"]["records"][1]["close"])
        self.assertEqual(normalized["series"]["type"], "series")
        self.assertIsNone(normalized["series"]["data"]["bad"])


class QmtDataServiceTest(unittest.TestCase):
    def tearDown(self):
        stop_qmt_data_service()

    def test_market_data_ex_endpoint_and_client_dataframe(self):
        status = start_qmt_data_service(FakeContextInfo(), port=0, token="secret")
        client = QmtDataClient("http://{0}:{1}".format(status["host"], status["port"]), token="secret")

        health = client.health()
        self.assertTrue(health["context_registered"])
        self.assertTrue(health["auth_required"])

        frame = client.get_market_data_ex_df(
            "510300.SH",
            fields=["open", "high", "low", "close", "volume"],
            stock_code=["510300.SH"],
            period="1d",
            count=2,
            dividend_type="front",
            subscribe=False,
        )
        ohlcv = to_backtrader_ohlcv(frame)

        self.assertEqual(list(ohlcv.columns), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(float(ohlcv.iloc[0]["close"]), 1.1)

    def test_rejects_missing_auth_and_unknown_params(self):
        status = start_qmt_data_service(FakeContextInfo(), port=0, token="secret")
        url = "http://{0}:{1}/v1/market-data-ex".format(status["host"], status["port"])

        with self.assertRaises(HTTPError) as auth_error:
            urlopen(Request(url, data=b"{}", method="POST"), timeout=5)
        self.assertEqual(auth_error.exception.code, 401)

        request = Request(
            url,
            data=json.dumps({"fields": ["close"], "unexpected": True}).encode("utf-8"),
            headers={
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as param_error:
            urlopen(request, timeout=5)
        self.assertEqual(param_error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
