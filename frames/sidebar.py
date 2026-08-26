import datetime

import streamlit as st

from utils.schemas import BacktraderParams, DataSourceParams, XtDataParams


def market_data_source_ui(prefix: str = "") -> DataSourceParams:
	label_prefix = f"{prefix} " if prefix else ""
	st.sidebar.markdown(f"# {label_prefix}Market Data Source")
	data_source = st.sidebar.selectbox(
		f"{label_prefix}data source",
		("xtdata", "qmt_proxy"),
	)
	dividend_type = st.sidebar.selectbox(
		f"{label_prefix}dividend type",
		("front", "back", "none", "front_ratio", "back_ratio"),
	)
	qmt_base_url = "http://127.0.0.1:10086"
	qmt_token = "123456789"
	qmt_timeout = 10.0
	if data_source == "qmt_proxy":
		qmt_base_url = st.sidebar.text_input(f"{label_prefix}QMT proxy url", value=qmt_base_url)
		qmt_token = st.sidebar.text_input(f"{label_prefix}QMT token", value=qmt_token, type="password")
		qmt_timeout = st.sidebar.number_input(
			f"{label_prefix}QMT timeout",
			min_value=1.0,
			max_value=60.0,
			value=qmt_timeout,
			step=1.0,
		)
	return DataSourceParams(
		data_source=data_source,
		dividend_type=dividend_type,
		qmt_base_url=qmt_base_url,
		qmt_token=qmt_token,
		qmt_timeout=float(qmt_timeout),
	)


def xtdata_selector_ui() -> XtDataParams:
	"""xtdata params

	:return: XtDataParams
	"""
	st.sidebar.markdown("# XtData Config")
	symbol = st.sidebar.text_input("symbol", value="000001.SZ")
	period = st.sidebar.selectbox("period", ("1d", "1w", "1mon"))
	start_date = st.sidebar.date_input("start date", datetime.date(2010, 1, 1))
	start_date = start_date.strftime("%Y%m%d")
	end_date = st.sidebar.date_input("end date", datetime.datetime.today())
	end_date = end_date.strftime("%Y%m%d")
	data_source = market_data_source_ui()
	return XtDataParams(
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
