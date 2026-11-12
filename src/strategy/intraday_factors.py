"""广发多因子 41 中可由连续竞价分钟行情构造的部分因子。

输入为 DataHub 标准化、分钟末时间戳的 1m 行情；不推算集合竞价因子。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _moments(r: pd.Series) -> tuple[float, float, float]:
    r = r.dropna()
    if len(r) < 2:
        return np.nan, np.nan, np.nan
    var = r.var(ddof=1)
    if not np.isfinite(var) or var <= 0:
        return var, np.nan, np.nan
    centered = r - r.mean()
    return var, (centered ** 3).mean() / var ** 1.5, (centered ** 4).mean() / var ** 2


def _corr(a: pd.Series, b: pd.Series) -> float:
    pair = pd.concat([a, b], axis=1).dropna()
    if len(pair) < 3 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return np.nan
    return float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))


def daily_factors(bars: pd.DataFrame, *, min_bars: int = 240) -> pd.DataFrame:
    """计算报告中 39 个由连续竞价分钟数据构造的因子。

    缺少完整分钟线的日子默认排除。大成交量按日内成交量最高的 1/3 分钟
    选取，收益率始终使用原始相邻分钟，成交量平局按时间顺序打破。
    """
    needed = {"symbol", "datetime", "open", "close", "volume"}
    if not needed.issubset(bars.columns):
        raise ValueError(f"缺少字段: {sorted(needed - set(bars.columns))}")
    frame = bars.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    if frame["datetime"].dt.tz is not None:
        frame["datetime"] = frame["datetime"].dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    frame = frame.sort_values(["symbol", "datetime"])
    if frame.duplicated(["symbol", "datetime"]).any():
        raise ValueError("重复的证券分钟时间戳")
    frame["date"] = frame["datetime"].dt.normalize()
    minute = frame["datetime"].dt.hour * 60 + frame["datetime"].dt.minute
    frame = frame[((minute >= 571) & (minute <= 690)) | ((minute >= 781) & (minute <= 900))]
    rows = []
    for (symbol, date), g in frame.groupby(["symbol", "date"], sort=True):
        if len(g) < min_bars:
            continue
        p = pd.to_numeric(g["close"], errors="coerce").reset_index(drop=True)
        v = pd.to_numeric(g["volume"], errors="coerce").reset_index(drop=True)
        op = pd.to_numeric(g["open"], errors="coerce").iloc[0]
        if p.isna().any() or v.isna().any() or (p <= 0).any() or (v < 0).any() or not np.isfinite(op) or op <= 0:
            continue
        r = p.pct_change(fill_method=None)
        var, skew, kurt = _moments(r)
        large = v.sort_values(ascending=False, kind="stable").index[:len(v) // 3]
        var_large, skew_large, kurt_large = _moments(r.loc[large])
        tail = g["datetime"].dt.hour.to_numpy() * 60 + g["datetime"].dt.minute.to_numpy() > 870
        last = np.flatnonzero(tail)
        illiq = (r.abs() / (p * v).replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).mean()
        upvar = r[r > 0].var(ddof=1)
        downvar = r[r < 0].var(ddof=1)
        path = p.diff().abs().sum()
        tail_r = r.iloc[last]
        tail_var, tail_skew, tail_kurt = _moments(tail_r)
        row = {"symbol": symbol, "date": date, "real_var": var, "real_skew": skew,
                     "real_kurtosis": kurt, "real_upvar": upvar, "real_downvar": downvar,
                     "ratio_realupvar": upvar / var if var > 0 else np.nan,
                     "ratio_realdownvar": downvar / var if var > 0 else np.nan,
                     "trendratio": (p.iloc[-1] - p.iloc[0]) / path if path else np.nan,
                     "intraday_maxdrawdown": (p / p.cummax() - 1).min(),
                     "ret_intraday": p.iloc[-1] / op - 1,
                     "ratio_volumeH8": v.iloc[last].sum() / v.sum() if v.sum() else np.nan,
                     "corr_VP": _corr(v, p), "corr_VR": _corr(v, r),
                     "corr_VRlag": _corr(v, r.shift(1)), "corr_VRlead": _corr(v, r.shift(-1)),
                     "Amihud_illiq": illiq,
                     "ret_H8": p.iloc[-1] / p.iloc[last[0] - 1] - 1 if len(last) and last[0] else np.nan,
                     "corr_VPH8": _corr(v.iloc[last], p.iloc[last]),
                     "corr_VRH8": _corr(v.iloc[last], r.iloc[last]),
                     "corr_VRlagH8": _corr(v.iloc[last], r.shift(1).iloc[last]),
                     "corr_VRleadH8": _corr(v.iloc[last], r.shift(-1).iloc[last]),
                     "real_varH8": tail_var, "real_skewH8": tail_skew, "real_kurtosisH8": tail_kurt,
                     "real_varlarge": var_large, "real_skewlarge": skew_large,
                     "real_kurtosislarge": kurt_large,
                     "ratio_realvarlarge": var_large / var if var > 0 else np.nan,
                     "corr_VPlarge": _corr(v.loc[large], p.loc[large]),
                     "corr_VRlarge": _corr(v.loc[large], r.loc[large]),
                     "corr_VRleadlarge": _corr(v.loc[large], r.shift(-1).loc[large]),
                     "corr_VRlaglarge": _corr(v.loc[large], r.shift(1).loc[large])}
        for i in range(8):
            row[f"ratio_volumeH{i + 1}"] = v.iloc[i * 30:(i + 1) * 30].sum() / v.sum() if v.sum() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def smooth_factors(factors: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """对每只股票连续已有日因子做 MA，调用方须先检查交易日缺失。"""
    if window < 1:
        raise ValueError("window 必须为正整数")
    result = factors.sort_values(["symbol", "date"]).copy()
    columns = [c for c in result.columns if c not in ("symbol", "date")]
    result[columns] = result.groupby("symbol", sort=False)[columns].transform(lambda x: x.rolling(window, min_periods=window).mean())
    return result
