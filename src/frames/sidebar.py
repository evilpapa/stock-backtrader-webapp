import datetime
import os

import streamlit as st

from src.utils.schemas import BacktraderParams, DataSourceParams, MarketDataParams


def market_data_source_ui(prefix: str = "") -> DataSourceParams:
	"""渲染 Tushare 行情数据源配置，并返回统一的数据源参数对象。"""
	label_prefix = f"{prefix} " if prefix else ""
	st.sidebar.markdown(f"# {label_prefix}Market Data Source")
	dividend_type = st.sidebar.selectbox(
		f"{label_prefix}dividend type",
		("front", "back", "none", "front_ratio", "back_ratio"),
	)
	tushare_token = st.sidebar.text_input(
		f"{label_prefix}Tushare token", value=os.getenv("TUSHARE_TOKEN", ""), type="password"
	)
	tushare_timeout = st.sidebar.number_input(
		f"{label_prefix}Tushare request timeout", min_value=1.0, max_value=120.0, value=30.0, step=1.0
	)
	return DataSourceParams(
		dividend_type=dividend_type,
		tushare_token=tushare_token,
		tushare_timeout=float(tushare_timeout),
	)


def market_data_selector_ui() -> MarketDataParams:
	"""渲染单标的行情参数，并返回 Tushare 所需的数据对象。"""
	st.sidebar.markdown("# Tushare Data Config")
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
	"""渲染 Backtrader 回测参数，并返回回测配置对象。"""
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
