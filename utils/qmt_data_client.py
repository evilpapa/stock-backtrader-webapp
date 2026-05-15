"""Client helpers for the local QMT data web service."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd


class QmtDataClientError(RuntimeError):
    """Raised when the QMT data service returns an error."""


class QmtDataClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", token: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def get_history_data(self, **params: Any) -> Any:
        return self._request("POST", "/v1/history-data", params)["data"]

    def get_market_data(self, **params: Any) -> Any:
        return self._request("POST", "/v1/market-data", params)["data"]

    def get_market_data_ex(self, **params: Any) -> dict[str, Any]:
        return self._request("POST", "/v1/market-data-ex", params)["data"]

    def get_full_tick(self, **params: Any) -> Any:
        return self._request("POST", "/v1/full-tick", params)["data"]

    def get_local_data(self, **params: Any) -> Any:
        return self._request("POST", "/v1/local-data", params)["data"]

    def get_market_data_ex_df(self, symbol: str, **params: Any) -> pd.DataFrame:
        stock_code = params.pop("stock_code", [symbol])
        data = self.get_market_data_ex(stock_code=stock_code, **params)
        frame_payload = data.get(symbol)
        if frame_payload is None:
            raise QmtDataClientError("QMT response does not contain symbol: {0}".format(symbol))
        return dataframe_from_payload(frame_payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer {0}".format(self.token)

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as exc:
            error_body = exc.read()
            message = _extract_error_message(error_body) or "QMT service returned HTTP {0}".format(exc.code)
            raise QmtDataClientError(message) from exc

        response_payload = json.loads(body.decode("utf-8"))
        if not response_payload.get("ok"):
            raise QmtDataClientError(str(response_payload.get("error", "QMT service returned an error")))
        return response_payload


def dataframe_from_payload(payload: dict[str, Any]) -> pd.DataFrame:
    if payload.get("type") != "dataframe":
        raise QmtDataClientError("Expected dataframe payload")

    frame = pd.DataFrame(payload.get("records", []))
    if "time" in frame.columns:
        frame = frame.set_index("time", drop=False)
    return frame


def to_backtrader_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    if "time" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"time": "date"})

    required_columns = ["date", "open", "high", "low", "close", "volume"]
    missing_columns = [column for column in required_columns if column not in frame.columns]
    if missing_columns:
        raise QmtDataClientError("Missing OHLCV column(s): {0}".format(", ".join(missing_columns)))

    return frame[required_columns]


def _extract_error_message(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    error = payload.get("error")
    if error:
        return str(error)
    return None
