"""神秘螺旋策略（RPS60 + TD Sequential 月度轮动）回测与结果读取服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from examples.backtest_common import (
	add_named_price_data,
	align_series,
	build_cerebro,
	build_return_metrics,
	build_return_series,
	build_risk_frames,
	prepare_price_data,
	read_result_detail,
	restore_metric_scores,
	run_equal_weight_backtest,
)
from src.risk import RiskConfig
from src.strategy import MysteriousSpiralStrategy, PerformanceCalculator
from src.utils.schemas import DataSourceParams


STRATEGY_NAME = "神秘螺旋策略"
EQUAL_WEIGHT_NAME = "等权重组合"
DATA_CACHE_NAME = "神秘螺旋"
DEFAULT_OUTPUT_DIR = Path("examples") / "mysterious_spiral"
DEFAULT_START_DATE = "2020-01-01"
DEFAULT_END_DATE = "2024-12-31"
DEFAULT_INITIAL_CASH = 1_000_000.0
DEFAULT_RPS_WINDOW = 60
DEFAULT_TD_LOOKBACK = 15
DEFAULT_TD_BONUS = 25.0
DEFAULT_TOP_N = 2

DEFAULT_ASSETS = [
	{"symbol": "600549.SH", "name": "厦门钨业"},
	{"symbol": "002378.SZ", "name": "章源钨业"},
	{"symbol": "000657.SZ", "name": "中钨高新"},
	{"symbol": "002997.SZ", "name": "瑞华泰"},
	{"symbol": "688779.SH", "name": "中国稀土"},
]


@dataclass(frozen=True)
class MysteriousSpiralFrames:
	"""神秘螺旋策略回测输出的指标、净值、权重与交易结果表。"""

	metrics: pd.DataFrame
	returns: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	weights: pd.DataFrame
	rebalance_history: pd.DataFrame
	trades: pd.DataFrame
	risk_events: pd.DataFrame | None = None
	risk_summary: pd.DataFrame | None = None


def _build_weight_frame(rebalance_history: list[dict], names: list[str]) -> pd.DataFrame:
	"""将月度调仓记录展开为日期 × 标的权重表。"""
	rows = []
	for snapshot in rebalance_history:
		weights = snapshot.get("target_weights") or {}
		date_value = snapshot.get("execution_date") or snapshot.get("signal_date")
		if not date_value:
			continue
		row = {"Date": date_value}
		for name in names:
			row[name] = float(weights.get(name, 0.0))
		row["权重合计"] = sum(row[name] for name in names)
		rows.append(row)
	return pd.DataFrame(rows, columns=["Date", *names, "权重合计"])


def _build_rebalance_table(rebalance_history: list[dict]) -> pd.DataFrame:
	"""将调仓历史整理为便于页面展示的扁平表格。"""
	rows = []
	for record in rebalance_history:
		selected = record.get("selected_names") or []
		scores = record.get("scores") or {}
		td_flags = record.get("td_bear_recent") or {}
		rows.append(
			{
				"信号日": record.get("signal_date", ""),
				"执行日": record.get("execution_date", ""),
				"入选标的": ", ".join(str(item) for item in selected),
				"入选数量": len(selected),
				"TD触发标的": ", ".join(name for name, flag in td_flags.items() if flag),
				"最高得分": max((float(v) for v in scores.values()), default=None),
			}
		)
	return pd.DataFrame(rows)


def _load_rebalance_json(path: Path) -> pd.DataFrame:
	if not path.exists():
		return pd.DataFrame()
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return pd.DataFrame()
	if not isinstance(raw, list) or not raw:
		return pd.DataFrame()
	return _build_rebalance_table(raw)


def _drawdown_from_returns(series: pd.Series) -> pd.Series:
	nav = (1.0 + series).cumprod()
	return nav / nav.cummax() - 1.0


def load_mysterious_spiral_results(output_dir: Path = DEFAULT_OUTPUT_DIR) -> MysteriousSpiralFrames | None:
	"""读取已保存的神秘螺旋回测结果；兼容仅含指标/交易日志的旧目录。"""
	metrics_path = output_dir / "performance_metrics.csv"
	if not metrics_path.exists():
		return None
	metrics = pd.read_csv(metrics_path, encoding="utf-8-sig")
	returns_path = output_dir / "daily_returns.csv"
	cumulative_path = output_dir / "cumulative_returns.csv"
	drawdown_path = output_dir / "drawdowns.csv"
	weights_path = output_dir / "daily_weights.csv"
	trades_path = output_dir / "trade_log.csv"
	rebalance_path = output_dir / "rebalance_history.json"
	risk_events_path = output_dir / "risk_events.csv"
	risk_summary_path = output_dir / "risk_summary.csv"

	returns = pd.read_csv(returns_path, encoding="utf-8-sig") if returns_path.exists() else pd.DataFrame()
	if "策略" not in metrics.columns and not metrics.empty:
		metrics.insert(0, "策略", STRATEGY_NAME)
	if not returns.empty:
		metrics = restore_metric_scores(metrics, returns)

	cumulative = pd.read_csv(cumulative_path, encoding="utf-8-sig") if cumulative_path.exists() else pd.DataFrame()
	drawdown = pd.read_csv(drawdown_path, encoding="utf-8-sig") if drawdown_path.exists() else pd.DataFrame()
	weights = read_result_detail(weights_path) if weights_path.exists() else pd.DataFrame()
	trades = read_result_detail(trades_path) if trades_path.exists() else pd.DataFrame()
	rebalance_df = _load_rebalance_json(rebalance_path)
	return MysteriousSpiralFrames(
		metrics=metrics,
		returns=returns,
		cumulative=cumulative,
		drawdown=drawdown,
		weights=weights,
		rebalance_history=rebalance_df,
		trades=trades,
		risk_events=read_result_detail(risk_events_path) if risk_events_path.exists() else None,
		risk_summary=read_result_detail(risk_summary_path) if risk_summary_path.exists() else None,
	)


def run_mysterious_spiral_backtest(
	assets: list[dict[str, str]],
	start_date: str = DEFAULT_START_DATE,
	end_date: str = DEFAULT_END_DATE,
	initial_cash: float = DEFAULT_INITIAL_CASH,
	rps_window: int = DEFAULT_RPS_WINDOW,
	td_lookback: int = DEFAULT_TD_LOOKBACK,
	td_bonus: float = DEFAULT_TD_BONUS,
	top_n: int = DEFAULT_TOP_N,
	require_perfected_setup: bool = True,
	output_dir: Path = DEFAULT_OUTPUT_DIR,
	price_data: dict[str, pd.DataFrame] | None = None,
	data_source_params: DataSourceParams | None = None,
	risk_config: RiskConfig | None = None,
) -> MysteriousSpiralFrames:
	"""运行神秘螺旋策略与等权组合回测，并落盘统一格式结果表。"""
	if len(assets) < 2:
		raise ValueError("神秘螺旋策略至少需要两只标的")

	symbols = [asset["symbol"] for asset in assets]
	price_data = price_data or prepare_price_data(
		symbols,
		start_date,
		end_date,
		DATA_CACHE_NAME,
		data_source_params,
	)
	available = [asset for asset in assets if asset["symbol"] in price_data]
	if len(available) < 2:
		raise RuntimeError("至少需要两只标的的完整行情才能运行神秘螺旋回测")

	available_symbols = [asset["symbol"] for asset in available]
	available_names = [asset["name"] for asset in available]

	cerebro = build_cerebro(initial_cash)
	cerebro.broker.set_coo(True)
	add_named_price_data(cerebro, price_data, available_symbols, available_names)
	strategy_kwargs: dict[str, object] = {
		"rps_window": int(rps_window),
		"td_lookback": int(td_lookback),
		"td_bonus": float(td_bonus),
		"top_n": min(int(top_n), len(available)),
		"require_perfected_setup": bool(require_perfected_setup),
	}
	if risk_config is not None:
		strategy_kwargs["risk_config"] = risk_config
	cerebro.addstrategy(MysteriousSpiralStrategy, **strategy_kwargs)
	strategy_result = cerebro.run(cheat_on_open=True)[0]

	equal_result = run_equal_weight_backtest(
		price_data,
		available_symbols,
		available_names,
		initial_cash,
		EQUAL_WEIGHT_NAME,
	)

	strategy_returns = build_return_series(strategy_result)
	equal_returns = build_return_series(equal_result)
	strategy_returns, equal_returns = align_series(strategy_returns, equal_returns)

	calc = PerformanceCalculator()
	metrics = pd.DataFrame(
		[
			{"策略": STRATEGY_NAME}
			| build_return_metrics(strategy_returns)
			| {
				"索提诺比率": calc.sortino_ratio(strategy_returns),
				"胜率": calc.win_rate(strategy_returns) if len(strategy_returns) else None,
				"总交易日": int(len(strategy_returns)),
				"成交笔数": len(strategy_result.trade_log),
			},
			{"策略": EQUAL_WEIGHT_NAME}
			| build_return_metrics(equal_returns)
			| {
				"索提诺比率": calc.sortino_ratio(equal_returns),
				"胜率": calc.win_rate(equal_returns) if len(equal_returns) else None,
				"总交易日": int(len(equal_returns)),
				"成交笔数": len(available_symbols),
			},
		]
	)

	returns_df = pd.DataFrame(
		{
			"Date": strategy_returns.index.strftime("%Y-%m-%d"),
			STRATEGY_NAME: strategy_returns.values,
			EQUAL_WEIGHT_NAME: equal_returns.values,
		}
	)
	cumulative_df = pd.DataFrame(
		{
			"Date": strategy_returns.index.strftime("%Y-%m-%d"),
			STRATEGY_NAME: (1.0 + strategy_returns).cumprod().values,
			EQUAL_WEIGHT_NAME: (1.0 + equal_returns).cumprod().values,
		}
	)
	drawdown_df = pd.DataFrame(
		{
			"Date": strategy_returns.index.strftime("%Y-%m-%d"),
			STRATEGY_NAME: _drawdown_from_returns(strategy_returns).values,
			EQUAL_WEIGHT_NAME: _drawdown_from_returns(equal_returns).values,
		}
	)
	weights_df = _build_weight_frame(strategy_result.rebalance_history, available_names)
	rebalance_df = _build_rebalance_table(strategy_result.rebalance_history)
	trades_df = pd.DataFrame(strategy_result.trade_log)
	risk_events, risk_summary = build_risk_frames(strategy_result)

	output_dir.mkdir(parents=True, exist_ok=True)
	metrics.to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
	returns_df.to_csv(output_dir / "daily_returns.csv", index=False, encoding="utf-8-sig")
	cumulative_df.to_csv(output_dir / "cumulative_returns.csv", index=False, encoding="utf-8-sig")
	drawdown_df.to_csv(output_dir / "drawdowns.csv", index=False, encoding="utf-8-sig")
	weights_df.to_csv(output_dir / "daily_weights.csv", index=False, encoding="utf-8-sig")
	trades_df.to_csv(output_dir / "trade_log.csv", index=False, encoding="utf-8-sig")
	pd.DataFrame(strategy_result.rebalance_history).to_json(
		output_dir / "rebalance_history.json",
		orient="records",
		force_ascii=False,
		indent=2,
	)
	if risk_events is not None:
		risk_events.to_csv(output_dir / "risk_events.csv", index=False, encoding="utf-8-sig")
	if risk_summary is not None:
		risk_summary.to_csv(output_dir / "risk_summary.csv", index=False, encoding="utf-8-sig")

	return MysteriousSpiralFrames(
		metrics=metrics,
		returns=returns_df,
		cumulative=cumulative_df,
		drawdown=drawdown_df,
		weights=weights_df,
		rebalance_history=rebalance_df,
		trades=trades_df,
		risk_events=risk_events,
		risk_summary=risk_summary,
	)
