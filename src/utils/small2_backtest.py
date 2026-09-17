"""Small2 的 QMT 数据装配与 Backtrader 回测入口。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import backtrader as bt
import pandas as pd

from src.strategy.small2 import Small2PandasData, Small2Strategy

from .qmt_universe import QmtUniverseClient, StockUniverseSnapshot


def build_small2_snapshots(
    client: QmtUniverseClient,
    rebalance_dates: list[date | str | pd.Timestamp],
    sector_name: str = "沪深A股",
) -> dict[pd.Timestamp, StockUniverseSnapshot]:
    """按调仓日构建并返回股票池快照；调用方可将结果持久化以复用 QMT 请求。"""
    return {
        pd.Timestamp(day).normalize(): client.snapshot(day, sector_name)
        for day in rebalance_dates
    }


def prepare_small2_price_data(
    client: QmtUniverseClient,
    snapshots: dict[pd.Timestamp, StockUniverseSnapshot],
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    lookback_days: int = 100,
    index_codes: tuple[str, str] = ("000852.SH", "000300.SH"),
) -> dict[str, pd.DataFrame]:
    """读取所有快照中的候选股票及市场指数日线，保留 ``amount`` 列。"""
    codes = set(index_codes)
    for snapshot in snapshots.values():
        codes.update(snapshot.stocks["code"].dropna().astype(str))
    start = pd.Timestamp(start_date).normalize() - timedelta(days=lookback_days * 2)
    return client.daily_bars(sorted(codes), start, end_date)


def run_small2_backtest(
    price_data: dict[str, pd.DataFrame],
    snapshots: dict[pd.Timestamp, StockUniverseSnapshot],
    initial_cash: float,
    strategy_params: dict[str, Any] | None = None,
    market_factors: pd.DataFrame | None = None,
) -> Small2Strategy:
    """使用已下载的行情与快照运行 Small2，返回策略实例供读取调仓记录。"""
    if not snapshots:
        raise ValueError("Small2 回测至少需要一个股票池快照")
    cerebro = bt.Cerebro()
    for code, frame in price_data.items():
        required = {"date", "open", "high", "low", "close", "volume", "amount"}
        if not required.issubset(frame.columns):
            continue
        data_frame = frame.copy().set_index(pd.to_datetime(frame["date"]))
        cerebro.adddata(Small2PandasData(dataname=data_frame), name=code)
    if not cerebro.datas:
        raise ValueError("Small2 回测没有可用的含 amount 日线数据")
    cerebro.broker.setcash(initial_cash)
    params = dict(strategy_params or {})
    params.update({"universe_snapshots": snapshots, "market_factors": market_factors})
    cerebro.addstrategy(Small2Strategy, **params)
    return cerebro.run()[0]
