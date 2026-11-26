"""Reproduce selected Huatai MA/SMA and Everbright RSRS index-timing rules."""

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from src.datahub import DataKind, DataRequest, ParquetRepository, create_service
from src.strategy_evaluation import evaluate_returns

SYMBOL = "000300.SH"
DATA_START, DATA_END = "2002-01-01", "2025-12-31"
MA_STRATEGIES = ("MA20", "SMA10_20")
RSRS_STRATEGIES = ("RSRS_slope", "RSRS_zscore")
PERIODS = (
    ("huatai", "2002-01-07", "2021-07-21", MA_STRATEGIES),
    ("everbright", "2005-03-01", "2017-04-30", RSRS_STRATEGIES),
    ("post_publication", "2022-01-01", DATA_END, MA_STRATEGIES + RSRS_STRATEGIES),
)


def load_bars(cache_dir: Path) -> tuple[pd.DataFrame, dict]:
    request = DataRequest(
        symbols=(SYMBOL,),
        start=DATA_START,
        end=DATA_END,
        frequency="1d",
        adjust="none",
        fields=("ts_code", "trade_date", "open", "high", "low", "close"),
    )
    service = create_service(repository=ParquetRepository(cache_dir))
    try:
        raw = service.get_cached(DataKind.INDEX_DAILY, request, source="tushare")
        if raw is None or raw.empty:
            raw = service.get(DataKind.INDEX_DAILY, request, persist=True)
    finally:
        service.close()
    if raw.empty or not raw["ts_code"].eq(SYMBOL).all():
        raise ValueError(f"缺少 {SYMBOL} 的指数日线")
    dates = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
    bars = raw.set_index(dates.rename("date"))[["open", "high", "low", "close"]].sort_index()
    close_history = bars.loc[:"2004-12-31", ["close"]]
    full_history = bars.loc["2005-01-01":]
    required_prices = np.concatenate([close_history.to_numpy().ravel(), full_history.to_numpy().ravel()])
    if bars.index.has_duplicates or not np.isfinite(required_prices).all() or (required_prices <= 0).any():
        raise ValueError("指数日线含重复日期、缺失值或无效价格")
    if bars.index[0] != pd.Timestamp("2002-01-04") or bars.index[-1] != pd.Timestamp(DATA_END):
        raise ValueError(f"指数日线覆盖不足：{bars.index[0].date()} 至 {bars.index[-1].date()}")
    metadata = {
        "symbol": SYMBOL,
        "source": raw.attrs["source"],
        "frequency": "1d",
        "adjust": "none",
        "data_version": raw.attrs["data_version"],
        "data_start": str(bars.index[0].date()),
        "data_end": str(bars.index[-1].date()),
        "bars": len(bars),
    }
    return bars, metadata


def threshold_position(score: pd.Series, buy_above: float, sell_below: float) -> pd.Series:
    orders = pd.Series(np.nan, index=score.index)
    orders.loc[score > buy_above] = 1.0
    orders.loc[score < sell_below] = 0.0
    return orders.ffill().fillna(0.0)


def build_signals(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = bars["close"]
    ma20 = close.rolling(20).mean()
    low_window = bars["low"].rolling(18)
    beta = low_window.cov(bars["high"]).div(low_window.var().replace(0, np.nan))
    past_beta = beta.shift(1).rolling(600, min_periods=2)
    zscore = (beta - past_beta.mean()).div(past_beta.std().replace(0, np.nan))
    indicators = pd.DataFrame({
        "MA20": close - ma20,
        "SMA10_20": close.rolling(10).mean() - ma20,
        "RSRS_slope": beta,
        "RSRS_zscore": zscore,
    })
    targets = pd.DataFrame({
        "MA20": threshold_position(indicators["MA20"], 0, 0),
        "SMA10_20": threshold_position(indicators["SMA10_20"], 0, 0),
        "RSRS_slope": threshold_position(beta, 1.0, 0.8),
        "RSRS_zscore": threshold_position(zscore, 0.7, -0.7),
        "buy_hold": 1.0,
    }, index=bars.index)
    return indicators, targets


def backtest_period(
    bars: pd.DataFrame, targets: pd.DataFrame, start: str, end: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    position = targets.shift(1, fill_value=0.0).loc[start:end]
    previous_position = position.shift(1, fill_value=0.0)
    sample = bars.loc[start:end]
    execution_price = sample["open"].fillna(sample["close"])
    before_execution = (execution_price / sample["close"].shift(1) - 1).fillna(0.0)
    after_execution = sample["close"] / execution_price - 1
    returns = (
        (1 + previous_position.mul(before_execution, axis=0))
        * (1 + position.mul(after_execution, axis=0))
        - 1
    )
    return returns, position


def summarize(returns: pd.Series, position: pd.Series) -> dict:
    evaluation = evaluate_returns(returns)
    return evaluation.metrics | evaluation.scoring | {
        "entries": int(position.diff().fillna(position).gt(0).sum()),
        "exits": int(position.diff().lt(0).sum()),
        "invested_fraction": float(position.mean()),
    }


def plot_nav(curves: dict[str, pd.DataFrame], path: Path) -> None:
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    colors = {
        "MA20": "#26798a",
        "SMA10_20": "#7e57a3",
        "RSRS_slope": "#b06a17",
        "RSRS_zscore": "#13745d",
        "buy_hold": "#6b7280",
    }
    titles = ("Huatai | MA signals", "Everbright | RSRS signals", "Post-publication | Fixed parameters")
    figure, axes = plt.subplots(3, 1, figsize=(10, 9), layout="constrained")
    for axis, nav, title in zip(axes, curves.values(), titles, strict=True):
        for name, series in nav.items():
            axis.plot(series, label=name, color=colors[name], linewidth=1.6)
        axis.axhline(1, color="#9ca3af", linewidth=0.7)
        axis.set(title=title, ylabel="Net asset value")
        axis.set_yscale("log")
        axis.grid(axis="y", color="#e5e7eb")
        axis.legend(loc="upper left", frameon=False, ncol=3)
    figure.savefig(path, dpi=140)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/index_timing_replication"))
    args = parser.parse_args()
    bars, metadata = load_bars(args.output_dir / "cache")
    indicators, targets = build_signals(bars)
    summaries, curves, daily_tables = {}, {}, []
    for name, start, end, strategies in PERIODS:
        columns = [*strategies, "buy_hold"]
        returns, position = backtest_period(bars, targets[columns], start, end)
        sample = bars.reindex(returns.index)
        nav = (1 + returns).cumprod()
        curves[name] = nav
        summaries[name] = {
            "start": str(returns.index[0].date()),
            "end": str(returns.index[-1].date()),
            "strategies": {key: summarize(returns[key], position[key]) for key in columns},
        }
        daily_tables.append(pd.concat(
            [
                sample.assign(execution_at=np.where(sample["open"].notna(), "open", "close")),
                indicators[list(strategies)].reindex(returns.index).add_prefix("indicator_"),
                targets[columns].reindex(returns.index).add_prefix("target_at_close_"),
                position.add_prefix("position_after_execution_"),
                returns.add_prefix("return_"),
                nav.add_prefix("nav_"),
            ],
            axis=1,
        ).assign(period=name, **metadata))

    summary = {"data": metadata, "periods": summaries}
    pd.concat(daily_tables).reset_index().to_parquet(args.output_dir / "daily.parquet", index=False)
    plot_nav(curves, args.output_dir / "nav.png")
    text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output_dir / "summary.json").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
