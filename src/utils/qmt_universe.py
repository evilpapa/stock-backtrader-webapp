"""基于原生 ``xtquant.xtdata`` 的全市场股票池快照服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .bigqmt_client import (
    QmtDataClient,
    normalize_qmt_symbol,
)


@dataclass(frozen=True)
class StockUniverseSnapshot:
    """Small_Cap 选股所需的同一时点全市场元数据。"""

    as_of: pd.Timestamp
    stocks: pd.DataFrame

    REQUIRED_COLUMNS = (
        "code", "name", "listing_date", "is_st", "is_suspended", "is_delisted",
        "float_market_cap", "float_shares",
    )

    def eligible_codes(
        self,
        listing_days: int,
        min_cap: float,
        max_cap: float,
        main_board_only: bool = True,
    ) -> list[str]:
        """应用 qb/small2 的基础股票池过滤规则。市值单位为亿元。"""
        frame = self.stocks.copy()
        missing = set(self.REQUIRED_COLUMNS).difference(frame.columns)
        if missing:
            raise ValueError(f"股票池快照缺少字段: {', '.join(sorted(missing))}")
        listing_date = pd.to_datetime(frame["listing_date"], errors="coerce")
        age_days = (self.as_of.normalize() - listing_date.dt.normalize()).dt.days
        keep = (
            frame["code"].notna()
            & ~frame["is_st"].fillna(True)
            & ~frame["is_suspended"].fillna(True)
            & ~frame["is_delisted"].fillna(True)
            & age_days.ge(listing_days)
            & frame["float_market_cap"].between(min_cap, max_cap)
        )
        if main_board_only:
            keep &= ~frame["code"].str.startswith(("688", "30", "4", "8", "9"), na=True)
        return frame.loc[keep].sort_values("float_market_cap")["code"].tolist()


class QmtUniverseClient:
    """通过原生 ``xtquant.xtdata`` 读取 QMT 全市场元数据。"""

    def __init__(
        self,
        timeout: float = 30.0,
        xtdata_client: Any | None = None,
    ) -> None:
        self.timeout = timeout
        self.data_client = QmtDataClient(timeout=timeout, xtdata_client=xtdata_client)
        self.xtdata = self.data_client.xtdata

    def stock_codes(self, sector_name: str = "沪深A股") -> list[str]:
        """读取 QMT 板块成分股并规范化代码。"""
        return [
            normalize_qmt_symbol(code)
            for code in self.data_client.stock_list_in_sector(sector_name)
            if isinstance(code, str) and code
        ]

    def instrument_details(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        """逐只读取合约详情（名称、上市/退市日期）。"""
        details = {}
        for code in codes:
            data = self.data_client.instrument_detail(code, is_detail=True)
            if isinstance(data, dict):
                details[code] = data
        return details

    def historical_st_codes(self, codes: list[str], as_of: date | str | pd.Timestamp) -> set[str]:
        """通过 ``get_his_st_data`` 判断目标日期是否处于 ST 区间。"""
        day = pd.Timestamp(as_of).normalize()
        result: set[str] = set()
        for code in codes:
            payload = self.data_client.historical_st_data(code)
            if self._is_st_on(payload, day):
                result.add(code)
        return result

    def daily_bars(self, codes: list[str], start_date: Any, end_date: Any) -> dict[str, pd.DataFrame]:
        """批量取得含成交额的日线；缺少目标日有效 bar 的股票应视为停牌。"""
        return self.data_client.daily_bars(codes, start_date, end_date)

    def float_shares(self, codes: list[str], as_of: date | str | pd.Timestamp) -> dict[str, float]:
        """从 ``Capital`` 提取流通股本，兼容常见字段命名。"""
        data = self.data_client.financial_data(codes, tables=["Capital"], end_date=as_of)
        return {code: self._extract_float_shares(self._financial_frame(data, code)) for code in codes}

    def snapshot(
        self,
        as_of: date | str | pd.Timestamp,
        sector_name: str = "沪深A股",
        codes: list[str] | None = None,
    ) -> StockUniverseSnapshot:
        """构建 Small2 所需快照；市值以亿元表示。

        ``codes`` 用于冒烟测试或分批构建缓存；省略时读取完整板块股票池。
        """
        day = pd.Timestamp(as_of).normalize()
        codes = [normalize_qmt_symbol(code) for code in codes] if codes is not None else self.stock_codes(sector_name)
        details = self.instrument_details(codes)
        st_codes = self.historical_st_codes(codes, day)
        missing_share_codes = [code for code in codes if not pd.notna(self._detail_float_shares(details.get(code, {})))]
        financial_shares = self.float_shares(missing_share_codes, day) if missing_share_codes else {}
        bars = self.daily_bars(codes, day, day)
        rows = []
        for code in codes:
            detail = details.get(code, {})
            bar = bars.get(code, pd.DataFrame())
            close = float(bar["close"].iloc[-1]) if not bar.empty else float("nan")
            volume = float(bar["volume"].iloc[-1]) if not bar.empty else 0.0
            float_share = self._detail_float_shares(detail)
            if not pd.notna(float_share) or float_share <= 0:
                float_share = financial_shares.get(code, float("nan"))
            rows.append(
                {
                    "code": code,
                    "name": detail.get("InstrumentName") or detail.get("name") or "",
                    "listing_date": self._detail_date(detail, "OpenDate", "listing_date", "list_date"),
                    "delisting_date": self._detail_date(detail, "ExpireDate", "delisting_date", "delist_date"),
                    "is_st": code in st_codes or "ST" in str(detail.get("InstrumentName") or detail.get("name") or "").upper(),
                    "is_suspended": bar.empty or volume <= 0 or not pd.notna(close),
                    "is_delisted": self._is_delisted(detail, day),
                    "float_shares": float_share,
                    "float_market_cap": close * float_share / 1e8,
                }
            )
        return StockUniverseSnapshot(day, pd.DataFrame(rows))

    @staticmethod
    def _financial_frame(data: Any, code: str) -> pd.DataFrame:
        if isinstance(data, dict):
            data = data.get(code, data.get("Capital", data.get("Capital.CAPITAL", data)))
            if isinstance(data, dict):
                data = data.get("Capital", data.get("Capital.CAPITAL", data))
        if isinstance(data, pd.DataFrame):
            return data.copy()
        if isinstance(data, dict) and data.get("__bigqmt_type__") == "DataFrame":
            return pd.DataFrame(data.get("records", []))
        return pd.DataFrame(data if isinstance(data, list) else [data] if isinstance(data, dict) else [])

    @staticmethod
    def _extract_float_shares(frame: pd.DataFrame) -> float:
        for column in (
            "float_share", "float_shares", "float_share_capital",
            "circulating_share", "circulating_capital",
        ):
            if column in frame.columns:
                values = pd.to_numeric(frame[column], errors="coerce").dropna()
                if not values.empty and values.iloc[-1] > 0:
                    return float(values.iloc[-1])
        return float("nan")

    @staticmethod
    def _detail_float_shares(detail: dict[str, Any]) -> float:
        for key in ("FloatVolume", "FloatVolumn", "float_volume", "float_share"):
            value = pd.to_numeric(detail.get(key), errors="coerce")
            if pd.notna(value) and value > 0:
                return float(value)
        return float("nan")

    @staticmethod
    def _detail_date(detail: dict[str, Any], *keys: str) -> pd.Timestamp:
        for key in keys:
            if key not in detail:
                continue
            value = detail[key]
            # QMT 合约详情的 OpenDate/ExpireDate 是 YYYYMMDD 整数；直接交给
            # pandas 会被解释为纳秒时间戳，必须先按日期文本解析。
            text = str(int(value)) if isinstance(value, (int, float)) and pd.notna(value) else str(value)
            parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
            if pd.isna(parsed):
                parsed = pd.to_datetime(value, errors="coerce")
            if pd.notna(parsed):
                return parsed
        return pd.NaT

    @staticmethod
    def _is_delisted(detail: dict[str, Any], as_of: pd.Timestamp) -> bool:
        for key in ("ExpireDate", "delisting_date", "delist_date"):
            value = detail.get(key)
            if str(value).split(".", maxsplit=1)[0] in {"", "0", "99999999"}:
                continue
            date_value = QmtUniverseClient._detail_date({key: value}, key)
            if pd.notna(date_value):
                return bool(date_value.normalize() <= as_of)
        return False

    @staticmethod
    def _is_st_on(payload: Any, day: pd.Timestamp) -> bool:
        if isinstance(payload, bool):
            return payload
        frame = pd.DataFrame(payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else [])
        if frame.empty:
            return False
        if "is_st" in frame.columns:
            return bool(frame["is_st"].fillna(False).iloc[-1])
        start_column = next((name for name in ("start_date", "begin_date") if name in frame.columns), None)
        end_column = next((name for name in ("end_date", "end_time") if name in frame.columns), None)
        if start_column is not None:
            start = pd.to_datetime(frame[start_column], errors="coerce")
            end = pd.to_datetime(frame[end_column], errors="coerce") if end_column is not None else pd.Series(pd.NaT, index=frame.index)
            return bool(((start <= day) & (end.isna() | (end >= day))).any())
        return bool(frame.get("st", pd.Series(False)).fillna(False).any())
