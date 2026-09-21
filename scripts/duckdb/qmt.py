"""Small, testable wrapper around the Big QMT Redis RPC contract."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.bigqmt_client import (
    BigQmtApiError,
    get_xtdata,
    format_qmt_date,
    market_data_payload_to_frame,
    market_data_payload_to_ohlcv,
)


DAILY_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
REQUIRED_DAILY_FIELDS = ["open", "high", "low", "close", "volume"]
TICK_FIELDS = ["lastPrice", "volume", "amount", "bidPrice", "askPrice", "bidVol", "askVol"]
INTRADAY_PERIODS = {"1m", "5m", "15m", "30m", "60m"}


class QmtRpcError(RuntimeError):
    """A QMT request failed or returned an unusable payload."""


class QmtRpc:
    def __init__(
        self,
        account_id: str,
        *,
        timeout: float = 30.0,
        xtdata_client: Any | None = None,
    ) -> None:
        if not account_id:
            raise ValueError("BIGQMT_ACCOUNT_ID 不能为空")
        self.account_id = account_id
        self.timeout = timeout
        self.xtdata = xtdata_client or get_xtdata(account_id=account_id, timeout=timeout)

    def call(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return getattr(self.xtdata, method)(**params)
        except Exception as exc:
            raise QmtRpcError(f"Big QMT {method} 请求失败: {exc}") from exc

    def daily_bars(
        self,
        symbols: list[str],
        start_date: Any,
        end_date: Any,
        *,
        dividend_type: str = "none",
        download_missing: bool = False,
    ) -> dict[str, pd.DataFrame]:
        params = {
            "field_list": DAILY_FIELDS,
            "stock_list": symbols,
            "period": "1d",
            "start_time": format_qmt_date(start_date),
            "end_time": format_qmt_date(end_date),
            "count": -1,
            "dividend_type": dividend_type,
            "fill_data": False,
            "timeout_seconds": self.timeout,
        }
        data = self.call("get_market_data_ex", params)
        result = self._parse_daily_payload(data, symbols)
        if download_missing and not any(not frame.empty for frame in result.values()):
            self.call(
                "download_history_data2",
                {
                    "stock_list": symbols,
                    "period": "1d",
                    "start_time": format_qmt_date(start_date),
                    "end_time": format_qmt_date(end_date),
                },
            )
            data = self.call("get_market_data_ex", params)
            result = self._parse_daily_payload(data, symbols)
        return result

    def market_bars(
        self,
        symbols: list[str],
        start_date: Any,
        end_date: Any,
        *,
        period: str = "1d",
        dividend_type: str = "none",
        download_missing: bool = False,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily, intraday, or tick data in one normalized shape."""
        if period not in {"1d", *INTRADAY_PERIODS, "tick"}:
            raise ValueError(f"不支持的 QMT 周期: {period}")
        fields = TICK_FIELDS if period == "tick" else DAILY_FIELDS
        params = {
            "field_list": fields,
            "stock_list": symbols,
            "period": period,
            "start_time": format_qmt_date(start_date),
            "end_time": format_qmt_date(end_date),
            "count": -1,
            "dividend_type": dividend_type,
            "fill_data": False,
            "timeout_seconds": self.timeout,
        }
        data = self.call("get_market_data_ex", params)
        result = self._parse_market_payload(data, symbols, fields, period)
        if download_missing and not any(not frame.empty for frame in result.values()):
            self.call(
                "download_history_data2",
                {
                    "stock_list": symbols,
                    "period": period,
                    "start_time": format_qmt_date(start_date),
                    "end_time": format_qmt_date(end_date),
                },
            )
            data = self.call("get_market_data_ex", params)
            result = self._parse_market_payload(data, symbols, fields, period)
        return result

    @staticmethod
    def _parse_market_payload(
        data: Any,
        symbols: list[str],
        fields: list[str],
        period: str,
    ) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            try:
                frame = market_data_payload_to_frame(
                    data,
                    symbol,
                    fields,
                    numeric_fields=fields,
                )
            except BigQmtApiError as exc:
                if "amount" not in fields or "amount" not in str(exc):
                    result[symbol] = pd.DataFrame(columns=["date", *fields])
                    continue
                fallback_fields = [field for field in fields if field != "amount"]
                try:
                    frame = market_data_payload_to_frame(
                        data,
                        symbol,
                        fallback_fields,
                        numeric_fields=fallback_fields,
                    )
                except BigQmtApiError:
                    result[symbol] = pd.DataFrame(columns=["date", *fields])
                    continue
                frame["amount"] = float("nan")
            frame = frame.rename(columns={
                "lastPrice": "last",
                "bidPrice": "bid",
                "askPrice": "ask",
                "bidVol": "bid_volume",
                "askVol": "ask_volume",
            })
            for column in ["open", "high", "low", "close", "last", "volume", "amount", "bid", "ask", "bid_volume", "ask_volume"]:
                if column not in frame.columns:
                    frame[column] = float("nan")
            frame["bar_time"] = pd.to_datetime(frame.pop("date"), errors="coerce").dt.normalize() if period == "1d" else pd.to_datetime(frame.pop("date"), errors="coerce")
            result[symbol] = frame[
                [
                    "bar_time", "open", "high", "low", "close", "last", "volume", "amount",
                    "bid", "ask", "bid_volume", "ask_volume",
                ]
            ]
        return result

    def sector_list(self, *, allow_fallback: bool = True) -> list[str]:
        """Return QMT sector names, explicitly opting into the broker fallback list."""
        data = self.call("get_sector_list", {"allow_fallback": allow_fallback})
        if isinstance(data, dict):
            data = data.get("sectors", data.get("data", data))
        if not isinstance(data, list):
            raise QmtRpcError("get_sector_list 返回格式错误")
        return sorted(str(item) for item in data if item)

    def _parse_daily_payload(self, data: Any, symbols: list[str]) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            try:
                result[symbol] = market_data_payload_to_ohlcv(data, symbol, DAILY_FIELDS)
            except BigQmtApiError as exc:
                # Some QMT builds omit amount for non-equity instruments. Keep the
                # bar instead of losing the whole batch, with a nullable amount.
                if "amount" not in str(exc):
                    result[symbol] = pd.DataFrame(columns=["date", *DAILY_FIELDS])
                    continue
                try:
                    frame = market_data_payload_to_ohlcv(data, symbol, REQUIRED_DAILY_FIELDS)
                except BigQmtApiError as fallback_exc:
                    result[symbol] = pd.DataFrame(columns=["date", *DAILY_FIELDS])
                    continue
                frame["amount"] = float("nan")
                result[symbol] = frame
        return result
