"""ETF 动量策略回测。

运行：``uv run python examples/etf_momentum.py``
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from tabulate import tabulate

from examples.backtest_common import format_metrics_for_console, plot_compare, plot_weights
from src.charts import configure_matplotlib_chinese_font
from src.constants import (
    BENCHMARK_COLOR, DEFAULT_MOMENTUM_WINDOW, DEFAULT_REBALANCE_DAYS,
    EQUAL_WEIGHT_COLOR, INITIAL_CASH, STRATEGY_COLOR, default_backtest_end,
)
from src.risk.cli import add_risk_arguments, risk_config_from_args
from src.utils.etf_momentum_backtest import (
    BENCHMARK_NAME, DEFAULT_ASSETS, DEFAULT_OUTPUT_DIR, EQUAL_WEIGHT_NAME,
    STRATEGY_NAME, run_etf_momentum_backtest,
)
from src.utils.schemas import DataSourceParams


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="运行 ETF 动量策略回测")
	parser.add_argument(
		"--data-source", choices=("tushare", "qmt", "cache"),
		default=os.getenv("DATAHUB_DATA_SOURCE", "tushare"),
		help="通过 DataHub 选择数据源：Tushare、QMT/XtQuant 或本地 DuckDB cache",
	)
	parser.add_argument(
		"--cache-path", default=os.getenv("DATAHUB_CACHE_PATH", "data/etf.duckdb"),
		help="cache 模式使用的本地 DuckDB 文件",
	)
	parser.add_argument(
		"--dividend-type", choices=("none", "front", "back", "qfq", "hfq"),
		default=os.getenv("DATAHUB_DIVIDEND_TYPE", "front"),
		help="复权口径；当前 data/etf.duckdb 仅保存 none，因此 cache 模式请使用 none",
	)
	parser.add_argument("--start", default="2025-01-01", help="回测开始日期，YYYY-MM-DD")
	parser.add_argument("--end", default=default_backtest_end(), help="回测结束日期，YYYY-MM-DD")
	parser.add_argument("--output-dir", default="", help="结果目录；默认按数据源分目录保存")
	parser.add_argument("--tushare-token", default=os.getenv("TUSHARE_TOKEN", ""))
	parser.add_argument("--tushare-timeout", type=float, default=float(os.getenv("TUSHARE_TIMEOUT_SECONDS", "30")))
	parser.add_argument("--bigqmt-account-id", default=str(os.getenv("BIGQMT_ACCOUNT_ID", "")), help=argparse.SUPPRESS)
	parser.add_argument("--bigqmt-timeout", type=float, default=None, help=argparse.SUPPRESS)
	add_risk_arguments(parser)
	return parser


def parse_data_source_params(argv: Sequence[str] | None = None) -> DataSourceParams:
    args = _build_parser().parse_args(argv)
    return DataSourceParams(
        data_source=args.data_source,
        cache_path=args.cache_path,
        dividend_type=args.dividend_type,
        tushare_token=args.tushare_token,
        tushare_timeout=args.tushare_timeout if args.bigqmt_timeout is None else args.bigqmt_timeout,
        bigqmt_account_id=args.bigqmt_account_id,
        bigqmt_timeout=args.tushare_timeout if args.bigqmt_timeout is None else args.bigqmt_timeout,
    )


def main() -> None:
    configure_matplotlib_chinese_font()
    args = _build_parser().parse_args()
    data_source_params = parse_data_source_params()
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR / args.data_source
    risk_config = risk_config_from_args(args)
    frames = run_etf_momentum_backtest(
        DEFAULT_ASSETS, "510300", BENCHMARK_NAME, args.start, args.end,
        INITIAL_CASH, DEFAULT_MOMENTUM_WINDOW, DEFAULT_REBALANCE_DAYS,
        output_dir, data_source_params=data_source_params, risk_config=risk_config,
    )
    colors = {STRATEGY_NAME: STRATEGY_COLOR, BENCHMARK_NAME: BENCHMARK_COLOR, EQUAL_WEIGHT_NAME: EQUAL_WEIGHT_COLOR}
    plot_compare(
        STRATEGY_NAME, BENCHMARK_NAME, frames.cumulative, frames.drawdown,
        colors, output_dir, "momentum_vs_benchmark.png",
    )
    plot_compare(
        STRATEGY_NAME, EQUAL_WEIGHT_NAME, frames.cumulative, frames.drawdown,
        colors, output_dir, "momentum_vs_equal_weight.png",
    )
    plot_weights(frames.weights, STRATEGY_NAME, output_dir)
    print(tabulate(format_metrics_for_console(frames.metrics), headers="keys", tablefmt="grid", showindex=False))
    if frames.risk_summary is not None and not frames.risk_summary.empty:
        print("\n风控统计:")
        print(
            tabulate(
                frames.risk_summary.values.tolist(),
                headers=list(frames.risk_summary.columns),
                tablefmt="grid",
                showindex=False,
            )
        )
    if frames.risk_events is not None and not frames.risk_events.empty:
        print(f"\n风控事件 {len(frames.risk_events)} 条，明细见 {output_dir / 'risk_events.csv'}")
    print(f"数据源: DataHub/{args.data_source}")
    print(f"结果已保存到: {output_dir}")


if __name__ == "__main__":
    main()
