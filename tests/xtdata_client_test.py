import unittest

import pandas as pd

from utils.xtdata_client import fetch_history_ohlcv, normalize_dividend_type, normalize_xt_symbol, to_chinese_ohlcv


class FakeXtData:
    def __init__(self):
        self.download_calls = []
        self.market_data_calls = []

    def download_history_data(self, stock_code, period, start_time, end_time):
        self.download_calls.append((stock_code, period, start_time, end_time))

    def get_market_data(self, **kwargs):
        self.market_data_calls.append(kwargs)
        columns = ["20240102", "20240103"]
        index = ["000001.SZ"]
        return {
            "open": pd.DataFrame([[10.0, 10.5]], index=index, columns=columns),
            "high": pd.DataFrame([[11.0, 11.5]], index=index, columns=columns),
            "low": pd.DataFrame([[9.5, 10.1]], index=index, columns=columns),
            "close": pd.DataFrame([[10.8, 11.2]], index=index, columns=columns),
            "volume": pd.DataFrame([[1000, 1200]], index=index, columns=columns),
        }


class XtDataClientTest(unittest.TestCase):
    def test_fetch_history_ohlcv_downloads_and_converts_xtdata_shape(self):
        xtdata = FakeXtData()

        frame = fetch_history_ohlcv(
            "000001",
            "2024-01-02",
            "2024-01-03",
            dividend_type="qfq",
            xtdata_module=xtdata,
        )

        self.assertEqual(xtdata.download_calls, [("000001.SZ", "1d", "20240102", "20240103")])
        self.assertEqual(xtdata.market_data_calls[0]["dividend_type"], "front")
        self.assertEqual(frame.columns.tolist(), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(frame["close"].tolist(), [10.8, 11.2])

    def test_to_chinese_ohlcv_keeps_app_column_contract(self):
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-02"]),
                "open": [10],
                "high": [11],
                "low": [9],
                "close": [10.5],
                "volume": [1000],
            }
        )

        self.assertEqual(to_chinese_ohlcv(frame).columns.tolist(), ["日期", "开盘", "收盘", "最高", "最低", "成交量"])

    def test_normalizers(self):
        self.assertEqual(normalize_xt_symbol("600000"), "600000.SH")
        self.assertEqual(normalize_xt_symbol("000001"), "000001.SZ")
        self.assertEqual(normalize_xt_symbol("600000.ss"), "600000.SH")
        self.assertEqual(normalize_dividend_type("hfq"), "back")


if __name__ == "__main__":
    unittest.main()
