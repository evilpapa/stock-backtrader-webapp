import datetime

import streamlit as st

from utils.schemas import BacktraderParams, DataParams


def data_selector_ui() -> DataParams:
	"""AKShare 数据参数

	:return: DataParams
	"""
	st.sidebar.markdown("# 数据配置")
	symbol = st.sidebar.text_input("股票代码", value="000001")
	period = st.sidebar.selectbox("周期", ("1d",), index=0)
	start_date = st.sidebar.date_input("开始日期", datetime.date(2010, 1, 1))
	start_date = start_date.strftime("%Y-%m-%d")
	end_date = st.sidebar.date_input("结束日期", datetime.datetime.today())
	end_date = end_date.strftime("%Y-%m-%d")
	dividend_type = st.sidebar.selectbox("复权方式", ("qfq", "hfq", "none"))
	return DataParams(
		symbol=symbol,
		period=period,
		start_date=start_date,
		end_date=end_date,
		dividend_type=dividend_type,
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
