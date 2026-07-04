from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from examples.rotation_backtest_common import (
	align_series,
	build_cumulative_frame,
	build_drawdown_frame,
	build_metrics,
	build_rebalance_detail_frame,
	build_return_series,
	build_returns_frame,
	build_selection_frequency_frame,
	build_weight_frame,
	prepare_price_data,
	run_benchmark_backtest,
	run_equal_weight_backtest,
	run_rotation_strategy_backtest,
	save_results,
)
from strategy.leading_rotation import LeadingRotationStrategy
from strategy.sector_rotation import SectorRotationStrategy


@dataclass(frozen=True)
class RotationSpec:
	key: str
	title: str
	strategy_name: str
	benchmark_symbol: str
	benchmark_name: str
	equal_weight_name: str
	data_cache_name: str
	asset_label: str
	output_dir: Path
	assets: list[dict[str, str]]
	strategy_cls: type
	default_start_date: str
	default_momentum_window: int = 20
	default_rebalance_days: int = 5
	default_top_l: int = 5


@dataclass(frozen=True)
class RotationFrames:
	metrics: pd.DataFrame
	returns: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	weights: pd.DataFrame
	selection_frequency: pd.DataFrame | None = None
	rebalance_details: pd.DataFrame | None = None


RESULT_FILES = {
	"metrics": "performance_metrics.csv",
	"returns": "daily_returns.csv",
	"cumulative": "cumulative_returns.csv",
	"drawdown": "drawdowns.csv",
	"weights": "daily_weights.csv",
	"selection_frequency": "selection_frequency.csv",
	"rebalance_details": "rebalance_details.csv",
}


LEADING_ASSETS = [
	{"symbol": "600111", "name": "北方稀土"},
	{"symbol": "002460", "name": "赣锋锂业"},
	{"symbol": "601899", "name": "紫金矿业"},
	{"symbol": "600988", "name": "赤峰黄金"},
	{"symbol": "002230", "name": "科大讯飞"},
	{"symbol": "300750", "name": "宁德时代"},
	{"symbol": "002594", "name": "比亚迪"},
	{"symbol": "603259", "name": "药明康德"},
	{"symbol": "601939", "name": "建设银行"},
	{"symbol": "688256", "name": "寒武纪"},
	{"symbol": "601606", "name": "长城军工"},
	{"symbol": "688981", "name": "中芯国际"},
	{"symbol": "300502", "name": "新易盛"},
	{"symbol": "601138", "name": "工业富联"},
	{"symbol": "300308", "name": "中际旭创"},
	{"symbol": "300476", "name": "胜宏科技"},
	{"symbol": "300394", "name": "天孚通信"},
	{"symbol": "688041", "name": "海光信息"},
	{"symbol": "601336", "name": "新华保险"},
	{"symbol": "600519", "name": "贵州茅台"},
	{"symbol": "601288", "name": "农业银行"},
	{"symbol": "601319", "name": "中国人保"},
]

SECTOR_ASSETS = [
	{"symbol": "159819", "name": "人工智能ETF"},
	{"symbol": "588000", "name": "科创50ETF"},
	{"symbol": "512690", "name": "军工ETF"},
	{"symbol": "159813", "name": "半导体ETF"},
	{"symbol": "159526", "name": "机器人ETF嘉实"},
	{"symbol": "515650", "name": "消费50ETF"},
	{"symbol": "159869", "name": "游戏ETF"},
	{"symbol": "159740", "name": "恒生科技ETF"},
	{"symbol": "159992", "name": "创新药ETF"},
	{"symbol": "159755", "name": "电池ETF"},
	{"symbol": "515290", "name": "银行ETF易方达"},
	{"symbol": "512200", "name": "房地产ETF"},
	{"symbol": "159766", "name": "旅游ETF"},
]

ROTATION_SPECS = {
	"LeadingRotation": RotationSpec(
		key="LeadingRotation",
		title="Leading Rotation",
		strategy_name="龙头动量轮动策略",
		benchmark_symbol="588000",
		benchmark_name="科创50ETF",
		equal_weight_name="等权重组合",
		data_cache_name="leading_rotation",
		asset_label="Stock",
		output_dir=Path("examples") / "leading_rotation" / "backtest_results",
		assets=LEADING_ASSETS,
		strategy_cls=LeadingRotationStrategy,
		default_start_date="2025-01-01",
	),
	"SectorRotation": RotationSpec(
		key="SectorRotation",
		title="Sector Rotation",
		strategy_name="行业动量轮动策略",
		benchmark_symbol="588000",
		benchmark_name="科创50ETF",
		equal_weight_name="行业等权重组合",
		data_cache_name="sector_rotation",
		asset_label="ETF",
		output_dir=Path("examples") / "sector_rotation" / "backtest_results",
		assets=SECTOR_ASSETS,
		strategy_cls=SectorRotationStrategy,
		default_start_date="2026-01-01",
	),
}


def normalize_assets(assets: pd.DataFrame) -> list[dict[str, str]]:
	normalized = []
	for _, row in assets.iterrows():
		symbol = str(row.get("symbol", "")).strip()
		name = str(row.get("name", "")).strip()
		if symbol and name:
			normalized.append({"symbol": symbol, "name": name})
	return normalized


def load_rotation_results(spec: RotationSpec) -> RotationFrames | None:
	mandatory = ["metrics", "returns", "cumulative", "drawdown", "weights"]
	if not all((spec.output_dir / RESULT_FILES[key]).exists() for key in mandatory):
		return None
	selection_path = spec.output_dir / RESULT_FILES["selection_frequency"]
	rebalance_path = spec.output_dir / RESULT_FILES["rebalance_details"]
	return RotationFrames(
		metrics=pd.read_csv(spec.output_dir / RESULT_FILES["metrics"], encoding="utf-8-sig"),
		returns=pd.read_csv(spec.output_dir / RESULT_FILES["returns"], encoding="utf-8-sig"),
		cumulative=pd.read_csv(spec.output_dir / RESULT_FILES["cumulative"], encoding="utf-8-sig"),
		drawdown=pd.read_csv(spec.output_dir / RESULT_FILES["drawdown"], encoding="utf-8-sig"),
		weights=pd.read_csv(spec.output_dir / RESULT_FILES["weights"], encoding="utf-8-sig"),
		selection_frequency=(
			pd.read_csv(selection_path, encoding="utf-8-sig") if selection_path.exists() else None
		),
		rebalance_details=(
			pd.read_csv(rebalance_path, encoding="utf-8-sig") if rebalance_path.exists() else None
		),
	)


def run_rotation_backtest(
	spec: RotationSpec,
	assets: list[dict[str, str]],
	benchmark_symbol: str,
	benchmark_name: str,
	start_date: str,
	end_date: str,
	initial_cash: float,
	momentum_window: int,
	rebalance_days: int,
	top_l: int,
	price_data: dict[str, pd.DataFrame] | None = None,
) -> RotationFrames:
	if not assets:
		raise ValueError(f"{spec.title} 至少需要一个可交易标的")

	strategy_assets = list(assets)
	if benchmark_symbol not in {asset["symbol"] for asset in strategy_assets}:
		strategy_assets.append({"symbol": benchmark_symbol, "name": benchmark_name})

	all_symbols = [asset["symbol"] for asset in strategy_assets]
	all_names = [asset["name"] for asset in strategy_assets]
	price_data = price_data or prepare_price_data(all_symbols, start_date, end_date, spec.data_cache_name)
	if benchmark_symbol not in price_data:
		raise RuntimeError(f"缺少基准数据: {benchmark_symbol}")

	available_assets = [asset for asset in strategy_assets if asset["symbol"] in price_data]
	available_symbols = [asset["symbol"] for asset in available_assets]
	available_names = [asset["name"] for asset in available_assets]
	if not available_symbols:
		raise RuntimeError(f"{spec.title} 回测缺少可用数据")

	strategy_result = run_rotation_strategy_backtest(
		price_data,
		available_symbols,
		available_names,
		benchmark_name,
		spec.strategy_cls,
		spec.strategy_name,
		initial_cash,
		momentum_window,
		rebalance_days,
		top_l,
	)
	benchmark_result = run_benchmark_backtest(
		price_data,
		benchmark_symbol,
		benchmark_name,
		initial_cash,
	)
	equal_assets = [
		asset for asset in assets
		if asset["symbol"] != benchmark_symbol and asset["symbol"] in price_data
	]
	equal_result = run_equal_weight_backtest(
		price_data,
		[asset["symbol"] for asset in equal_assets],
		[asset["name"] for asset in equal_assets],
		initial_cash,
		spec.equal_weight_name,
	)

	strategy_returns = build_return_series(strategy_result)
	benchmark_returns = build_return_series(benchmark_result)
	equal_returns = build_return_series(equal_result)
	strategy_returns, benchmark_returns, equal_returns = align_series(
		strategy_returns,
		benchmark_returns,
		equal_returns,
	)

	frames = RotationFrames(
		metrics=build_metrics(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			spec.strategy_name,
			benchmark_name,
			spec.equal_weight_name,
		),
		returns=build_returns_frame(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			spec.strategy_name,
			benchmark_name,
			spec.equal_weight_name,
		),
		cumulative=build_cumulative_frame(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			spec.strategy_name,
			benchmark_name,
			spec.equal_weight_name,
		),
		drawdown=build_drawdown_frame(
			strategy_returns,
			benchmark_returns,
			equal_returns,
			spec.strategy_name,
			benchmark_name,
			spec.equal_weight_name,
		),
		weights=build_weight_frame(strategy_result),
		selection_frequency=build_selection_frequency_frame(strategy_result, spec.asset_label),
		rebalance_details=build_rebalance_detail_frame(strategy_result, spec.asset_label),
	)
	save_results(
		spec.output_dir,
		frames.metrics,
		frames.returns,
		frames.cumulative,
		frames.drawdown,
		frames.weights,
		frames.selection_frequency,
		frames.rebalance_details,
	)
	return frames
