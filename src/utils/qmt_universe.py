"""基于 Big QMT RPC 的全市场股票池快照服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

import pandas as pd

from .bigqmt_client import (
    BigQmtApiError,
    _call_redis_rpc,
    _create_redis_client,
    format_qmt_date,
    market_data_payload_to_ohlcv,
    normalize_qmt_symbol,
)


@dataclass(frozen=True)
class StockUniverseSnapshot:
    """Small2 选股所需的同一时点全市场元数据。"""

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
    """以可替换 RPC 调用封装 QMT 全市场元数据接口，便于离线测试。"""

    def __init__(
        self,
        account_id: str,
        timeout: float = 30.0,
        redis_client: Any | None = None,
        rpc_call: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if not account_id:
            raise ValueError("account_id 不能为空")
        self.account_id = account_id
        self.timeout = timeout
        self.client = redis_client or _create_redis_client()
        self.rpc_call = rpc_call or _call_redis_rpc

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        try:
            response = self.rpc_call(self.client, self.account_id, method, params, timeout_seconds=self.timeout)
        except Exception as exc:
            raise BigQmtApiError(f"Big QMT {method} 请求失败: {exc}") from exc
        if not response.get("ok"):
            raise BigQmtApiError(str(response.get("error") or f"Big QMT {method} 请求失败"))
        return response.get("data")

    def stock_codes(self, sector_name: str = "沪深A股") -> list[str]:
        """读取 QMT 板块成分股并规范化代码。"""
        data = self._call("get_stock_list_in_sector", {"sector_name": sector_name})
        if not isinstance(data, list):
            raise BigQmtApiError("get_stock_list_in_sector 返回格式错误")
        return [normalize_qmt_symbol(code) for code in data if isinstance(code, str) and code]

    def instrument_details(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        """逐只读取合约详情（名称、上市/退市日期）。"""
        return {
            code: data for code in codes
            if isinstance(data := self._call("get_instrument_detail", {"code": code}), dict)
        }

    def historical_st_codes(self, codes: list[str], as_of: date | str | pd.Timestamp) -> set[str]:
        """通过 ``get_his_st_data`` 判断目标日期是否处于 ST 区间。"""
        day = pd.Timestamp(as_of).normalize()
        result: set[str] = set()
        for code in codes:
            payload = self._call("get_his_st_data", {"stock_code": code})
            if self._is_st_on(payload, day):
                result.add(code)
        return result

    def daily_bars(self, codes: list[str], start_date: Any, end_date: Any) -> dict[str, pd.DataFrame]:
        """批量取得含成交额的日线；缺少目标日有效 bar 的股票应视为停牌。"""
        data = self._call(
            "get_market_data_ex",
            {
                "field_list": ["open", "high", "low", "close", "volume", "amount"],
                "stock_list": codes,
                "period": "1d",
                "start_time": format_qmt_date(start_date),
                "end_time": format_qmt_date(end_date),
                "count": -1,
                "dividend_type": "none",
                "fill_data": False,
            },
        )
        return {
            code: market_data_payload_to_ohlcv(data, code, ["open", "high", "low", "close", "volume", "amount"])
            for code in codes
        }

    def float_shares(self, codes: list[str], as_of: date | str | pd.Timestamp) -> dict[str, float]:
        """从 ``Capital.CAPITAL`` 提取流通股本，兼容常见字段命名。"""
        data = self._call(
            "get_financial_data",
            {"stock_list": codes, "table_list": ["Capital.CAPITAL"], "start_time": "", "end_time": format_qmt_date(as_of)},
        )
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
            data = data.get(code, data.get("Capital.CAPITAL", data))
        if isinstance(data, dict) and data.get("__bigqmt_type__") == "DataFrame":
            return pd.DataFrame(data.get("records", []))
        return pd.DataFrame(data if isinstance(data, list) else [data] if isinstance(data, dict) else [])

    @staticmethod
    def _extract_float_shares(frame: pd.DataFrame) -> float:
        for column in ("float_share", "float_shares", "float_share_capital", "circulating_share"):
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
