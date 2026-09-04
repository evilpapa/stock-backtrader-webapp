import datetime
import os

import streamlit as st

from utils.schemas import BacktraderParams, DataSourceParams, MarketDataParams


def market_data_source_ui(prefix: str = "") -> DataSourceParams:
	label_prefix = f"{prefix} " if prefix else ""
	st.sidebar.markdown(f"# {label_prefix}Market Data Source")
	dividend_type = st.sidebar.selectbox(
		f"{label_prefix}dividend type",
		("front", "back", "none", "front_ratio", "back_ratio"),
	)
	bigqmt_account_id = st.sidebar.text_input(
		f"{label_prefix}Big QMT account ID", value=os.getenv("BIGQMT_ACCOUNT_ID", "")
	)
	bigqmt_timeout = st.sidebar.number_input(
		f"{label_prefix}Big QMT RPC timeout", min_value=1.0, max_value=60.0, value=10.0, step=1.0
	)
	return DataSourceParams(
		dividend_type=dividend_type,
		bigqmt_account_id=bigqmt_account_id,
		bigqmt_timeout=float(bigqmt_timeout),
	)


def market_data_selector_ui() -> MarketDataParams:
	"""Big QMT RPC market-data parameters.

	:return: MarketDataParams
	"""
	st.sidebar.markdown("# Big QMT Data Config")
	symbol = st.sidebar.text_input("symbol", value="000001.SZ")
	period = st.sidebar.selectbox("period", ("1d", "1w", "1mon"))
	start_date = st.sidebar.date_input("start date", datetime.date(2010, 1, 1))
	start_date = start_date.strftime("%Y%m%d")
	end_date = st.sidebar.date_input("end date", datetime.datetime.today())
	end_date = end_date.strftime("%Y%m%d")
	data_source = market_data_source_ui()
	return MarketDataParams(
		symbol=symbol,
		period=period,
		start_date=start_date,
		end_date=end_date,
		**data_source.model_dump(),
	)


def backtrader_selector_ui() -> BacktraderParams:
	"""backtrader params

	:return: BacktraderParams
	"""
	st.sidebar.markdown("# BackTrader Config")
	start_date = st.sidebar.date_input("backtrader start date", datetime.date(2000, 1, 1))
	end_date = st.sidebar.date_input("backtrader end date", datetime.datetime.today())
	start_cash = st.sidebar.number_input("start cash", min_value=0, value=100000, step=10000)
	commission_fee = st.sidebar.number_input("commission fee", min_value=0.0, max_value=1.0, value=0.001, step=0.0001)
	stake = st.sidebar.number_input("stake", min_value=0, value=100, step=10)
	return BacktraderParams(
		start_date=start_date,
		end_date=end_date,
		start_cash=start_cash,
		commission_fee=commission_fee,
		stake=stake,
	)
