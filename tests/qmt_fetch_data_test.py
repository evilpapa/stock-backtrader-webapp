import unittest
from datetime import date

import pandas as pd

from strategy.data_loader import fetch_qmt_strategy_data
from utils.fetch_data import fetch_etf_data, format_qmt_date, normalize_qmt_symbol


class FakeQmtDataClient:
	def __init__(self):
		self.calls = []

	def get_market_data_ex_df(self, symbol, **params):
		self.calls.append((symbol, params))
		return pd.DataFrame(
			[
				{
					"time": "20240102",
					"open": 1.0,
					"high": 1.2,
					"low": 0.9,
					"close": 1.1,
					"volume": 1000,
				},
				{
					"time": "20240103",
					"open": 1.1,
					"high": 1.3,
					"low": 1.0,
					"close": 1.2,
					"volume": 1200,
				},
			]
		)


class QmtFetchDataTest(unittest.TestCase):
	def test_normalizes_common_symbols_and_dates(self):
		self.assertEqual(normalize_qmt_symbol("513100.SS"), "513100.SH")
		self.assertEqual(normalize_qmt_symbol("510300.SH"), "510300.SH")
		self.assertEqual(normalize_qmt_symbol("000001"), "000001.SZ")
		self.assertEqual(normalize_qmt_symbol("600000"), "600000.SH")
		self.assertEqual(format_qmt_date("2024-01-02"), "20240102")
		self.assertEqual(format_qmt_date(date(2024, 1, 2)), "20240102")

	def test_fetch_etf_data_uses_qmt_client(self):
		client = FakeQmtDataClient()

		data = fetch_etf_data(
			["513100.SS"],
			"2024-01-01",
			"2024-01-31",
			strategy_name="test_qmt_fetch",
			client=client,
			use_cache=False,
		)

		self.assertIn("513100.SS", data)
		self.assertEqual(list(data["513100.SS"].columns), ["Open", "High", "Low", "Close", "Volume"])
		self.assertEqual(client.calls[0][0], "513100.SH")
		self.assertEqual(client.calls[0][1]["stock_code"], ["513100.SH"])
		self.assertEqual(client.calls[0][1]["start_time"], "20240101")
		self.assertEqual(client.calls[0][1]["end_time"], "20240131")
		self.assertFalse(client.calls[0][1]["subscribe"])

	def test_strategy_data_loader_delegates_to_qmt_fetch(self):
		client = FakeQmtDataClient()

		data = fetch_qmt_strategy_data(
			["510300.SH"],
			"2024-01-01",
			"2024-01-31",
			client=client,
			use_cache=False,
		)

		self.assertIn("510300.SH", data)
		self.assertEqual(client.calls[0][0], "510300.SH")


if __name__ == "__main__":
	unittest.main()
