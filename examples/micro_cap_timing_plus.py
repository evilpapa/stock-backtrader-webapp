"""微盘股择时增强策略复现（华福证券 2026-08-11 研报）。

先缓存数据（Tushare 全市场日频，约 1 小时）：

    uv run python scripts/fetch_micro_cap_data.py
    uv run python examples/micro_cap_timing_plus.py

结果保存在 examples/micro_cap_timing_plus/。本脚本仅读取本地缓存并执行回测，不会下单。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.strategy.micro_cap_timing_plus import (
    MicroCapTimingParams,
    backtest,
    build_positions,
    compute_signals,
    performance,
)
from src.utils.micro_cap_data import (
    DATA_DIR,
    build_factors,
    build_micro_index,
    load_raw_panels,
    select_constituents,
)

OUTPUT_DIR = Path("examples") / "micro_cap_timing_plus"


def load_index_close(code: str, data_dir: Path = DATA_DIR) -> pd.Series:
    frame = pd.read_parquet(data_dir / "reference" / f"index_{code}.parquet")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")["close"].sort_index()


def build_dataset(*, size: int, min_listed_days: int, large_code: str, small_code: str | None):
    """重建微盘指数、因子与大小盘风格差；small_code 为空时以重建的微盘指数作“小盘”。"""
    panels = load_raw_panels()
    members = select_constituents(panels, size=size, min_listed_days=min_listed_days)
    index, active = build_micro_index(panels, members)
    factors = build_factors(panels, active).reindex(index.index)
    large = load_index_close(large_code).reindex(index.index)
    small = load_index_close(small_code).reindex(index.index) if small_code else index["close"]
    style_gap = large.pct_change(20, fill_method=None) - small.pct_change(20, fill_method=None)
    return index, factors, style_gap, members


def summarize(index: pd.DataFrame, signals: pd.DataFrame, params: MicroCapTimingParams, start: str, end: str):
    variants = {
        "买入持有": pd.Series(1.0, index=signals.index),
        "MA15": build_positions(signals, params, use_bottom=False, use_top=False),
        "MA15+底部": build_positions(signals, params, use_bottom=True, use_top=False),
        "MA15+顶部": build_positions(signals, params, use_bottom=False, use_top=True),
        "MA15+底部+顶部": build_positions(signals, params),
    }
    returns, rows = {}, {}
    for name, position in variants.items():
        ret = backtest(index, position, params.cost).loc[start:end]
        returns[name] = ret
        rows[name] = performance(ret) | {"持仓天数占比": position.loc[start:end].mean()}
    return pd.DataFrame(rows).T, pd.DataFrame(returns), variants


def main() -> None:
    parser = argparse.ArgumentParser(description="微盘股择时增强策略复现")
    parser.add_argument("--start", default="2016-01-04")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--size", type=int, default=400, help="微盘成分数量")
    parser.add_argument("--min-listed-days", type=int, default=60)
    parser.add_argument("--large-code", default="000300.SH")
    parser.add_argument("--small-code", default="932000.CSI", help="小盘对照指数（与研报风格差对账后取中证2000）")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    params = MicroCapTimingParams()
    index, factors, style_gap, _ = build_dataset(
        size=args.size, min_listed_days=args.min_listed_days, large_code=args.large_code, small_code=args.small_code
    )
    signals = compute_signals(index, factors, style_gap, params)
    metrics, returns, variants = summarize(index, signals, params, args.start, args.end)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    index.to_csv(args.output_dir / "micro_cap_index.csv")
    signals.assign(position=variants["MA15+底部+顶部"]).to_csv(args.output_dir / "signals.csv")
    metrics.to_csv(args.output_dir / "performance_metrics.csv")
    (1 + returns).cumprod().to_csv(args.output_dir / "cumulative_returns.csv")
    pd.set_option("display.float_format", "{:.4f}".format)
    print(metrics)
    print("底部/危机/顶部信号触发日数:", int(signals["bottom"].sum()), int(signals["crisis"].sum()), int(signals["top"].sum()))


if __name__ == "__main__":
    main()
