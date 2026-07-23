"""Helpers for loading OHLCV data with AKShare (Sina backend).

替代原先的 xtquant/miniQMT 数据源，使用 AKShare 的新浪接口获取 A股/ETF 行情。
- 股票：ak.stock_zh_a_daily (支持前复权/后复权)
- ETF：ak.fund_etf_hist_sina
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# 标准输出字段列表
DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]


class AkShareDataError(RuntimeError):
    """Raised when AKShare cannot return usable market-data payload."""


def _is_etf(symbol: str) -> bool:
    """通过代码前缀自动判断是否为 ETF。"""
    code = symbol.strip().upper().rstrip(".SH").rstrip(".SZ").rstrip(".BJ")
    return bool(code) and code[0] in ("1", "5")


def _to_akshare_symbol(symbol: str) -> str:
    """将 6 位代码或 xtdata 格式代码转换为 sh/sz 前缀格式。"""
    code = symbol.strip().upper()
    # 去掉 .SH/.SZ/.BJ 后缀
    for suffix in (".SH", ".SZ", ".BJ"):
        if code.endswith(suffix):
            code = code[: -len(suffix)]
            market = suffix[1:].lower()  # sh / sz / bj
            break
    else:
        # 根据代码首位自动判断市场
        if code.startswith(("5", "6", "9")):
            market = "sh"
        elif code.startswith(("0", "1", "2", "3")):
            market = "sz"
        elif code.startswith(("4", "8")):
            market = "bj"
        else:
            market = "sz"  # 兜底
    return f"{market}{code}"


def _format_date(value: Any) -> str:
    """统一转为 YYYY-MM-DD 格式。"""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value).replace("-", "").replace("/", "-")


def _normalize_dividend_type(value: str | None) -> str:
    """将 xtdata 风格的复权参数映射为 AKShare 风格。"""
    mapping = {
        None: "qfq",
        "": "",
        "none": "",
        "qfq": "qfq",
        "hfq": "hfq",
        "front": "qfq",
        "back": "hfq",
        "front_ratio": "qfq",
        "back_ratio": "hfq",
    }
    key = value.lower() if isinstance(value, str) else value
    return mapping.get(key, "qfq")


def fetch_history_ohlcv(
    symbol: str,
    start_date: Any,
    end_date: Any,
    period: str = "1d",
    dividend_type: str = "front",
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """
    获取历史 K 线数据，返回包含 date/open/high/low/close/volume 列的 DataFrame。

    使用 AKShare（新浪数据源），自动识别股票/ETF 并调用对应接口。
    - 股票：stock_zh_a_daily，支持复权参数
    - ETF：fund_etf_hist_sina，原生数据

    ohlcv 代表：Open High Low Close Volume / 开盘价 最高价 最低价 收盘价 成交量
    """
    import akshare as ak

    if period != "1d":
        raise AkShareDataError(f"AKShare 版暂不支持周期: {period}，仅支持日线(1d)")

    start = _format_date(start_date)
    end = _format_date(end_date)
    ak_symbol = _to_akshare_symbol(symbol)

    try:
        if _is_etf(symbol):
            df = _fetch_etf_data(ak, ak_symbol, start, end)
        else:
            df = _fetch_stock_data(ak, ak_symbol, start, end, dividend_type)
    except Exception as exc:
        raise AkShareDataError(
            f"AKShare 获取数据失败 ({symbol}): {exc}"
        ) from exc

    field_list = fields or DEFAULT_OHLCV_FIELDS
    available = [c for c in field_list if c in df.columns]
    if not available:
        raise AkShareDataError(f"AKShare 返回数据缺少所有行情列: {field_list}")

    result = df[["date", *available]].copy()
    result = result.dropna(subset=["date"] + available).sort_values("date").reset_index(drop=True)
    return result


def _fetch_stock_data(ak: Any, ak_symbol: str, start: str, end: str, dividend_type: str) -> pd.DataFrame:
    """使用 stock_zh_a_daily 获取股票数据（支持复权），失败时回退到 fund_etf_hist_sina。"""
    adj = _normalize_dividend_type(dividend_type)
    try:
        df = ak.stock_zh_a_daily(
            symbol=ak_symbol,
            adjust=adj,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
        )
    except Exception:
        df = pd.DataFrame()

    if df.empty or "date" not in df.columns:
        # fallback: fund_etf_hist_sina 也支持股票
        return _fetch_etf_data(ak, ak_symbol, start, end)

    # 保留必要列
    columns = {"date", "open", "high", "low", "close", "volume"}
    keep = [c for c in df.columns if c in columns]
    if "date" not in df.columns:
        df = df.reset_index()
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _fetch_etf_data(ak: Any, ak_symbol: str, start: str, end: str) -> pd.DataFrame:
    """使用 fund_etf_hist_sina 获取 ETF 数据。"""
    df = ak.fund_etf_hist_sina(symbol=ak_symbol)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    # 按日期过滤
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
    # 保留必要列
    keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].copy()


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    """将日期和行情列名转为中文，用于 Streamlit 界面展示。"""
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.rename(
        columns={
            "date": "日期",
            "open": "开盘",
            "close": "收盘",
            "high": "最高",
            "low": "最低",
            "volume": "成交量",
        }
    )[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]


def to_title_case_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    """
    将列名转为 Open/High/Low/Close/Volume 格式，
    保持与 Backtrader 兼容。
    """
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"])
    return frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )[["Open", "High", "Low", "Close", "Volume"]]
