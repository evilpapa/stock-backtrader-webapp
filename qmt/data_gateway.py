"""Local HTTP gateway for QMT market data APIs."""

from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from qmt.data_adapter import QmtDataAdapter, QmtDataAdapterError


MAX_REQUEST_BYTES = 1024 * 1024

ENDPOINT_METHODS = {
    "/v1/history-data": "get_history_data",
    "/v1/market-data": "get_market_data",
    "/v1/market-data-ex": "get_market_data_ex",
    "/v1/full-tick": "get_full_tick",
    "/v1/local-data": "get_local_data",
}

_SERVICE_LOCK = threading.Lock()
_SERVICE: "QmtDataService | None" = None


class QmtDataGatewayError(Exception):
    """Raised when the QMT HTTP gateway cannot complete a request."""


class QmtDataService:
    def __init__(self, context_info: Any, host: str = "127.0.0.1", port: int = 8765, token: str | None = None):
        self.context_info = context_info
        self.host = host
        self.port = port
        self.token = token
        self.adapter = QmtDataAdapter(context_info)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.httpd is not None and self.thread is not None and self.thread.is_alive()

    def start(self) -> dict[str, Any]:
        if self.running:
            return self.status()

        handler = self._build_handler()
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="qmt-data-service", daemon=True)
        self.thread.start()
        return self.status()

    def stop(self) -> None:
        if self.httpd is None:
            return

        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        self.httpd = None
        self.thread = None

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "host": self.host,
            "port": self.port,
            "running": self.running,
            "context_registered": self.context_info is not None,
            "auth_required": bool(self.token),
        }

    def replace_context(self, context_info: Any) -> None:
        self.context_info = context_info
        self.adapter = QmtDataAdapter(context_info)

    def handle(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if path == "/health":
            return self.status()

        method = ENDPOINT_METHODS.get(path)
        if method is None:
            raise QmtDataGatewayError("Unknown endpoint: {0}".format(path))

        result = self.adapter.call(method, payload or {})
        return {"ok": True, "data": normalize_qmt_value(result)}

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        service = self

        class QmtRequestHandler(BaseHTTPRequestHandler):
            server_version = "QmtDataGateway/1.0"

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/health":
                    self._write_error(404, "Unknown endpoint: {0}".format(parsed.path))
                    return
                if not self._is_authorized():
                    self._write_error(401, "Unauthorized")
                    return
                self._write_json(200, service.handle(parsed.path))

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if not self._is_authorized():
                    self._write_error(401, "Unauthorized")
                    return

                try:
                    payload = self._read_payload()
                    response = service.handle(parsed.path, payload)
                except QmtDataAdapterError as exc:
                    self._write_error(400, str(exc))
                    return
                except QmtDataGatewayError as exc:
                    self._write_error(404, str(exc))
                    return
                except ValueError as exc:
                    self._write_error(400, str(exc))
                    return
                except Exception as exc:  # pragma: no cover - protects QMT runtime from uncaught HTTP errors.
                    self._write_error(500, "QMT data gateway error: {0}".format(exc))
                    return

                self._write_json(200, response)

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _is_authorized(self) -> bool:
                if not service.token:
                    return True
                auth_header = self.headers.get("Authorization", "")
                token_header = self.headers.get("X-QMT-Token", "")
                return auth_header == "Bearer {0}".format(service.token) or token_header == service.token

            def _read_payload(self) -> dict[str, Any]:
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("Invalid Content-Length") from exc

                if length > MAX_REQUEST_BYTES:
                    raise ValueError("Request body too large")
                if length == 0:
                    return {}

                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError("Malformed JSON request body") from exc

                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object")
                return payload

            def _write_error(self, status: int, message: str) -> None:
                self._write_json(status, {"ok": False, "error": message})

            def _write_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return QmtRequestHandler


def start_qmt_data_service(
    context_info: Any,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
) -> dict[str, Any]:
    global _SERVICE

    with _SERVICE_LOCK:
        if _SERVICE is not None and _SERVICE.running:
            _SERVICE.replace_context(context_info)
            return _SERVICE.status()

        _SERVICE = QmtDataService(context_info=context_info, host=host, port=port, token=token)
        return _SERVICE.start()


def stop_qmt_data_service() -> None:
    global _SERVICE

    with _SERVICE_LOCK:
        if _SERVICE is None:
            return
        _SERVICE.stop()
        _SERVICE = None


def normalize_qmt_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return _normalize_dataframe(value)
    if isinstance(value, pd.Series):
        return _normalize_series(value)
    if isinstance(value, dict):
        return {str(key): normalize_qmt_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_qmt_value(item) for item in value]
    if isinstance(value, np.generic):
        return normalize_qmt_value(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _normalize_dataframe(data_frame: pd.DataFrame) -> dict[str, Any]:
    frame = data_frame.copy()
    index_name = _available_index_name(frame)
    frame.insert(0, index_name, frame.index)
    frame = frame.where(pd.notnull(frame), None)
    return {
        "type": "dataframe",
        "columns": [str(column) for column in frame.columns],
        "records": [
            {str(key): normalize_qmt_value(value) for key, value in record.items()}
            for record in frame.to_dict(orient="records")
        ],
    }


def _available_index_name(data_frame: pd.DataFrame) -> str:
    base_name = data_frame.index.name or "time"
    index_name = str(base_name)
    suffix = 1
    while index_name in data_frame.columns:
        index_name = "{0}_{1}".format(base_name, suffix)
        suffix += 1
    return index_name


def _normalize_series(series: pd.Series) -> dict[str, Any]:
    clean_series = series.where(pd.notnull(series), None)
    return {
        "type": "series",
        "name": None if series.name is None else str(series.name),
        "data": {str(key): normalize_qmt_value(value) for key, value in clean_series.to_dict().items()},
    }
