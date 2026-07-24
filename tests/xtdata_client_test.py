import unittest

import pandas as pd

from utils.xtdata_client import (
    DEFAULT_OHLCV_FIELDS,
    fetch_history_ohlcv,
    to_chinese_ohlcv,
    to_title_case_ohlcv,
)


class AkShareClientTest(unittest.TestCase):
    def test_fetch_stock_history_returns_ohlcv_columns(self):
        """测试股票数据获取返回标准 OHLCV 列。"""
        df = fetch_history_ohlcv(
            "000001",
            "2024-01-02",
            "2024-01-05",
            dividend_type="front",
        )

        self.assertFalse(df.empty)
        expected = ["date", "open", "high", "low", "close", "volume"]
        self.assertEqual(df.columns.tolist(), expected)
        self.assertTrue(all(col in df.columns for col in expected))
        self.assertGreater(len(df), 0)

    def test_fetch_etf_history_returns_ohlcv_columns(self):
        """测试 ETF 数据获取返回标准 OHLCV 列。"""
        df = fetch_history_ohlcv(
            "510300",
            "2024-01-02",
            "2024-01-05",
            dividend_type="front",
        )

        self.assertFalse(df.empty)
        expected = ["date", "open", "high", "low", "close", "volume"]
        self.assertEqual(df.columns.tolist(), expected)
        self.assertGreater(len(df), 0)

    def test_fetch_with_sz_suffix_works(self):
        """测试带 .SZ 后缀的代码也能正常工作。"""
        df = fetch_history_ohlcv(
            "000001.SZ",
            "2024-01-02",
            "2024-01-05",
        )
        self.assertFalse(df.empty)
        self.assertIn("close", df.columns)

    def test_to_chinese_ohlcv_keeps_app_column_contract(self):
        """测试中文列名转换保持与 Streamlit 界面兼容。"""
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

        result = to_chinese_ohlcv(frame)
        self.assertEqual(
            result.columns.tolist(),
            ["日期", "开盘", "收盘", "最高", "最低", "成交量"],
        )

    def test_to_title_case_ohlcv_returns_backtrader_columns(self):
        """测试 Backtrader 格式列名转换。"""
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

        result = to_title_case_ohlcv(frame)
        self.assertEqual(
            result.columns.tolist(),
            ["Open", "High", "Low", "Close", "Volume"],
        )


if __name__ == "__main__":
    unittest.main()
