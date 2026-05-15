"""Whitelisted adapter for QMT ContextInfo data APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class QmtDataAdapterError(ValueError):
    """Raised when a QMT data request is invalid."""


@dataclass(frozen=True)
class MethodSpec:
    required: tuple[str, ...]
    defaults: dict[str, Any]

    @property
    def allowed(self) -> set[str]:
        return set(self.required) | set(self.defaults)


class QmtDataAdapter:
    """Expose only approved read-only QMT market data methods."""

    METHOD_SPECS: dict[str, MethodSpec] = {
        "get_history_data": MethodSpec(
            required=("len", "period", "field"),
            defaults={
                "dividend_type": 0,
                "skip_paused": True,
                "stock_code": None,
            },
        ),
        "get_market_data": MethodSpec(
            required=("fields",),
            defaults={
                "stock_code": [],
                "start_time": "",
                "end_time": "",
                "skip_paused": True,
                "period": "1d",
                "dividend_type": "none",
                "count": -1,
            },
        ),
        "get_market_data_ex": MethodSpec(
            required=(),
            defaults={
                "fields": [],
                "stock_code": [],
                "period": "follow",
                "start_time": "",
                "end_time": "",
                "count": -1,
                "dividend_type": "follow",
                "fill_data": True,
                "subscribe": True,
            },
        ),
        "get_full_tick": MethodSpec(
            required=(),
            defaults={"stock_code": []},
        ),
        "get_local_data": MethodSpec(
            required=("stock_code",),
            defaults={
                "start_time": "",
                "end_time": "",
                "period": "1d",
                "divid_type": "none",
                "count": -1,
            },
        ),
    }

    def __init__(self, context_info: Any):
        self.context_info = context_info

    def call(self, method: str, params: dict[str, Any]) -> Any:
        if method not in self.METHOD_SPECS:
            raise QmtDataAdapterError("Unsupported QMT data method: {0}".format(method))

        spec = self.METHOD_SPECS[method]
        unknown_params = sorted(set(params) - spec.allowed)
        if unknown_params:
            raise QmtDataAdapterError(
                "Unsupported parameter(s) for {0}: {1}".format(method, ", ".join(unknown_params))
            )

        missing_params = [name for name in spec.required if name not in params]
        if missing_params:
            raise QmtDataAdapterError(
                "Missing required parameter(s) for {0}: {1}".format(method, ", ".join(missing_params))
            )

        call_params = dict(spec.defaults)
        call_params.update(params)

        if method == "get_history_data":
            return self._call_get_history_data(call_params)

        qmt_method = self._get_context_method(method)
        return qmt_method(**call_params)

    def _call_get_history_data(self, params: dict[str, Any]) -> Any:
        stock_code = params.pop("stock_code", None)
        if stock_code:
            set_universe = self._get_context_method("set_universe")
            set_universe(stock_code)

        qmt_method = self._get_context_method("get_history_data")
        return qmt_method(
            params["len"],
            params["period"],
            params["field"],
            dividend_type=params["dividend_type"],
            skip_paused=params["skip_paused"],
        )

    def _get_context_method(self, name: str) -> Callable[..., Any]:
        method = getattr(self.context_info, name, None)
        if method is None or not callable(method):
            raise QmtDataAdapterError("ContextInfo does not provide {0}".format(name))
        return method

