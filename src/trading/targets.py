"""Validated strategy signals shared by exporters, replay and live execution.

An empty symbol with zero weight represents an explicit all-cash rebalance.
Absence of a date means no rebalance; it must never imply liquidation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.datahub.ticker import TickerMapper
from .models import iso_day

TARGET_COLUMNS = ["signal_date", "trade_date", "symbol", "target_weight"]


def validate_targets(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(TARGET_COLUMNS) - set(frame)
    if missing:
        raise ValueError(f"missing target columns: {sorted(missing)}")
    frame = frame.copy()
    if "strategy_id" in frame and (frame.strategy_id.isna().any()
            or frame.strategy_id.astype(str).str.strip().eq("").any()
            or frame.strategy_id.nunique() != 1):
        raise ValueError("one nonempty strategy_id per target file is required")
    if frame.empty:
        raise ValueError("no target portfolios")
    for column in ("signal_date", "trade_date"):
        dates = pd.to_datetime(frame[column], errors="raise")
        if dates.isna().any():
            raise ValueError("missing target date")
        frame[column] = dates.dt.strftime("%Y-%m-%d")
    frame["symbol"] = frame.symbol.fillna("").map(
        lambda value: TickerMapper.normalize(str(value)) if str(value).strip() else "")
    frame["target_weight"] = pd.to_numeric(frame.target_weight, errors="raise")
    if (not frame.signal_date.lt(frame.trade_date).all()
            or not frame.target_weight.between(0, 1).all()):
        raise ValueError("invalid target dates/weights")
    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("duplicate target/date")
    for _, group in frame.groupby("trade_date", sort=False):
        if group.signal_date.nunique() != 1 or group.target_weight.sum() > 1 + 1e-8:
            raise ValueError("invalid rebalance target")
        cash = group.symbol.eq("")
        if cash.any() and (len(group) != 1 or group.target_weight.iloc[0] != 0):
            raise ValueError("cash rebalance must be a single empty symbol with zero weight")
    return frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def target_weights(frame: pd.DataFrame) -> dict[str, float]:
    """Read one validated portfolio, including the explicit all-cash marker."""
    frame = validate_targets(frame)
    if frame.trade_date.nunique() != 1:
        raise ValueError("select exactly one trade date")
    return {row.symbol: float(row.target_weight) for row in frame.itertuples()
            if row.symbol and row.target_weight > 0}


@dataclass(frozen=True)
class TargetPortfolio:
    strategy_id: str
    signal_date: str
    trade_date: str
    weights: Mapping[str, float]

    def to_frame(self) -> pd.DataFrame:
        if not self.strategy_id or not self.strategy_id.strip():
            raise ValueError("strategy_id is required")
        signal, trade = iso_day(self.signal_date), iso_day(self.trade_date)
        rows = [{"signal_date": signal, "trade_date": trade,
                 "symbol": symbol, "target_weight": weight}
                for symbol, weight in self.weights.items()]
        if not rows:
            rows = [{"signal_date": signal, "trade_date": trade,
                     "symbol": "", "target_weight": 0.}]
        frame = validate_targets(pd.DataFrame(rows))
        frame["strategy_id"] = self.strategy_id
        return frame

    def execute(self, engine, quotes, *, now):
        if engine.strategy_id != self.strategy_id:
            raise ValueError("signal strategy differs from execution portfolio")
        return engine.rebalance(target_weights(self.to_frame()), quotes,
                                signal_date=self.signal_date, trade_date=self.trade_date, now=now)


def write_targets(portfolios, path: str | Path) -> pd.DataFrame:
    frames = [portfolio.to_frame() for portfolio in portfolios]
    if not frames:
        raise ValueError("no target portfolios")
    frame = pd.concat(frames, ignore_index=True)
    if frame.strategy_id.nunique() != 1:
        raise ValueError("one strategy per target file is required")
    frame = validate_targets(frame)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame
