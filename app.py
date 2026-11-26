import datetime
from functools import partial
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_echarts import st_pyecharts

from src.charts import draw_multi_line, draw_pro_kline, draw_result_bar, draw_weight_area
from src.frames import (
	SUMMARY_CARD_CSS,
	backtrader_selector_ui,
	cumulative_return_from_frame,
	market_data_selector_ui,
	market_data_source_ui,
	params_selector_ui,
	render_free_cash_flow_page,
	render_index_timing_page,
	render_intraday_all_factor_page,
	render_micro_cap_timing_page,
	render_mysterious_spiral_page,
	render_performance_summary,
	render_sector_rotation_dual_page,
	render_small_cap_page,
	render_summary_from_metric_row,
	render_turnover_stability_page,
	risk_control_ui,
)
from src.frames.asset_management import render_asset_management
from src.utils.etf_momentum_backtest import (
	BENCHMARK_NAME as ETF_BENCHMARK_NAME,
	DEFAULT_ASSETS as ETF_DEFAULT_ASSETS,
	DEFAULT_OUTPUT_DIR as ETF_OUTPUT_DIR,
	EtfMomentumFrames,
	load_etf_momentum_results,
	run_etf_momentum_backtest,
)
from src.utils.load import load_strategy
from src.utils.logs import logger
from src.utils.processing import BACKTRADER_METRIC_COLUMNS, gen_stock_df, run_backtrader
from src.utils.rotation_backtest import (
	ROTATION_SPECS,
	RotationFrames,
	RotationSpec,
	load_rotation_results,
	normalize_assets,
	run_rotation_backtest,
)
from src.strategy import QbEtfMomentumStrategy
from src.utils.schemas import StrategyBase
from src.utils.turtle_backtest import (
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

STRATEGY_LABELS = {
	"Ma": "Ma · 单均线",
	"MaCross": "MaCross · 双均线",
	"EtfMomentum": "EtfMomentum · ETF动量轮动",
	"QbEtfMomentum": "QbEtfMomentum · QB ETF周频动量",
	"LeadingRotation": "LeadingRotation · 龙头动量轮动",
	"SectorRotation": "SectorRotation · 行业ETF动量轮动",
	"Small2": "Small2 · 全市场小市值选股",
	"MysteriousSpiral": "MysteriousSpiral · 神秘螺旋月度轮动",
	"TurtleTrading": "TurtleTrading · 海龟交易",
	"SectorRotationDual": "SectorRotationDual · 双轮配置行业ETF",
	"FreeCashFlow": "FreeCashFlow · 增强型自由现金流",
	"MicroCapTimingPlus": "MicroCapTimingPlus · 微盘股择时增强",
	"TurnoverStability": "TurnoverStability · 量稳换手率(STR/SCR)",
	"IntradayAllFactor": "IntradayAllFactor · 高频46因子中证500",
	"IndexTiming": "IndexTiming · 指数择时(MA/RSRS)",
}


def render_strategy_result_frames(frames: EtfMomentumFrames | RotationFrames) -> None:
	"""渲染 ETF 动量和轮动策略共用的结果区。"""
	if not frames.metrics.empty:
		strategy_row = frames.metrics.iloc[0]
		strategy_name = str(strategy_row.get("策略", ""))
		render_summary_from_metric_row(strategy_row, cumulative_return_from_frame(frames.cumulative, strategy_name))

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
	# 启用风控的回测会额外输出风控统计与事件明细。
	risk_summary = getattr(frames, "risk_summary", None)
	if risk_summary is not None and not risk_summary.empty:
		optional_frames.append(("风控统计", risk_summary))
	risk_events = getattr(frames, "risk_events", None)
	if risk_events is not None and not risk_events.empty:
		optional_frames.append(("风控事件", risk_events))
	# 基础结果固定展示四个标签页，扩展结果按数据对象能力追加。
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


def render_etf_momentum_page(qb_strategy: bool = False) -> None:
	"""渲染标准或 qb ETF 动量策略的配置、回测触发和结果展示页面。"""
	strategy_name = "QB ETF Momentum" if qb_strategy else "ETF Momentum"
	output_dir = Path("examples") / ("qb_etf_momentum" if qb_strategy else "etf_momentum")
	st.subheader(strategy_name)
	st.sidebar.markdown(f"# {strategy_name} Config")
	data_source_params = market_data_source_ui("ETF")
	start_date = st.sidebar.date_input("ETF start date", datetime.date(2025, 1, 1))
	end_date = st.sidebar.date_input("ETF end date", datetime.datetime.today())
	initial_cash = st.sidebar.number_input("ETF start cash", min_value=0.0, value=100000.0, step=10000.0)
	if qb_strategy:
		period = st.sidebar.number_input("ROC period", min_value=1, value=5, step=1)
		rebalance_weekday = st.sidebar.number_input("rebalance weekday (1=Mon, 5=Fri)", min_value=1, max_value=5, value=1, step=1)
		top_n = st.sidebar.number_input("top N", min_value=1, value=5, step=1)
	else:
		momentum_window = st.sidebar.number_input("momentum window", min_value=1, value=20, step=1)
		rebalance_days = st.sidebar.number_input("rebalance days", min_value=1, value=5, step=1)
	benchmark_symbol = st.sidebar.text_input("benchmark symbol", value="510300")
	benchmark_name = st.sidebar.text_input("benchmark name", value=ETF_BENCHMARK_NAME)
	risk_config = risk_control_ui("ETF" if not qb_strategy else "QB")

	assets_df = st.data_editor(
		pd.DataFrame(ETF_DEFAULT_ASSETS),
		column_order=["symbol", "name"],
		num_rows="dynamic",
		use_container_width=True,
		key="qb_etf_momentum_assets" if qb_strategy else "etf_momentum_assets",
	)
	assets = normalize_assets(assets_df)

	if st.button(f"重新运行 {strategy_name} 回测", type="primary"):
		try:
			# 回测失败时回退到已有 CSV 结果，保证页面仍可展示历史数据。
			with st.spinner(f"正在运行 {strategy_name} 回测..."):
				frames = run_etf_momentum_backtest(
					assets=assets,
					benchmark_symbol=benchmark_symbol.strip(),
					benchmark_name=benchmark_name.strip() or ETF_BENCHMARK_NAME,
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					initial_cash=float(initial_cash),
					momentum_window=int(period) if qb_strategy else int(momentum_window),
					rebalance_days=1 if qb_strategy else int(rebalance_days),
					output_dir=output_dir,
					data_source_params=data_source_params,
					strategy_class=QbEtfMomentumStrategy if qb_strategy else None,
					strategy_params=(
						{
							"period": int(period),
							"rebalance_weekday": int(rebalance_weekday),
							"top_n": int(top_n),
						}
						if qb_strategy
						else None
					),
					risk_config=risk_config,
				)
			st.success(f"{strategy_name} 结果已更新: {output_dir}")
		except Exception as exc:
			logger.exception("%s backtest failed", strategy_name)
			st.error(f"{strategy_name} 回测失败: {exc}")
			frames = load_etf_momentum_results(output_dir)
	else:
		frames = load_etf_momentum_results(output_dir)

	if frames is None:
		st.info(f"未找到完整 {strategy_name} 结果，请点击重新回测生成 {output_dir} 下的 CSV。")
		return
	render_strategy_result_frames(frames)


def render_rotation_page(spec: RotationSpec) -> None:
	"""根据轮动策略规格渲染对应的配置和结果页面。"""
	st.subheader(spec.title)
	st.sidebar.markdown(f"# {spec.title} Config")
	data_source_params = market_data_source_ui(spec.key)
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
	risk_config = risk_control_ui(spec.key)

	assets_df = st.data_editor(
		pd.DataFrame(spec.assets),
		column_order=["symbol", "name"],
		num_rows="dynamic",
		use_container_width=True,
		key=f"{spec.key}_assets",
	)
	assets = normalize_assets(assets_df)

	if st.button(f"重新运行 {spec.title} 回测", type="primary"):
		try:
			# spec 中封装了不同轮动策略的默认参数和输出目录。
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
					data_source_params=data_source_params,
					risk_config=risk_config,
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
	"""渲染海龟交易策略的指标、图表和明细表。"""
	st.subheader("海龟交易结果")
	equity = frames.equity.copy()
	equity["date"] = pd.to_datetime(equity["date"])

	if not frames.metrics.empty:
		render_summary_from_metric_row(frames.metrics.iloc[0])

	# pyecharts 通用折线图要求日期列命名为 Date。
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
	"""渲染海龟交易策略配置、回测触发和结果展示页面。"""
	st.subheader("Turtle Trading")
	st.sidebar.markdown("# Turtle Trading Config")
	data_source_params = market_data_source_ui("Turtle")
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
			# 海龟策略参数来自侧边栏，提交前统一转换为回测函数需要的类型。
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
					data_source_params=data_source_params,
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
	"""渲染单标的 Backtrader 策略的数据选择、参数扫描和结果图表。"""
	market_data_params = market_data_selector_ui()
	bt_params = backtrader_selector_ui()
	if not market_data_params.symbol:
		return

	stock_df = gen_stock_df(market_data_params)
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

	logger.info("market data: {}", market_data_params.model_dump(exclude={"tushare_token"}))
	logger.info(f"backtrader: {bt_params}")
	# Backtrader 数据源使用英文 OHLCV 字段名，这里在入参前统一映射。
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
	par_df = run_backtrader(stock_df, strategy, bt_params, period=market_data_params.period)
	if par_df.empty:
		st.info("没有可展示的回测结果")
		return
	ranked = par_df.sort_values(["score", "return"], ascending=False, na_position="last")
	render_summary_from_metric_row(ranked.iloc[0])
	st.dataframe(ranked)
	chart_metrics = ["score", *BACKTRADER_METRIC_COLUMNS]
	bar = draw_result_bar(ranked[[*strategy.params, *chart_metrics]], n_scors=len(chart_metrics))
	st_pyecharts(bar, height="500px")


CUSTOM_STRATEGY_RENDERERS = {
	"EtfMomentum": render_etf_momentum_page,
	"QbEtfMomentum": partial(render_etf_momentum_page, qb_strategy=True),
	**{key: partial(render_rotation_page, spec) for key, spec in ROTATION_SPECS.items()},
	"TurtleTrading": render_turtle_page,
	"Small2": render_small_cap_page,
	"MysteriousSpiral": render_mysterious_spiral_page,
	"SectorRotationDual": render_sector_rotation_dual_page,
	"FreeCashFlow": render_free_cash_flow_page,
	"MicroCapTimingPlus": render_micro_cap_timing_page,
	"TurnoverStability": render_turnover_stability_page,
	"IntradayAllFactor": render_intraday_all_factor_page,
	"IndexTiming": render_index_timing_page,
}


def main():
	"""根据侧边栏选择分发到资产管理或策略回测。"""
	if st.sidebar.radio("页面", ("策略回测", "资产管理")) == "资产管理":
		render_asset_management()
		return
	name = st.sidebar.selectbox(
		"strategy",
		list(strategy_dict.keys()),
		format_func=lambda key: STRATEGY_LABELS.get(key, key),
	)
	renderer = CUSTOM_STRATEGY_RENDERERS.get(name)
	if renderer is not None:
		renderer()
		return
	render_single_symbol_strategy(name)


strategy_dict = load_strategy("src/config/strategy.yaml")

if __name__ == "__main__":
	main()

