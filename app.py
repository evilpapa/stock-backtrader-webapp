import datetime

import pandas as pd
import streamlit as st
from streamlit_echarts import st_pyecharts

from charts import draw_multi_line, draw_pro_kline, draw_result_bar, draw_weight_area
from frames import backtrader_selector_ui, params_selector_ui, xtdata_selector_ui
from utils.etf_momentum_backtest import (
	BENCHMARK_NAME as ETF_BENCHMARK_NAME,
	DEFAULT_ASSETS as ETF_DEFAULT_ASSETS,
	DEFAULT_OUTPUT_DIR as ETF_OUTPUT_DIR,
	EtfMomentumFrames,
	load_etf_momentum_results,
	normalize_assets as normalize_etf_assets,
	run_etf_momentum_backtest,
)
from utils.load import load_strategy
from utils.logs import logger
from utils.processing import gen_stock_df, run_backtrader
from utils.rotation_backtest import (
	ROTATION_SPECS,
	RotationFrames,
	RotationSpec,
	load_rotation_results,
	normalize_assets as normalize_rotation_assets,
	run_rotation_backtest,
)
from utils.schemas import StrategyBase
from utils.turtle_backtest import (
	DEFAULT_ALLOW_SHORT,
	DEFAULT_ATR_PERIOD,
	DEFAULT_ENTRY_PERIOD,
	DEFAULT_EXIT_PERIOD,
	DEFAULT_INITIAL_CASH,
	DEFAULT_LOT_SIZE,
	DEFAULT_MAX_UNITS,
	DEFAULT_OUTPUT_DIR as TURTLE_OUTPUT_DIR,
	DEFAULT_RISK_PCT,
	DEFAULT_START_DATE,
	DEFAULT_SYMBOL,
	TurtleFrames,
	load_turtle_results,
	run_turtle_backtest,
)

st.set_page_config(page_title="backtrader", page_icon=":chart_with_upwards_trend:", layout="wide")


def render_strategy_result_frames(frames: EtfMomentumFrames | RotationFrames) -> None:
	st.subheader("绩效指标")
	st.dataframe(frames.metrics, use_container_width=True)

	left, right = st.columns(2)
	with left:
		st_pyecharts(draw_multi_line(frames.cumulative, "累计净值"), height="420px")
	with right:
		st_pyecharts(draw_multi_line(frames.drawdown, "回撤"), height="420px")

	if not frames.weights.empty:
		st_pyecharts(draw_weight_area(frames.weights), height="460px")

	tab_names = ["每日收益", "累计收益", "回撤明细", "每日权重"]
	optional_frames = []
	if getattr(frames, "selection_frequency", None) is not None:
		optional_frames.append(("入选频率", frames.selection_frequency))
	if getattr(frames, "rebalance_details", None) is not None:
		optional_frames.append(("调仓明细", frames.rebalance_details))
	tabs = st.tabs(tab_names + [name for name, _ in optional_frames])
	with tabs[0]:
		st.dataframe(frames.returns, use_container_width=True)
	with tabs[1]:
		st.dataframe(frames.cumulative, use_container_width=True)
	with tabs[2]:
		st.dataframe(frames.drawdown, use_container_width=True)
	with tabs[3]:
		st.dataframe(frames.weights, use_container_width=True)
	for tab, (_, frame) in zip(tabs[4:], optional_frames):
		with tab:
			st.dataframe(frame, use_container_width=True)


def render_etf_momentum_page() -> None:
	st.subheader("ETF Momentum")
	st.sidebar.markdown("# ETF Momentum Config")
	start_date = st.sidebar.date_input("ETF start date", datetime.date(2025, 1, 1))
	end_date = st.sidebar.date_input("ETF end date", datetime.datetime.today())
	initial_cash = st.sidebar.number_input("ETF start cash", min_value=0.0, value=100000.0, step=10000.0)
	momentum_window = st.sidebar.number_input("momentum window", min_value=1, value=20, step=1)
	rebalance_days = st.sidebar.number_input("rebalance days", min_value=1, value=5, step=1)
	benchmark_symbol = st.sidebar.text_input("benchmark symbol", value="510300")
	benchmark_name = st.sidebar.text_input("benchmark name", value=ETF_BENCHMARK_NAME)

	assets_df = st.data_editor(
		pd.DataFrame(ETF_DEFAULT_ASSETS),
		column_order=["symbol", "name"],
		num_rows="dynamic",
		use_container_width=True,
		key="etf_momentum_assets",
	)
	assets = normalize_etf_assets(assets_df)

	if st.button("重新运行 ETF Momentum 回测", type="primary"):
		try:
			with st.spinner("正在运行 ETF Momentum 回测..."):
				frames = run_etf_momentum_backtest(
					assets=assets,
					benchmark_symbol=benchmark_symbol.strip(),
					benchmark_name=benchmark_name.strip() or ETF_BENCHMARK_NAME,
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					initial_cash=float(initial_cash),
					momentum_window=int(momentum_window),
					rebalance_days=int(rebalance_days),
				)
			st.success(f"ETF Momentum 结果已更新: {ETF_OUTPUT_DIR}")
		except Exception as exc:
			logger.exception("ETF Momentum backtest failed")
			st.error(f"ETF Momentum 回测失败: {exc}")
			frames = load_etf_momentum_results()
	else:
		frames = load_etf_momentum_results()

	if frames is None:
		st.info(f"未找到完整 ETF Momentum 结果，请点击重新回测生成 {ETF_OUTPUT_DIR} 下的 CSV。")
		return
	render_strategy_result_frames(frames)


def render_rotation_page(spec: RotationSpec) -> None:
	st.subheader(spec.title)
	st.sidebar.markdown(f"# {spec.title} Config")
	start_date = st.sidebar.date_input(
		f"{spec.key} start date",
		datetime.date.fromisoformat(spec.default_start_date),
	)
	end_date = st.sidebar.date_input(f"{spec.key} end date", datetime.datetime.today())
	initial_cash = st.sidebar.number_input(f"{spec.key} start cash", min_value=0.0, value=100000.0, step=10000.0)
	momentum_window = st.sidebar.number_input(
		f"{spec.key} momentum window",
		min_value=1,
		value=spec.default_momentum_window,
		step=1,
	)
	rebalance_days = st.sidebar.number_input(
		f"{spec.key} rebalance days",
		min_value=1,
		value=spec.default_rebalance_days,
		step=1,
	)
	top_l = st.sidebar.number_input(f"{spec.key} top L", min_value=1, value=spec.default_top_l, step=1)
	benchmark_symbol = st.sidebar.text_input(f"{spec.key} benchmark symbol", value=spec.benchmark_symbol)
	benchmark_name = st.sidebar.text_input(f"{spec.key} benchmark name", value=spec.benchmark_name)

	assets_df = st.data_editor(
		pd.DataFrame(spec.assets),
		column_order=["symbol", "name"],
		num_rows="dynamic",
		use_container_width=True,
		key=f"{spec.key}_assets",
	)
	assets = normalize_rotation_assets(assets_df)

	if st.button(f"重新运行 {spec.title} 回测", type="primary"):
		try:
			with st.spinner(f"正在运行 {spec.title} 回测..."):
				frames = run_rotation_backtest(
					spec=spec,
					assets=assets,
					benchmark_symbol=benchmark_symbol.strip(),
					benchmark_name=benchmark_name.strip() or spec.benchmark_name,
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					initial_cash=float(initial_cash),
					momentum_window=int(momentum_window),
					rebalance_days=int(rebalance_days),
					top_l=int(top_l),
				)
			st.success(f"{spec.title} 结果已更新: {spec.output_dir}")
		except Exception as exc:
			logger.exception(f"{spec.key} backtest failed")
			st.error(f"{spec.title} 回测失败: {exc}")
			frames = load_rotation_results(spec)
	else:
		frames = load_rotation_results(spec)

	if frames is None:
		st.info(f"未找到完整 {spec.title} 结果，请点击重新回测生成 {spec.output_dir} 下的 CSV。")
		return
	render_strategy_result_frames(frames)


def render_turtle_frames(frames: TurtleFrames) -> None:
	st.subheader("海龟交易结果")
	equity = frames.equity.copy()
	equity["date"] = pd.to_datetime(equity["date"])

	stats_cols = st.columns(4)
	start_value = equity["value"].iloc[0]
	end_value = equity["value"].iloc[-1]
	stats_cols[0].metric("期初权益", f"{start_value:,.2f}")
	stats_cols[1].metric("期末权益", f"{end_value:,.2f}")
	stats_cols[2].metric("总收益率", f"{(end_value / start_value - 1.0) * 100:.2f}%")
	stats_cols[3].metric("最大回撤", f"{equity['drawdown'].min() * 100:.2f}%")

	price_value = equity.rename(columns={"date": "Date", "close": "Close", "value": "Equity"})[
		["Date", "Close", "Equity"]
	]
	drawdown = equity.rename(columns={"date": "Date", "drawdown": "Drawdown"})[["Date", "Drawdown"]]
	position = equity.rename(columns={"date": "Date", "position": "Position"})[["Date", "Position"]]
	left, right = st.columns(2)
	with left:
		st_pyecharts(draw_multi_line(price_value, "价格与权益"), height="420px")
	with right:
		st_pyecharts(draw_multi_line(drawdown, "回撤"), height="420px")
	st_pyecharts(draw_multi_line(position, "持仓状态"), height="360px")

	tabs = st.tabs(["权益曲线", "交易日志"])
	with tabs[0]:
		st.dataframe(frames.equity, use_container_width=True)
	with tabs[1]:
		st.dataframe(frames.trades, use_container_width=True)


def render_turtle_page() -> None:
	st.subheader("Turtle Trading")
	st.sidebar.markdown("# Turtle Trading Config")
	symbol = st.sidebar.text_input("Turtle symbol", value=DEFAULT_SYMBOL)
	start_date = st.sidebar.date_input("Turtle start date", datetime.date.fromisoformat(DEFAULT_START_DATE))
	end_date = st.sidebar.date_input("Turtle end date", datetime.datetime.today())
	initial_cash = st.sidebar.number_input("Turtle start cash", min_value=0.0, value=DEFAULT_INITIAL_CASH, step=10000.0)
	entry_period = st.sidebar.number_input("entry period", min_value=1, value=DEFAULT_ENTRY_PERIOD, step=1)
	exit_period = st.sidebar.number_input("exit period", min_value=1, value=DEFAULT_EXIT_PERIOD, step=1)
	atr_period = st.sidebar.number_input("ATR period", min_value=1, value=DEFAULT_ATR_PERIOD, step=1)
	max_units = st.sidebar.number_input("max units", min_value=1, value=DEFAULT_MAX_UNITS, step=1)
	risk_pct = st.sidebar.number_input("risk pct", min_value=0.0, max_value=1.0, value=DEFAULT_RISK_PCT, step=0.001, format="%.3f")
	lot_size = st.sidebar.number_input("lot size", min_value=1, value=DEFAULT_LOT_SIZE, step=1)
	allow_short = st.sidebar.checkbox("allow short", value=DEFAULT_ALLOW_SHORT)

	if st.button("重新运行 Turtle Trading 回测", type="primary"):
		try:
			with st.spinner("正在运行 Turtle Trading 回测..."):
				frames = run_turtle_backtest(
					symbol=symbol.strip(),
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					entry_period=int(entry_period),
					exit_period=int(exit_period),
					atr_period=int(atr_period),
					max_units=int(max_units),
					risk_pct=float(risk_pct),
					lot_size=int(lot_size),
					initial_cash=float(initial_cash),
					allow_short=bool(allow_short),
				)
			st.success(f"Turtle Trading 结果已更新: {TURTLE_OUTPUT_DIR}")
		except Exception as exc:
			logger.exception("Turtle Trading backtest failed")
			st.error(f"Turtle Trading 回测失败: {exc}")
			frames = load_turtle_results()
	else:
		frames = load_turtle_results()

	if frames is None:
		st.info(f"未找到完整 Turtle Trading 结果，请点击重新回测生成 {TURTLE_OUTPUT_DIR} 下的 CSV。")
		return
	render_turtle_frames(frames)


def render_single_symbol_strategy(name: str) -> None:
	xtdata_params = xtdata_selector_ui()
	bt_params = backtrader_selector_ui()
	if not xtdata_params.symbol:
		return

	stock_df = gen_stock_df(xtdata_params)
	if stock_df.empty:
		st.error("Get stock data failed!")
		return

	st.subheader("K线")
	kline = draw_pro_kline(stock_df)
	st_pyecharts(kline, height="500px")

	st.subheader("策略")
	submitted, params = params_selector_ui(strategy_dict[name])
	if not submitted:
		return

	logger.info(f"xtdata: {xtdata_params}")
	logger.info(f"backtrader: {bt_params}")
	stock_df = stock_df.rename(
		columns={
			"日期": "date",
			"开盘": "open",
			"收盘": "close",
			"最高": "high",
			"最低": "low",
			"成交量": "volume",
		}
	)
	strategy = StrategyBase(name=name, params=params)
	par_df = run_backtrader(stock_df, strategy, bt_params)
	st.dataframe(par_df.style.highlight_max(subset=par_df.columns[-3:]))
	bar = draw_result_bar(par_df)
	st_pyecharts(bar, height="500px")


def main():
	name = st.sidebar.selectbox("strategy", list(strategy_dict.keys()))
	if name == "EtfMomentum":
		render_etf_momentum_page()
		return
	if name in ROTATION_SPECS:
		render_rotation_page(ROTATION_SPECS[name])
		return
	if name == "TurtleTrading":
		render_turtle_page()
		return
	render_single_symbol_strategy(name)


strategy_dict = load_strategy("./config/strategy.yaml")

if __name__ == "__main__":
	main()
