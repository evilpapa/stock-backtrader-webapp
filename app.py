import datetime
import math

import pandas as pd
import streamlit as st
from streamlit_echarts import st_pyecharts

from charts import draw_multi_line, draw_pro_kline, draw_result_bar, draw_weight_area
from frames import backtrader_selector_ui, data_selector_ui, params_selector_ui
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
    RotationGridResult,
    RotationSpec,
    load_rotation_results,
    normalize_assets as normalize_rotation_assets,
    run_rotation_backtest,
    run_rotation_grid_search,
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

SUMMARY_CARD_CSS = """
<style>
.performance-summary {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 16px 18px;
    background: #ffffff;
    min-height: 116px;
}
.performance-summary-primary {
    min-height: 116px;
}
.performance-summary-label {
    color: #6b7280;
    font-size: 0.9rem;
    margin-bottom: 8px;
}
.performance-summary-annual {
    color: #d62728;
    font-size: 2.45rem;
    font-weight: 700;
    line-height: 1.05;
}
.performance-summary-sub {
    color: #374151;
    font-size: 0.98rem;
    margin-top: 10px;
}
.performance-summary-value {
    color: #111827;
    font-size: 1.6rem;
    font-weight: 650;
    line-height: 1.15;
}
</style>
"""


def _number_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _row_value(row: pd.Series | dict, names: list[str]) -> float | None:
    for name in names:
        if name in row:
            value = _number_or_none(row[name])
            if value is not None:
                return value
    return None


def _annual_return_from_row(row: pd.Series | dict) -> float | None:
    value = _row_value(row, ["年化收益率", "annual_return", "annualized_return"])
    if value is not None:
        return value
    value = _row_value(row, ["return"])
    return value / 100.0 if value is not None else None


def _cumulative_return_from_row(row: pd.Series | dict) -> float | None:
    return _row_value(row, ["累计收益率", "total_return", "cumulative_return"])


def _max_drawdown_from_row(row: pd.Series | dict) -> float | None:
    value = _row_value(row, ["最大回撤", "max_drawdown"])
    if value is not None:
        return -abs(value)
    value = _row_value(row, ["dd"])
    return -abs(value / 100.0) if value is not None else None


def _ratio_from_row(row: pd.Series | dict, names: list[str]) -> float | None:
    return _row_value(row, names)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.3f}"


def render_performance_summary(
    annual_return: float | None,
    cumulative_return: float | None,
    max_drawdown: float | None,
    sharpe_ratio: float | None,
    calmar_ratio: float | None,
) -> None:
    st.markdown(SUMMARY_CARD_CSS, unsafe_allow_html=True)
    left, dd_col, sharpe_col, calmar_col = st.columns([2.2, 1, 1, 1])
    with left:
        st.markdown(
            f"""
            <div class="performance-summary performance-summary-primary">
                <div class="performance-summary-label">年化收益</div>
                <div class="performance-summary-annual">{_format_percent(annual_return)}</div>
                <div class="performance-summary-sub">累计收益 {_format_percent(cumulative_return)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for column, label, value, formatter in [
        (dd_col, "最大回撤", max_drawdown, _format_percent),
        (sharpe_col, "夏普比率", sharpe_ratio, _format_ratio),
        (calmar_col, "卡玛比率", calmar_ratio, _format_ratio),
    ]:
        with column:
            st.markdown(
                f"""
                <div class="performance-summary">
                    <div class="performance-summary-label">{label}</div>
                    <div class="performance-summary-value">{formatter(value)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_summary_from_metric_row(row: pd.Series | dict, cumulative_return: float | None = None) -> None:
    render_performance_summary(
        annual_return=_annual_return_from_row(row),
        cumulative_return=cumulative_return if cumulative_return is not None else _cumulative_return_from_row(row),
        max_drawdown=_max_drawdown_from_row(row),
        sharpe_ratio=_ratio_from_row(row, ["夏普比率", "sharpe", "sharpe_ratio"]),
        calmar_ratio=_ratio_from_row(row, ["卡玛比率", "卡尔马比率", "calmar", "calmar_ratio"]),
    )


def cumulative_return_from_frame(cumulative: pd.DataFrame, strategy_name: str) -> float | None:
    if strategy_name not in cumulative.columns or cumulative.empty:
        return None
    value = _number_or_none(cumulative[strategy_name].iloc[-1])
    return value - 1.0 if value is not None else None


def render_strategy_result_frames(frames: EtfMomentumFrames | RotationFrames) -> None:
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


def _param_range_ui(key: str, label: str, default_value: int) -> tuple[int, int, int]:
    """渲染 min / max / step 三列参数范围输入，返回 (min_val, max_val, step)"""
    st.markdown(f"**{label}**")
    cols = st.columns(3)
    with cols[0]:
        min_val = st.number_input(f"min {key}", value=default_value - 10, min_value=1, step=1, key=f"min_{key}")
    with cols[1]:
        max_val = st.number_input(f"max {key}", value=default_value + 10, min_value=1, step=1, key=f"max_{key}")
    with cols[2]:
        step_val = st.number_input(f"step {key}", value=5, min_value=1, step=1, key=f"step_{key}")
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    if step_val < 1:
        step_val = 1
    return min_val, max_val, step_val


def render_rotation_page(spec: RotationSpec) -> None:
    st.subheader(spec.title)
    st.sidebar.markdown(f"# {spec.title} Config")
    start_date = st.sidebar.date_input(
        f"{spec.key} start date",
        datetime.date.fromisoformat(spec.default_start_date),
    )
    end_date = st.sidebar.date_input(f"{spec.key} end date", datetime.datetime.today())
    initial_cash = st.sidebar.number_input(f"{spec.key} start cash", min_value=0.0, value=100000.0, step=10000.0)

    # 参数范围输入（替换之前的单个数字）
    st.sidebar.markdown("---")
    st.sidebar.markdown("**参数范围（网格搜索）**")
    st.sidebar.caption("设 min=max 即为单次运行")
    mw_min, mw_max, mw_step = _param_range_ui(f"{spec.key}_mw", "动量窗口", spec.default_momentum_window)
    rd_min, rd_max, rd_step = _param_range_ui(f"{spec.key}_rd", "调仓间隔", spec.default_rebalance_days)
    tl_min, tl_max, tl_step = _param_range_ui(f"{spec.key}_tl", "持仓数量(L)", spec.default_top_l)

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

    # 存储结果
    if "rotation_grid_result" not in st.session_state:
        st.session_state.rotation_grid_result = None
    if "rotation_frames" not in st.session_state:
        st.session_state.rotation_frames = None

    if st.button(f"运行 {spec.title} 回测", type="primary"):
        try:
            mw_range = range(mw_min, mw_max + 1, mw_step)
            rd_range = range(rd_min, rd_max + 1, rd_step)
            tl_range = range(tl_min, tl_max + 1, tl_step)
            total_combos = len(list(mw_range)) * len(list(rd_range)) * len(list(tl_range))

            param_ranges = {
                "momentum_window": mw_range,
                "rebalance_days": rd_range,
                "top_l": tl_range,
            }

            with st.spinner(f"正在运行 {spec.title} 网格搜索（共 {total_combos} 种参数组合）..."):
                if total_combos == 1:
                    # 单次运行，走原来的路
                    frames = run_rotation_backtest(
                        spec=spec,
                        assets=assets,
                        benchmark_symbol=benchmark_symbol.strip(),
                        benchmark_name=benchmark_name.strip() or spec.benchmark_name,
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        initial_cash=float(initial_cash),
                        momentum_window=mw_min,
                        rebalance_days=rd_min,
                        top_l=tl_min,
                    )
                    st.session_state.rotation_grid_result = None
                    st.session_state.rotation_frames = frames
                    st.success(f"{spec.title} 回测完成")
                else:
                    # 网格搜索
                    grid_result = run_rotation_grid_search(
                        spec=spec,
                        assets=assets,
                        benchmark_symbol=benchmark_symbol.strip(),
                        benchmark_name=benchmark_name.strip() or spec.benchmark_name,
                        start_date=start_date.isoformat(),
                        end_date=end_date.isoformat(),
                        initial_cash=float(initial_cash),
                        param_ranges=param_ranges,
                    )
                    st.session_state.rotation_grid_result = grid_result
                    st.session_state.rotation_frames = grid_result.best_frames
                    st.success(
                        f"{spec.title} 网格搜索完成（{total_combos} 种组合），"
                        f"最优参数已保存到 {spec.output_dir}"
                    )
        except Exception as exc:
            logger.exception(f"{spec.key} backtest failed")
            st.error(f"{spec.title} 回测失败: {exc}")
            st.session_state.rotation_grid_result = None
            st.session_state.rotation_frames = load_rotation_results(spec)

    grid_result = st.session_state.rotation_grid_result
    frames = st.session_state.rotation_frames

    if frames is None:
        st.info(f"未找到完整 {spec.title} 结果，请点击运行回测。")
        return

    # 显示参数对比表（网格搜索时）
    if grid_result is not None and not grid_result.comparison.empty:
        st.subheader("参数对比")

        # 格式化百分比列
        display_df = grid_result.comparison.copy()
        pct_cols = ["年化收益率", "年化波动率", "最大回撤", "胜率"]
        for col in pct_cols:
            if col in display_df.columns:
                display_df[col] = display_df[col].map(
                    lambda v: f"{v * 100:.2f}%" if pd.notna(v) else "N/A"
                )
        ratio_cols = ["夏普比率", "卡尔马比率", "索提诺比率"]
        for col in ratio_cols:
            if col in display_df.columns:
                display_df[col] = display_df[col].map(
                    lambda v: f"{v:.3f}" if pd.notna(v) else "N/A"
                )

        st.dataframe(display_df.style.highlight_max(subset=[c for c in display_df.columns if c not in ["momentum_window", "rebalance_days", "top_l"]]), use_container_width=True)
        st.caption("按年化收益率降序排列，绿色高亮 = 该列最大值")

        # 参数组合柱状图
        if len(grid_result.comparison) >= 2:
            chart_df = grid_result.comparison.copy()
            chart_df["label"] = chart_df.apply(
                lambda r: f"N{r['momentum_window']}_K{r['rebalance_days']}_L{r['top_l']}", axis=1
            )
            bar = draw_result_bar(chart_df, n_scors=5)
            st_pyecharts(bar, height="460px")

    # 显示最优结果的详细回测
    st.subheader("最优结果详情" if grid_result else "回测结果")
    render_strategy_result_frames(frames)


def render_turtle_frames(frames: TurtleFrames) -> None:
	st.subheader("海龟交易结果")
	equity = frames.equity.copy()
	equity["date"] = pd.to_datetime(equity["date"])

	if not frames.metrics.empty:
		render_summary_from_metric_row(frames.metrics.iloc[0])

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
	data_params = data_selector_ui()
	bt_params = backtrader_selector_ui()
	if not data_params.symbol:
		return

	stock_df = gen_stock_df(data_params)
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

	logger.info(f"akshare: {data_params}")
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
	if not par_df.empty:
		best_row = par_df.loc[par_df["return"].idxmax()]
		render_summary_from_metric_row(best_row)
	st.dataframe(par_df.style.highlight_max(subset=par_df.columns[-5:]))
	bar = draw_result_bar(par_df, n_scors=5)
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

