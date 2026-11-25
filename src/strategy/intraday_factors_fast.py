"""原分钟因子的等价矩阵实现，仅接受经过 normalize_bars 的完整240分钟日。"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd


def _moments(x):
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        var = np.nanvar(x, axis=1, ddof=1)
        centered = x - np.nanmean(x, axis=1, keepdims=True)
        skew = np.nanmean(centered ** 3, axis=1) / var ** 1.5
        kurt = np.nanmean(centered ** 4, axis=1) / var ** 2
    good = np.isfinite(var) & (var > 0)
    return var, np.where(good, skew, np.nan), np.where(good, kurt, np.nan)


def _corr(a, b):
    valid = ~np.isnan(a) & ~np.isnan(b)
    count = valid.sum(axis=1)
    with np.errstate(all="ignore"):
        ac = np.where(valid, a, 0).sum(axis=1) / count
        bc = np.where(valid, b, 0).sum(axis=1) / count
        aa = np.where(valid, a - ac[:, None], 0)
        bb = np.where(valid, b - bc[:, None], 0)
        den = np.sqrt((aa * aa).sum(axis=1) * (bb * bb).sum(axis=1))
        result = (aa * bb).sum(axis=1) / den
    # 与 Series.nunique 一致地排除常量，包括均值舍入造成的微小残差。
    constant = (
        np.nanmax(np.where(valid, a, np.nan), axis=1) == np.nanmin(np.where(valid, a, np.nan), axis=1)
    ) | (
        np.nanmax(np.where(valid, b, np.nan), axis=1) == np.nanmin(np.where(valid, b, np.nan), axis=1)
    )
    return np.where((count >= 3) & ~constant & (den > 0), np.clip(result, -1, 1), np.nan)


def daily_factors_fast(bars: pd.DataFrame) -> pd.DataFrame:
    """公式与 daily_factors 相同；成交量平局仍按时间先后，收益不跨日。"""
    if bars.empty:
        return pd.DataFrame()
    frame = bars.sort_values(["symbol", "datetime"]).copy()
    frame["date"] = pd.to_datetime(frame.datetime).dt.normalize()
    if frame.duplicated(["symbol", "datetime"]).any():
        raise ValueError("重复分钟")
    groups = frame.groupby(["symbol", "date"], sort=True)
    if not groups.size().eq(240).all():
        raise ValueError("矩阵实现只接受完整240分钟")
    minute = frame.datetime.dt.hour * 60 + frame.datetime.dt.minute
    expected = np.r_[np.arange(571, 691), np.arange(781, 901)]
    if not np.equal(minute.to_numpy().reshape(-1, 240), expected).all():
        raise ValueError("分钟标签不匹配")
    keys = groups.size().index.to_frame(index=False)
    p = frame.close.to_numpy(dtype=float).reshape(-1, 240)
    v = frame.volume.to_numpy(dtype=float).reshape(-1, 240)
    op = frame.open.to_numpy(dtype=float).reshape(-1, 240)[:, 0]
    good = (~np.isnan(p).any(axis=1) & ~np.isnan(v).any(axis=1)
            & (p > 0).all(axis=1) & (v >= 0).all(axis=1) & np.isfinite(op) & (op > 0))
    p, v, op = p[good], v[good], op[good]
    keys = keys.loc[good].reset_index(drop=True)
    if not len(keys):
        return pd.DataFrame()
    with np.errstate(all="ignore"):
        r = np.c_[np.full(len(p), np.nan), p[:, 1:] / p[:, :-1] - 1]
        lag = np.c_[np.full(len(p), np.nan), r[:, :-1]]
        lead = np.c_[r[:, 1:], np.full(len(p), np.nan)]
        var, skew, kurt = _moments(r)
        upvar = _moments(np.where(r > 0, r, np.nan))[0]
        downvar = _moments(np.where(r < 0, r, np.nan))[0]
        large = np.argsort(-v, axis=1, kind="stable")[:, :80]
        take = lambda a: np.take_along_axis(a, large, axis=1)
        vl, pl, rl = take(v), take(p), take(r)
        varl, skewl, kurtl = _moments(rl)
        varh, skewh, kurth = _moments(r[:, -30:])
        total = v.sum(axis=1)
        path = np.abs(np.diff(p, axis=1)).sum(axis=1)
        illiq = np.abs(r) / np.where(p * v == 0, np.nan, p * v)
        illiq[~np.isfinite(illiq)] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            illiq = np.nanmean(illiq, axis=1)
        ratio = lambda a, b: np.divide(a, b, out=np.full_like(a, np.nan), where=b > 0)
        row = dict(real_var=var, real_skew=skew, real_kurtosis=kurt,
                   real_upvar=upvar, real_downvar=downvar,
                   ratio_realupvar=ratio(upvar, var), ratio_realdownvar=ratio(downvar, var),
                   trendratio=ratio(p[:, -1] - p[:, 0], path),
                   intraday_maxdrawdown=(p / np.maximum.accumulate(p, axis=1) - 1).min(axis=1),
                   ret_intraday=p[:, -1] / op - 1,
                   ratio_volumeH8=ratio(v[:, -30:].sum(axis=1), total),
                   corr_VP=_corr(v, p), corr_VR=_corr(v, r),
                   corr_VRlag=_corr(v, lag), corr_VRlead=_corr(v, lead),
                   Amihud_illiq=illiq, ret_H8=p[:, -1] / p[:, -31] - 1,
                   corr_VPH8=_corr(v[:, -30:], p[:, -30:]),
                   corr_VRH8=_corr(v[:, -30:], r[:, -30:]),
                   corr_VRlagH8=_corr(v[:, -30:], lag[:, -30:]),
                   corr_VRleadH8=_corr(v[:, -30:], lead[:, -30:]),
                   real_varH8=varh, real_skewH8=skewh, real_kurtosisH8=kurth,
                   real_varlarge=varl, real_skewlarge=skewl, real_kurtosislarge=kurtl,
                   ratio_realvarlarge=ratio(varl, var),
                   corr_VPlarge=_corr(vl, pl), corr_VRlarge=_corr(vl, rl),
                   corr_VRleadlarge=_corr(vl, take(lead)),
                   corr_VRlaglarge=_corr(vl, take(lag)))
        for i in range(8):
            row[f"ratio_volumeH{i + 1}"] = ratio(v[:, i * 30:(i + 1) * 30].sum(axis=1), total)
    return pd.concat([keys, pd.DataFrame(row)], axis=1)
