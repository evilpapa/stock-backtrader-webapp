"""微盘股指数与广度/资金流因子的重建（万得微盘 8841431.WI 在 Tushare 中不可得）。

规则假设（研报未披露成分细则，以下为复现假设）：
- 股票池：沪深 A 股，剔除北交所、ST/*ST、上市不足 ``min_listed_days`` 个交易日、前一交易日停牌；
- 成分：前一交易日总市值最小的 ``size`` 只，等权，逐日调整（t-1 选股、t 日计收益，无前视）；
- 价格：用 ``pct_chg`` 链式累乘得到复权价，避免除权跳变污染均线与广度。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data") / "micro_cap_timing_plus"


def _load_daily_files(api: str, columns: list[str], raw_dir: Path) -> pd.DataFrame:
    files = sorted((raw_dir / api).glob("*.parquet"))
    frames = [pd.read_parquet(path, columns=columns) for path in files]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True)


def load_raw_panels(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """读取缓存的原始数据并透视为 日期×股票 矩阵。"""
    raw = data_dir / "raw"
    daily = _load_daily_files(
        "daily", ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"], raw
    )
    basic = _load_daily_files("daily_basic", ["ts_code", "trade_date", "total_mv"], raw)
    flow = _load_daily_files(
        "moneyflow",
        ["ts_code", "trade_date", "net_mf_amount"],
        raw,
    )
    st = _load_daily_files("stock_st", ["ts_code", "trade_date"], raw)
    for frame in (daily, basic, flow, st):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    # 与研报“主力净流入”对账：Tushare 的 net_mf_amount 相关性 ~0.9，大单+超大单自算口径反而为负相关
    flow["main_net"] = flow["net_mf_amount"]
    st["is_st"] = True

    def pivot(frame: pd.DataFrame, column: str) -> pd.DataFrame:
        return frame.pivot(index="trade_date", columns="ts_code", values=column).sort_index()

    panels = {name: pivot(daily, name) for name in ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]}
    panels["total_mv"] = pivot(basic, "total_mv")
    panels["main_net"] = pivot(flow, "main_net")
    panels["is_st"] = pivot(st, "is_st").reindex(index=panels["close"].index, columns=panels["close"].columns).eq(True)
    return panels


def listing_matrix(index: pd.DatetimeIndex, columns: pd.Index, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """每只股票累计已上市交易日数矩阵，用于剔除次新股。"""
    basic = pd.read_parquet(data_dir / "reference" / "stock_basic.parquet").drop_duplicates("ts_code")
    listed = pd.to_datetime(basic.set_index("ts_code")["list_date"], errors="coerce").reindex(columns)
    filled = listed.fillna(pd.Timestamp("1990-01-01"))
    start_pos = index.searchsorted(filled.to_numpy())  # 首个不早于上市日的交易日位置
    # 早于样本起点的股票视为早已上市
    start_pos = np.where(filled.to_numpy() < index[0].to_datetime64(), -10_000, start_pos)
    return pd.DataFrame(np.arange(len(index))[:, None] - start_pos[None, :], index=index, columns=columns)


def select_constituents(panels: dict[str, pd.DataFrame], *, size: int = 400, min_listed_days: int = 60,
                        data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """返回 t 日收盘后选出的成分布尔矩阵（t+1 日起生效）。"""
    close = panels["close"]
    listed_days = listing_matrix(close.index, close.columns, data_dir)
    eligible = (
        close.notna()
        & (panels["vol"] > 0)
        & ~panels["is_st"]
        & (listed_days >= min_listed_days)
        & ~close.columns.str.endswith(".BJ")[None, :]
        & panels["total_mv"].notna()
    )
    rank = panels["total_mv"].where(eligible).rank(axis=1, method="first")
    return rank <= size


def build_micro_index(panels: dict[str, pd.DataFrame], members: pd.DataFrame, *, base: float = 1000.0
                      ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """由前一日成分等权合成指数 OHLC，并输出 t 日实际生效的成分矩阵。

    open/high 以成分的 open/high 相对前收的等权均值近似（真实指数高点 ≤ 该近似值）。
    """
    active = members.shift(1, fill_value=False)
    pre = panels["pre_close"]

    def ew(column: str) -> pd.Series:
        ret = (panels[column] / pre - 1).where(active)
        return ret.mean(axis=1)

    ret_close = (panels["pct_chg"] / 100).where(active).mean(axis=1)
    ret_open, ret_high, ret_low = ew("open"), ew("high"), ew("low")
    valid = active.sum(axis=1) > 0
    close = base * (1 + ret_close.where(valid, 0.0)).cumprod()
    prev = close.shift(1).fillna(base)
    index = pd.DataFrame(
        {"open": prev * (1 + ret_open), "high": prev * (1 + ret_high), "low": prev * (1 + ret_low), "close": close, "n": active.sum(axis=1)}
    )
    index["high"] = index[["high", "close", "open"]].max(axis=1)
    index["low"] = index[["low", "close", "open"]].min(axis=1)
    return index[valid], active


def build_factors(panels: dict[str, pd.DataFrame], active: pd.DataFrame, *, ma_window: int = 15) -> pd.DataFrame:
    """成分口径的扩散指数、资金流广度、主力净流入率（均为 t 日同步值）。"""
    adj = (1 + panels["pct_chg"].fillna(0) / 100).cumprod()
    adj = adj.where(panels["close"].notna())
    above = adj > adj.rolling(ma_window, min_periods=ma_window).mean()
    count = active.sum(axis=1).replace(0, np.nan)
    diffusion = (above & active).sum(axis=1) / count
    positive = panels["main_net"] > 0
    covered = (panels["main_net"].notna() & active).sum(axis=1).replace(0, np.nan)
    flow_breadth = (positive & active).sum(axis=1) / covered
    turnover_wan = panels["amount"].where(active).sum(axis=1) / 10  # 千元 -> 万元
    main_net_ratio = panels["main_net"].where(active).sum(axis=1) / turnover_wan.replace(0, np.nan)
    return pd.DataFrame(
        {"diffusion": diffusion, "flow_breadth": flow_breadth, "main_net_ratio": main_net_ratio}
    )
