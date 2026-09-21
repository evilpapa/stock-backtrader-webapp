"""QMT 全市场股票池服务测试。"""

import unittest

import pandas as pd

from src.utils.qmt_universe import QmtUniverseClient


class QmtUniverseClientTest(unittest.TestCase):
	def test_snapshot_normalizes_qmt_universe_metadata(self):
		"""验证板块、ST、合约、财务和日线数据会合成为统一快照。"""
		class FakeXtdata:
			def get_stock_list_in_sector(self, sector_name):
				return ["600001.SH", "600002.SH"]

			def get_instrument_detail(self, stock_code, iscomplete=True):
				return {
					"600001.SH": {"InstrumentName": "正常股", "OpenDate": 20200101, "ExpireDate": 99999999, "FloatVolume": 100_000_000},
					"600002.SH": {"InstrumentName": "ST 测试", "OpenDate": 20200101, "ExpireDate": 99999999, "FloatVolume": 50_000_000},
				}[stock_code]

			def get_his_st_data(self, stock_code):
				return {"600001.SH": [], "600002.SH": [{"start_date": "20230101", "end_date": None}]}[stock_code]

			def get_financial_data(self, **_params):
				return {
					"600001.SH": [{"float_share": 100_000_000}],
					"600002.SH": [{"float_share": 50_000_000}],
				}

			def get_market_data(self, **_params):
				return {
					"600001.SH": pd.DataFrame([{"time": "20240102", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000, "amount": 10000}]),
					"600002.SH": pd.DataFrame([{"time": "20240102", "open": 8, "high": 9, "low": 7, "close": 8, "volume": 0, "amount": 0}]),
				}

		client = QmtUniverseClient(xtdata_client=FakeXtdata())
		snapshot = client.snapshot("2024-01-02")
		stocks = snapshot.stocks.set_index("code")

		self.assertEqual(stocks.loc["600001.SH", "float_market_cap"], 10.0)
		self.assertEqual(stocks.loc["600001.SH", "listing_date"], pd.Timestamp("2020-01-01"))
		self.assertFalse(stocks.loc["600001.SH", "is_delisted"])
		self.assertFalse(stocks.loc["600001.SH", "is_st"])
		self.assertTrue(stocks.loc["600002.SH", "is_st"])
		self.assertTrue(stocks.loc["600002.SH", "is_suspended"])
		self.assertEqual(snapshot.eligible_codes(375, 5, 20), ["600001.SH"])

	def test_eligible_codes_excludes_new_st_suspended_delisted_and_non_main_board(self):
		"""基础池过滤应覆盖 qb/small2 的全部排除条件。"""
		from src.utils.qmt_universe import StockUniverseSnapshot
		frame = pd.DataFrame([
			{"code": "600001.SH", "name": "ok", "listing_date": "20200101", "is_st": False, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 10},
			{"code": "300001.SZ", "name": "gem", "listing_date": "20200101", "is_st": False, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 6},
			{"code": "600002.SH", "name": "new", "listing_date": "20240101", "is_st": False, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 7},
			{"code": "600003.SH", "name": "st", "listing_date": "20200101", "is_st": True, "is_suspended": False, "is_delisted": False, "float_shares": 1, "float_market_cap": 8},
		])
		snapshot = StockUniverseSnapshot(pd.Timestamp("2024-01-02"), frame)
		self.assertEqual(snapshot.eligible_codes(375, 5, 20), ["600001.SH"])


if __name__ == "__main__":
	unittest.main()
