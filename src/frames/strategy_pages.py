"""未内置于 app.py 的各类策略 Streamlit 页面渲染函数。"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_echarts import st_pyecharts

from src.charts import draw_multi_line, draw_weight_area
from src.frames.risk import risk_control_ui
from src.frames.sidebar import market_data_source_ui
from src.frames.summary import cumulative_return_from_frame, render_summary_from_metric_row
from src.utils.logs import logger
from src.utils.mysterious_spiral_backtest import (
	DEFAULT_ASSETS as MYSTERIOUS_DEFAULT_ASSETS,
	DEFAULT_END_DATE as MYSTERIOUS_END_DATE,
	DEFAULT_INITIAL_CASH as MYSTERIOUS_INITIAL_CASH,
	DEFAULT_OUTPUT_DIR as MYSTERIOUS_OUTPUT_DIR,
	DEFAULT_RPS_WINDOW,
	DEFAULT_START_DATE as MYSTERIOUS_START_DATE,
	DEFAULT_TD_BONUS,
	DEFAULT_TD_LOOKBACK,
	DEFAULT_TOP_N as MYSTERIOUS_TOP_N,
	load_mysterious_spiral_results,
	run_mysterious_spiral_backtest,
)
from src.utils.research_strategy_backtest import (
	DEFAULT_FREE_CASH_FLOW_DIR,
	DEFAULT_INDEX_TIMING_DIR,
	DEFAULT_INTRADAY_ROOT,
	DEFAULT_MICRO_CAP_TIMING_DIR,
	DEFAULT_SECTOR_ROTATION_DUAL_DIR,
	DEFAULT_TURNOVER_STABILITY_DIR,
	discover_free_cash_flow_account_dirs,
	discover_intraday_result_dirs,
	load_free_cash_flow_account_results,
	load_free_cash_flow_results,
	load_index_timing_results,
	load_intraday_all_factor_results,
	load_micro_cap_timing_results,
	load_sector_rotation_dual_results,
	load_turnover_stability_results,
	run_free_cash_flow_backtest,
	run_index_timing_backtest,
	run_intraday_all_factor_backtest,
	run_micro_cap_timing_backtest,
	run_sector_rotation_dual_backtest,
	run_turnover_stability_backtest,
)
from src.utils.rotation_backtest import normalize_assets
from src.utils.small_cap_backtest import (
	DEFAULT_CODES as SMALL_CAP_DEFAULT_CODES,
	DEFAULT_OUTPUT_DIR as SMALL_CAP_OUTPUT_DIR,
	DEFAULT_START_DATE as SMALL_CAP_START_DATE,
	load_small_cap_results,
	run_small_cap_page_backtest,
)


def _render_nav_and_drawdown(
	cumulative: pd.DataFrame,
	drawdown: pd.DataFrame,
	*,
	columns: list[str] | None = None,
	nav_title: str = "累计净值",
	dd_title: str = "回撤",
) -> None:
	"""并排渲染累计净值与动态回撤折线图。"""
	if cumulative.empty or "Date" not in cumulative.columns:
		return
	available = [col for col in (columns or [c for c in cumulative.columns if c != "Date"]) if col in cumulative.columns]
	if not available:
		return
	nav_plot = cumulative[["Date", *available]]
	dd_cols = [col for col in available if col in drawdown.columns]
	left, right = st.columns(2)
	with left:
		st_pyecharts(draw_multi_line(nav_plot, nav_title), height="420px")
	with right:
		if not drawdown.empty and dd_cols:
			st_pyecharts(draw_multi_line(drawdown[["Date", *dd_cols]], dd_title), height="420px")


def _select_summary_row(metrics: pd.DataFrame, name_col: str, preferred_names: tuple[str, ...]) -> tuple[pd.Series, str]:
	"""按优先级在绩效表中选择用于顶部摘要卡片的主策略行。"""
	if name_col in metrics.columns:
		for preferred in preferred_names:
			matched = metrics[metrics[name_col].astype(str) == preferred]
			if not matched.empty:
				return matched.iloc[0], preferred
	row = metrics.iloc[0]
	return row, str(row.get(name_col, ""))


def _render_optional_tabs(named_frames: list[tuple[str, pd.DataFrame]]) -> None:
	"""只渲染非空的结果明细标签页。"""
	valid = [(label, frame) for label, frame in named_frames if frame is not None and not frame.empty]
	if not valid:
		return
	tabs = st.tabs([label for label, _ in valid])
	for tab, (_, frame) in zip(tabs, valid):
		with tab:
			st.dataframe(frame, use_container_width=True)


# ---------------------------------------------------------------------------
# 1. Small2 小市值选股策略
# ---------------------------------------------------------------------------


def render_small_cap_page() -> None:
	"""渲染 Small2 小市值选股策略配置、回测触发与结果展示页面。"""
	st.subheader("Small2 小市值选股策略")
	st.sidebar.markdown("# Small2 Config")
	data_source_params = market_data_source_ui("Small2")
	start_date = st.sidebar.date_input("Small2 start date", datetime.date.fromisoformat(SMALL_CAP_START_DATE))
	end_date = st.sidebar.date_input("Small2 end date", datetime.date.today())
	initial_cash = st.sidebar.number_input("Small2 initial cash", min_value=10000.0, value=1_000_000.0, step=100000.0)
	stock_num = st.sidebar.number_input("stock_num (持仓数)", min_value=1, max_value=100, value=3, step=1)
	pool_num = st.sidebar.number_input("pool_num (候选池上限)", min_value=10, max_value=500, value=100, step=10)
	rebalance_days = st.sidebar.number_input("rebalance_days (调仓间隔)", min_value=1, max_value=60, value=10, step=1)
	min_cap = st.sidebar.number_input("min_cap (流通市值下限/亿)", min_value=0.0, value=5.0, step=1.0)
	max_cap = st.sidebar.number_input("max_cap (流通市值上限/亿)", min_value=10.0, value=5000.0, step=50.0)
	sector_name = st.sidebar.text_input("sector (全市场板块名)", value="沪深A股")
	full_universe = st.sidebar.checkbox("使用完整沪深A股股票池（耗时较长）", value=False)

	codes_df = st.data_editor(
		pd.DataFrame({"code": SMALL_CAP_DEFAULT_CODES}),
		num_rows="dynamic",
		use_container_width=True,
		key="small_cap_codes",
		disabled=full_universe,
	)
	codes = [str(val).strip() for val in codes_df["code"].dropna().tolist() if str(val).strip()]

	if st.button("重新运行 Small2 回测", type="primary"):
		try:
			with st.spinner("正在构建股票池快照并运行 Small2 回测..."):
				frames = run_small_cap_page_backtest(
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					initial_cash=float(initial_cash),
					codes=codes,
					full_universe=bool(full_universe),
					sector_name=sector_name.strip() or "沪深A股",
					stock_num=int(stock_num),
					pool_num=int(pool_num),
					rebalance_days=int(rebalance_days),
					min_cap=float(min_cap),
					max_cap=float(max_cap),
					output_dir=SMALL_CAP_OUTPUT_DIR,
					data_source_params=data_source_params,
				)
			st.success(f"Small2 回测结果已更新: {SMALL_CAP_OUTPUT_DIR}")
		except Exception as exc:
			logger.exception("Small2 backtest failed")
			st.error(f"Small2 回测失败: {exc}")
			frames = load_small_cap_results(SMALL_CAP_OUTPUT_DIR)
	else:
		frames = load_small_cap_results(SMALL_CAP_OUTPUT_DIR)

	if frames is None:
		st.info(f"未找到 Small2 回测结果，请点击上方按钮运行回测生成 {SMALL_CAP_OUTPUT_DIR} 下的结果文件。")
		return

	if not frames.metrics.empty:
		row, name = _select_summary_row(frames.metrics, "策略", ("小市值策略(Small2)",))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("绩效指标")
		st.dataframe(frames.metrics, use_container_width=True)
	else:
		st.info("当前目录仅包含股票池快照与调仓历史；点击「重新运行 Small2 回测」可生成完整绩效指标与净值曲线。")

	_render_nav_and_drawdown(frames.cumulative, frames.drawdown)
	_render_optional_tabs(
		[
			("股票池快照", frames.universe_snapshot),
			("调仓历史", frames.rebalance_history),
			("每日收益", frames.returns),
			("累计净值", frames.cumulative),
			("回撤明细", frames.drawdown),
		]
	)


# ---------------------------------------------------------------------------
# 2. 神秘螺旋策略 (MysteriousSpiral)
# ---------------------------------------------------------------------------


def render_mysterious_spiral_page() -> None:
	"""渲染神秘螺旋（RPS60 + TD Sequential 月度轮动）页面。"""
	st.subheader("Mysterious Spiral 神秘螺旋月度轮动策略")
	st.sidebar.markdown("# Mysterious Spiral Config")
	data_source_params = market_data_source_ui("MysteriousSpiral")
	start_date = st.sidebar.date_input("Start date", datetime.date.fromisoformat(MYSTERIOUS_START_DATE))
	end_date = st.sidebar.date_input("End date", datetime.date.fromisoformat(MYSTERIOUS_END_DATE))
	initial_cash = st.sidebar.number_input("Initial cash", min_value=10000.0, value=MYSTERIOUS_INITIAL_CASH, step=100000.0)
	rps_window = st.sidebar.number_input("RPS window", min_value=5, max_value=250, value=DEFAULT_RPS_WINDOW, step=5)
	td_lookback = st.sidebar.number_input("TD lookback", min_value=1, max_value=60, value=DEFAULT_TD_LOOKBACK, step=1)
	td_bonus = st.sidebar.number_input("TD bonus", min_value=0.0, max_value=100.0, value=DEFAULT_TD_BONUS, step=5.0)
	top_n = st.sidebar.number_input("Top N", min_value=1, max_value=10, value=MYSTERIOUS_TOP_N, step=1)
	require_perfected = st.sidebar.checkbox("Require perfected TD setup", value=True)
	risk_config = risk_control_ui("MysteriousSpiral")

	assets_df = st.data_editor(
		pd.DataFrame(MYSTERIOUS_DEFAULT_ASSETS),
		column_order=["symbol", "name"],
		num_rows="dynamic",
		use_container_width=True,
		key="mysterious_spiral_assets",
	)
	assets = normalize_assets(assets_df)

	if st.button("重新运行 MysteriousSpiral 回测", type="primary"):
		try:
			with st.spinner("正在运行神秘螺旋回测..."):
				frames = run_mysterious_spiral_backtest(
					assets=assets,
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					initial_cash=float(initial_cash),
					rps_window=int(rps_window),
					td_lookback=int(td_lookback),
					td_bonus=float(td_bonus),
					top_n=int(top_n),
					require_perfected_setup=bool(require_perfected),
					output_dir=MYSTERIOUS_OUTPUT_DIR,
					data_source_params=data_source_params,
					risk_config=risk_config,
				)
			st.success(f"神秘螺旋结果已更新: {MYSTERIOUS_OUTPUT_DIR}")
		except Exception as exc:
			logger.exception("MysteriousSpiral backtest failed")
			st.error(f"神秘螺旋回测失败: {exc}")
			frames = load_mysterious_spiral_results(MYSTERIOUS_OUTPUT_DIR)
	else:
		frames = load_mysterious_spiral_results(MYSTERIOUS_OUTPUT_DIR)

	if frames is None:
		st.info(f"未找到神秘螺旋回测结果，请点击上方按钮运行回测生成 {MYSTERIOUS_OUTPUT_DIR} 下的结果文件。")
		return

	if not frames.metrics.empty:
		row, name = _select_summary_row(frames.metrics, "策略", ("神秘螺旋策略",))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("绩效指标")
		st.dataframe(frames.metrics, use_container_width=True)

	_render_nav_and_drawdown(frames.cumulative, frames.drawdown)
	if not frames.weights.empty:
		st_pyecharts(draw_weight_area(frames.weights), height="440px")

	_render_optional_tabs(
		[
			("月度调仓记录", frames.rebalance_history),
			("交易明细", frames.trades),
			("每日收益", frames.returns),
			("累计净值", frames.cumulative),
			("每日权重", frames.weights),
			("风控统计", frames.risk_summary if frames.risk_summary is not None else pd.DataFrame()),
			("风控事件", frames.risk_events if frames.risk_events is not None else pd.DataFrame()),
		]
	)


# ---------------------------------------------------------------------------
# 3. 双轮配置行业 ETF 策略 (SectorRotationDual)
# ---------------------------------------------------------------------------


def render_sector_rotation_dual_page() -> None:
	"""渲染双轮配置行业 ETF 策略页面。"""
	st.subheader("双轮配置行业 ETF 策略（招商证券）")
	st.sidebar.markdown("# Sector Rotation Dual Config")
	data_source_params = market_data_source_ui("DualRotation")
	start_date = st.sidebar.date_input("Dual start date", datetime.date(2017, 9, 1))
	end_date = st.sidebar.date_input("Dual end date", datetime.date.today())
	top_n = st.sidebar.number_input("正/反向各持仓数量 (top_n)", min_value=1, max_value=20, value=6, step=1)
	top_k = st.sidebar.number_input("每行业候选指数数 (top_k)", min_value=1, max_value=10, value=3, step=1)
	rebalance_every = st.sidebar.number_input("调仓周期（周）", min_value=1, max_value=8, value=1, step=1)
	trend_ma_weeks = st.sidebar.number_input("趋势均线窗口（周）", min_value=5, max_value=60, value=25, step=5)
	gap_mean_weeks = st.sidebar.number_input("风格差均值窗口（周）", min_value=4, max_value=26, value=12, step=2)
	norm_weeks = st.sidebar.number_input("标准化窗口（周）", min_value=12, max_value=104, value=52, step=4)
	heat = st.sidebar.selectbox("热度来源", ("ths_etf", "none", "ths_stock", "etf_amount", "index_amount"))
	fee_model = st.sidebar.selectbox("手续费模型", ("commission", "flat"))
	use_dtw = st.sidebar.checkbox("启用 DTW 历史相似性", value=True)
	refresh_pool = st.sidebar.checkbox("重建 ETF 池（覆盖 pool.csv）", value=False)

	if st.button("重新运行双轮行业 ETF 回测", type="primary"):
		try:
			with st.spinner("正在拉取行业 ETF 数据并运行双轮配置回测..."):
				frames = run_sector_rotation_dual_backtest(
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					top_k=int(top_k),
					top_n=int(top_n),
					rebalance_every=int(rebalance_every),
					trend_ma_weeks=int(trend_ma_weeks),
					gap_mean_weeks=int(gap_mean_weeks),
					norm_weeks=int(norm_weeks),
					heat=heat,
					use_dtw=bool(use_dtw),
					fee_model=fee_model,
					refresh_pool=bool(refresh_pool),
					output_dir=DEFAULT_SECTOR_ROTATION_DUAL_DIR,
					data_source_params=data_source_params,
				)
			st.success(f"双轮配置行业 ETF 结果已更新: {DEFAULT_SECTOR_ROTATION_DUAL_DIR}")
		except Exception as exc:
			logger.exception("SectorRotationDual backtest failed")
			st.error(f"双轮配置行业 ETF 回测失败: {exc}")
			frames = load_sector_rotation_dual_results(DEFAULT_SECTOR_ROTATION_DUAL_DIR)
	else:
		frames = load_sector_rotation_dual_results(DEFAULT_SECTOR_ROTATION_DUAL_DIR)

	if frames is None:
		st.info(f"未找到双轮行业 ETF 结果，请点击上方按钮运行回测生成 {DEFAULT_SECTOR_ROTATION_DUAL_DIR} 下的文件。")
		return

	if frames.source_flags:
		st.caption(" · ".join(f"{k}: {v}" for k, v in frames.source_flags.items()))

	if not frames.metrics.empty:
		row, name = _select_summary_row(frames.metrics, "策略", ("双轮配置",))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("绩效指标")
		st.dataframe(frames.metrics, use_container_width=True)

	if not frames.cumulative.empty:
		_render_nav_and_drawdown(frames.cumulative, frames.drawdown)
	elif frames.nav_image is not None:
		st.image(str(frames.nav_image), caption="历史回测净值与正向权重图（点击重新运行可生成交互式图表）", use_container_width=True)

	if not frames.weights.empty and {"Date", "w"}.issubset(frames.weights.columns):
		w_cols = [c for c in ("w", "heat_active") if c in frames.weights.columns]
		st_pyecharts(draw_multi_line(frames.weights[["Date", *w_cols]], "正向配置权重 w 与热度覆盖"), height="360px")

	_render_optional_tabs(
		[
			("配置权重与信号", frames.weights),
			("行业 ETF 池", frames.pool),
			("累计净值", frames.cumulative),
			("回撤明细", frames.drawdown),
		]
	)


# ---------------------------------------------------------------------------
# 4. 增强型自由现金流策略 (FreeCashFlow)
# ---------------------------------------------------------------------------


def render_free_cash_flow_page() -> None:
	"""渲染增强型自由现金流策略（研报复现 + 约束账户模拟）页面。"""
	st.subheader("增强型自由现金流策略（国泰海通）")
	view_mode = st.radio("视图模式", ("研报策略复现", "约束账户模拟"), horizontal=True)

	if view_mode == "约束账户模拟":
		account_dirs = discover_free_cash_flow_account_dirs(DEFAULT_FREE_CASH_FLOW_DIR)
		if not account_dirs:
			st.info("未找到约束账户模拟结果目录，请先运行 `python -m examples.free_cash_flow_account`。")
			return
		chosen = st.sidebar.selectbox(
			"账户模拟目录",
			account_dirs,
			format_func=lambda p: p.name,
		)
		acc = load_free_cash_flow_account_results(chosen)
		if acc is None:
			st.info(f"无法读取 {chosen} 下的约束账户结果。")
			return
		if not acc.metrics.empty:
			scenarios = acc.metrics["scenario"].astype(str).tolist() if "scenario" in acc.metrics.columns else []
			focus = st.sidebar.selectbox("摘要卡片聚焦方案", scenarios) if scenarios else ""
			row, name = _select_summary_row(acc.metrics, "scenario", (focus,) if focus else ())
			render_summary_from_metric_row(row, cumulative_return_from_frame(acc.cumulative, name))
			st.subheader("各方案账户绩效")
			st.dataframe(acc.metrics, use_container_width=True)
		_render_nav_and_drawdown(acc.cumulative, acc.drawdown, nav_title="约束账户净值（归一）")
		_render_optional_tabs(
			[
				("分年度收益", acc.yearly),
				("最新建仓清单", acc.latest_initial_orders),
				("行业权重", acc.industry_weights),
				("持仓明细", acc.positions),
				("调仓订单", acc.orders),
			]
		)
		return

	st.sidebar.markdown("# Free Cash Flow Config")
	start_date = st.sidebar.date_input("FCF start date", datetime.date(2014, 1, 1))
	end_date = st.sidebar.date_input("FCF end date", datetime.date(2026, 10, 30))
	size = st.sidebar.number_input("成分数量 (size)", min_value=10, max_value=300, value=100, step=10)
	weight_cap = st.sidebar.number_input("单股权重上限", min_value=0.01, max_value=1.0, value=0.10, step=0.01, format="%.2f")
	liquidity_keep = st.sidebar.number_input("流动性保留比例", min_value=0.2, max_value=1.0, value=0.80, step=0.05, format="%.2f")
	quality_keep = st.sidebar.number_input("盈利质量保留比例", min_value=0.2, max_value=1.0, value=0.80, step=0.05, format="%.2f")
	ocf_years = st.sidebar.number_input("连续正经营现金流年数", min_value=1, max_value=10, value=5, step=1)
	commission = st.sidebar.number_input("单边佣金率", min_value=0.0, max_value=0.01, value=0.0000854, step=0.00005, format="%.7f")

	if st.button("基于本地缓存重新运行自由现金流回测", type="primary"):
		try:
			with st.spinner("正在读取本地全市场行情与财报缓存并运行自由现金流回测..."):
				frames = run_free_cash_flow_backtest(
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					size=int(size),
					weight_cap=float(weight_cap),
					liquidity_keep=float(liquidity_keep),
					quality_keep=float(quality_keep),
					ocf_years=int(ocf_years),
					commission=float(commission),
					output_dir=DEFAULT_FREE_CASH_FLOW_DIR,
				)
			st.success(f"增强型自由现金流结果已更新: {DEFAULT_FREE_CASH_FLOW_DIR}")
		except Exception as exc:
			logger.exception("FreeCashFlow backtest failed")
			st.error(f"自由现金流回测失败: {exc}")
			frames = load_free_cash_flow_results(DEFAULT_FREE_CASH_FLOW_DIR)
	else:
		frames = load_free_cash_flow_results(DEFAULT_FREE_CASH_FLOW_DIR)

	if frames is None:
		st.info(f"未找到自由现金流回测结果，请先准备本地缓存并点击上方按钮运行。")
		return

	if not frames.metrics.empty:
		row, name = _select_summary_row(frames.metrics, "策略", ("增强-FCF加权", "增强-等权", "复现指数"))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("绩效指标")
		st.dataframe(frames.metrics, use_container_width=True)

	all_curves = [c for c in frames.cumulative.columns if c != "Date"]
	default_curves = [c for c in ("增强-FCF加权", "增强-等权", "复现指数", "中证现金流全收益", "中证红利全收益", "沪深300全收益") if c in all_curves]
	selected_curves = st.multiselect("对比曲线", all_curves, default=default_curves or all_curves[:5], key="fcf_curves")
	_render_nav_and_drawdown(frames.cumulative, frames.drawdown, columns=selected_curves)

	_render_optional_tabs(
		[
			("分年度收益", frames.yearly),
			("单因子与复合分组年化", frames.groups),
			("增强策略持仓记录", frames.holdings),
			("候选池规模", frames.pool_size),
			("官方成分重合度", frames.official_overlap),
			("累计净值明细", frames.cumulative),
		]
	)


# ---------------------------------------------------------------------------
# 5. 微盘股择时增强策略 (MicroCapTimingPlus)
# ---------------------------------------------------------------------------


def render_micro_cap_timing_page() -> None:
	"""渲染微盘股择时增强策略页面。"""
	st.subheader("微盘股择时增强策略（华福证券）")
	st.sidebar.markdown("# Micro Cap Timing Plus Config")
	start_date = st.sidebar.date_input("Start date", datetime.date(2016, 1, 4))
	end_date = st.sidebar.date_input("End date", datetime.date(2026, 6, 30))
	size = st.sidebar.number_input("微盘成分数量", min_value=50, max_value=1000, value=400, step=50)
	min_listed_days = st.sidebar.number_input("最低上市天数", min_value=1, max_value=365, value=60, step=10)
	ma_window = st.sidebar.number_input("趋势均线窗口 (MA)", min_value=3, max_value=120, value=15, step=1)
	bottom_hold_days = st.sidebar.number_input("底部持有天数", min_value=1, max_value=60, value=20, step=1)
	top_lock_days = st.sidebar.number_input("顶部空仓锁定天数", min_value=1, max_value=60, value=10, step=1)
	cost = st.sidebar.number_input("单边交易成本", min_value=0.0, max_value=0.01, value=0.001, step=0.0005, format="%.4f")
	large_code = st.sidebar.text_input("大盘对照指数", value="000300.SH")
	small_code = st.sidebar.text_input("小盘对照指数（留空使用微盘指数）", value="932000.CSI")

	if st.button("基于本地缓存重新运行微盘股择时回测", type="primary"):
		try:
			with st.spinner("正在重建微盘指数并运行择时增强回测..."):
				frames = run_micro_cap_timing_backtest(
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					size=int(size),
					min_listed_days=int(min_listed_days),
					ma_window=int(ma_window),
					bottom_hold_days=int(bottom_hold_days),
					top_lock_days=int(top_lock_days),
					cost=float(cost),
					large_code=large_code,
					small_code=small_code or None,
					output_dir=DEFAULT_MICRO_CAP_TIMING_DIR,
				)
			st.success(f"微盘股择时增强结果已更新: {DEFAULT_MICRO_CAP_TIMING_DIR}")
		except Exception as exc:
			logger.exception("MicroCapTimingPlus backtest failed")
			st.error(f"微盘股择时回测失败: {exc}")
			frames = load_micro_cap_timing_results(DEFAULT_MICRO_CAP_TIMING_DIR)
	else:
		frames = load_micro_cap_timing_results(DEFAULT_MICRO_CAP_TIMING_DIR)

	if frames is None:
		st.info(f"未找到微盘股择时结果，请先缓存数据并点击上方按钮运行回测。")
		return

	if not frames.metrics.empty:
		row, name = _select_summary_row(frames.metrics, "策略", ("MA15+底部+顶部", "MA15+底部", "MA15"))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("各择时变体绩效对比")
		st.dataframe(frames.metrics, use_container_width=True)

	_render_nav_and_drawdown(frames.cumulative, frames.drawdown)

	if not frames.signals.empty and {"Date", "position"}.issubset(frames.signals.columns):
		pos_cols = [c for c in ("position", "diffusion") if c in frames.signals.columns]
		st_pyecharts(draw_multi_line(frames.signals[["Date", *pos_cols]], "择时仓位与扩散度"), height="360px")

	_render_optional_tabs(
		[
			("逐日择时信号", frames.signals),
			("自建微盘指数", frames.micro_index),
			("累计净值明细", frames.cumulative),
			("回撤明细", frames.drawdown),
		]
	)


# ---------------------------------------------------------------------------
# 6. 量稳换手率选股策略 (TurnoverStability)
# ---------------------------------------------------------------------------


def render_turnover_stability_page() -> None:
	"""渲染量稳换手率选股策略（东吴证券 STR / SCR）页面。"""
	st.subheader("量稳换手率选股策略（东吴证券 STR / SCR）")
	st.sidebar.markdown("# Turnover Stability Config")
	start_date = st.sidebar.date_input("Start date", datetime.date(2013, 1, 1))
	end_date = st.sidebar.date_input("End date", datetime.date(2026, 10, 30))
	k_window = st.sidebar.number_input("当期窗口 K（日）", min_value=5, max_value=120, value=20, step=5)
	x_window = st.sidebar.number_input("基期窗口 X（日）", min_value=10, max_value=180, value=40, step=10)
	min_listed_days = st.sidebar.number_input("最低上市天数", min_value=30, max_value=365, value=120, step=30)
	top_fraction = st.sidebar.number_input("Top 分位比例", min_value=0.05, max_value=0.50, value=0.10, step=0.05, format="%.2f")
	top_n = st.sidebar.number_input("精选持股数 (Top N)", min_value=10, max_value=200, value=50, step=10)
	include_index_universes = st.sidebar.checkbox("包含沪深300/中证500子样本（耗时增加）", value=False)
	include_param_grid = st.sidebar.checkbox("包含 K×X 参数敏感性网格（耗时增加）", value=False)

	if st.button("基于本地缓存重新运行量稳换手率回测", type="primary"):
		try:
			with st.spinner("正在计算全 A 换手率截面因子与纯多头组合回测..."):
				frames = run_turnover_stability_backtest(
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					k_window=int(k_window),
					x_window=int(x_window),
					min_listed_days=int(min_listed_days),
					top_fraction=float(top_fraction),
					top_n=int(top_n),
					include_index_universes=bool(include_index_universes),
					include_param_grid=bool(include_param_grid),
					output_dir=DEFAULT_TURNOVER_STABILITY_DIR,
				)
			st.success(f"量稳换手率结果已更新: {DEFAULT_TURNOVER_STABILITY_DIR}")
		except Exception as exc:
			logger.exception("TurnoverStability backtest failed")
			st.error(f"量稳换手率回测失败: {exc}")
			frames = load_turnover_stability_results(DEFAULT_TURNOVER_STABILITY_DIR)
	else:
		frames = load_turnover_stability_results(DEFAULT_TURNOVER_STABILITY_DIR)

	if frames is None:
		st.info(f"未找到量稳换手率回测结果，请先准备本地日频缓存并点击上方按钮运行。")
		return

	if frames.metadata:
		data_range = frames.metadata.get("data_range", {})
		st.caption(
			f"数据范围 {data_range.get('start', '?')} ~ {data_range.get('end', '?')} · "
			f"调仓月数 {frames.metadata.get('rebalance_months', '?')} · "
			f"最新信号日 {frames.metadata.get('latest_signal_date', '?')}"
		)

	metrics_view = frames.metrics
	if not metrics_view.empty and "区间" in metrics_view.columns:
		periods = metrics_view["区间"].dropna().unique().tolist()
		selected_period = st.selectbox("统计区间", periods, index=0, key="turnover_period")
		period_df = metrics_view[metrics_view["区间"] == selected_period]
	else:
		period_df = metrics_view

	if not period_df.empty:
		row, name = _select_summary_row(period_df, "组合", ("全A_SCR_Top10%", "全A_SCR_Top50", "全A_STR_Top10%"))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("纯多头组合绩效")
		st.dataframe(period_df, use_container_width=True)

	all_curves = [c for c in frames.cumulative.columns if c != "Date"]
	default_curves = [c for c in ("全A_SCR_Top10%", "全A_SCR_Top50", "全A_STR_Top10%", "全A_PureSCR_Top10%", "中证全指") if c in all_curves]
	selected_curves = st.multiselect("对比曲线", all_curves, default=default_curves or all_curves[:5], key="turnover_curves")
	_render_nav_and_drawdown(frames.cumulative, frames.drawdown, columns=selected_curves)

	_render_optional_tabs(
		[
			("因子 IC 与多空汇总", frames.factor_summary),
			("10分组年化收益", frames.decile_annual),
			("组内收益离散度", frames.group_dispersion),
			("SCR 分年度表现", frames.yearly_scr),
			("STR 分年度表现", frames.yearly_str),
			("纯净 SCR 分年度", frames.yearly_pure_scr),
			("沪深300/中证500子样本", frames.index_universe_summary),
			("参数敏感性(样本内)", frames.param_sensitivity_is),
			("参数敏感性(样本外)", frames.param_sensitivity_oos),
			("最新 SCR Top50", frames.latest_top),
		]
	)


# ---------------------------------------------------------------------------
# 7. 高频价量 46 因子中证 500 策略 (IntradayAllFactor)
# ---------------------------------------------------------------------------


def render_intraday_all_factor_page() -> None:
	"""渲染高频价量 46 因子中证 500 周频回测页面。"""
	st.subheader("高频价量 46 因子中证 500 策略")
	st.sidebar.markdown("# Intraday 46-Factor Config")
	result_dirs = discover_intraday_result_dirs(DEFAULT_INTRADAY_ROOT)
	selected_dir: Path | None = None
	if result_dirs:
		selected_dir = st.sidebar.selectbox(
			"结果目录",
			result_dirs,
			format_func=lambda p: str(p.relative_to(DEFAULT_INTRADAY_ROOT)),
		)

	factor_dir = st.sidebar.text_input("分钟因子目录", value="data/intraday_factors/local_minute_factors")
	auction_dir = st.sidebar.text_input("竞价因子目录", value="data/intraday_factors/auction_history/daily")
	coverage_path = st.sidebar.text_input("资格覆盖表", value="examples/intraday_factors/auction_history/coverage.duckdb")
	history_path = st.sidebar.text_input("历史周度 IC 表", value="examples/intraday_factors/local_minute_research/weekly_research.csv")
	output_dir_text = st.sidebar.text_input("重跑输出目录", value="examples/intraday_factors/all_factor_backtest")

	if st.button("重新运行高频 46 因子周频回测", type="primary"):
		try:
			with st.spinner("正在加载 46 个高频因子并运行周频组合回测..."):
				frames = run_intraday_all_factor_backtest(
					output_dir=Path(output_dir_text),
					factor_dir=Path(factor_dir),
					auction_dir=Path(auction_dir),
					coverage=Path(coverage_path),
					history=Path(history_path),
				)
			st.success(f"高频 46 因子回测结果已更新: {frames.result_dir}")
		except Exception as exc:
			logger.exception("IntradayAllFactor backtest failed")
			st.error(f"高频 46 因子回测失败: {exc}")
			frames = load_intraday_all_factor_results(selected_dir)
	else:
		frames = load_intraday_all_factor_results(selected_dir)

	if frames is None:
		st.info("未找到高频 46 因子回测结果，请点击上方按钮基于本地因子缓存运行回测。")
		return

	if frames.raw_metrics:
		st.caption(
			f"结果目录: {frames.result_dir} · "
			f"区间 {frames.raw_metrics.get('first_trade_date', '?')} ~ {frames.raw_metrics.get('end_date', '?')} · "
			f"最新信号日 {frames.raw_metrics.get('latest_signal_date', '?')} · "
			f"调仓次数 {frames.raw_metrics.get('rebalance_count', '?')}"
		)

	if not frames.metrics.empty:
		row, name = _select_summary_row(frames.metrics, "策略", ("46因子策略",))
		render_summary_from_metric_row(row, cumulative_return_from_frame(frames.cumulative, name))
		st.subheader("绩效指标")
		st.dataframe(frames.metrics, use_container_width=True)

	_render_nav_and_drawdown(frames.cumulative, frames.drawdown)
	_render_optional_tabs(
		[
			("最新选股清单", frames.latest_selection),
			("期末持仓明细", frames.latest_holdings),
			("净值与持仓数明细", frames.nav_detail),
			("单因子研究汇总", frames.factor_summary),
			("因子滚动方向", frames.directions),
			("调仓目标", frames.targets),
			("成交记录", frames.trades),
		]
	)


# ---------------------------------------------------------------------------
# 8. 指数择时策略 MA / SMA / RSRS (IndexTiming)
# ---------------------------------------------------------------------------


def render_index_timing_page() -> None:
	"""渲染指数择时（华泰 MA/SMA 与光大 RSRS）策略页面。"""
	st.subheader("指数择时策略（MA / SMA / RSRS）")
	st.sidebar.markdown("# Index Timing Config")
	data_source_params = market_data_source_ui("IndexTiming")
	symbol = st.sidebar.text_input("指数代码", value="000300.SH")
	start_date = st.sidebar.date_input("Start date", datetime.date(2020, 1, 1))
	end_date = st.sidebar.date_input("End date", datetime.date(2025, 12, 31))
	ma_window = st.sidebar.number_input("MA 慢线周期", min_value=5, max_value=250, value=20, step=1)
	fast_ma = st.sidebar.number_input("SMA 快线周期", min_value=2, max_value=120, value=10, step=1)
	rsrs_window = st.sidebar.number_input("RSRS 斜率回归窗口", min_value=5, max_value=60, value=18, step=1)
	zscore_window = st.sidebar.number_input("RSRS 标准分滚动窗口", min_value=60, max_value=1200, value=600, step=30)
	slope_buy = st.sidebar.number_input("RSRS 斜率买入阈值", value=1.0, step=0.05, format="%.2f")
	slope_sell = st.sidebar.number_input("RSRS 斜率卖出阈值", value=0.8, step=0.05, format="%.2f")
	zscore_buy = st.sidebar.number_input("RSRS 标准分买入阈值", value=0.7, step=0.05, format="%.2f")
	zscore_sell = st.sidebar.number_input("RSRS 标准分卖出阈值", value=-0.7, step=0.05, format="%.2f")

	if st.button("运行自定义参数指数择时回测", type="primary"):
		try:
			with st.spinner("正在通过 DataHub 读取指数行情并运行择时回测..."):
				frames = run_index_timing_backtest(
					symbol=symbol.strip(),
					start_date=start_date.isoformat(),
					end_date=end_date.isoformat(),
					ma_window=int(ma_window),
					fast_ma=int(fast_ma),
					rsrs_window=int(rsrs_window),
					zscore_window=int(zscore_window),
					slope_buy=float(slope_buy),
					slope_sell=float(slope_sell),
					zscore_buy=float(zscore_buy),
					zscore_sell=float(zscore_sell),
					output_dir=DEFAULT_INDEX_TIMING_DIR,
					data_source_params=data_source_params,
				)
			st.success("自定义参数指数择时回测完成")
		except Exception as exc:
			logger.exception("IndexTiming backtest failed")
			st.error(f"指数择时回测失败: {exc}")
			frames = load_index_timing_results(DEFAULT_INDEX_TIMING_DIR)
	else:
		frames = load_index_timing_results(DEFAULT_INDEX_TIMING_DIR)

	if frames is None or not frames.periods:
		st.info("未找到指数择时复现结果，请点击上方按钮运行回测。")
		return

	if frames.metadata:
		st.caption(
			f"标的 {frames.metadata.get('symbol', '?')} · "
			f"数据源 {frames.metadata.get('source', '?')} · "
			f"数据范围 {frames.metadata.get('data_start', '?')} ~ {frames.metadata.get('data_end', '?')}"
		)

	period_names = list(frames.periods.keys())
	selected_period = st.selectbox("回测区间", period_names, index=0, key="index_timing_period")
	bundle = frames.periods[selected_period]
	metrics_df = bundle["metrics"]
	cumulative = bundle["cumulative"]
	drawdown = bundle["drawdown"]
	daily = bundle["daily"]

	if not metrics_df.empty:
		ranked = metrics_df.sort_values("score", ascending=False, na_position="last") if "score" in metrics_df.columns else metrics_df
		row, name = _select_summary_row(ranked, "策略", ())
		render_summary_from_metric_row(row, cumulative_return_from_frame(cumulative, name))
		st.subheader("各择时规则绩效对比")
		st.dataframe(metrics_df, use_container_width=True)

	_render_nav_and_drawdown(cumulative, drawdown)
	_render_optional_tabs(
		[
			("每日指标与持仓", daily),
			("累计净值明细", cumulative),
			("回撤明细", drawdown),
		]
	)
