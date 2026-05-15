"""Strategy-side data loading helpers backed by the local QMT data service."""

from __future__ import annotations

from utils.fetch_data import fetch_etf_data, format_qmt_date, normalize_qmt_symbol
from utils.qmt_data_client import QmtDataClient


def fetch_qmt_strategy_data(
	symbols,
	start_date,
	end_date,
	strategy_name=None,
	client: QmtDataClient | None = None,
	base_url="http://127.0.0.1:8765",
	token=None,
	period="1d",
	dividend_type="front",
	fields=None,
	use_cache=True,
):
	"""Fetch OHLCV data for strategy backtests through QmtDataClient."""
	return fetch_etf_data(
		symbols=symbols,
		start_date=start_date,
		end_date=end_date,
		strategy_name=strategy_name,
		client=client,
		base_url=base_url,
		token=token,
		period=period,
		dividend_type=dividend_type,
		fields=fields,
		use_cache=use_cache,
	)
