"""XtQuant / xtquant_big_convert Adapter。

默认优先导入 ``bigqmt_signal_trader.xtquant_compat``，只有桥接包不可用时才
尝试官方 ``xtquant.xtdata``。这使开发机和 QMT 端使用同一套 DataHub 接口。
"""

from __future__ import annotations

import itertools
import inspect
from collections.abc import Callable, Sequence
from typing import Any

import pandas as pd

from ..exceptions import (
    DataSourceTimeout, ProviderCapacityError, ProviderPermissionError, ProviderUnavailable, SubscriptionError,
)
from ..models import DataKind, DataRequest, DataResult
from ..provider import Callback, MarketDataProvider, RealtimeProvider
from ..ticker import TickerMapper


class XtQuantProvider(MarketDataProvider, RealtimeProvider):
    """XtQuant 行情 Adapter，所有 SDK 差异均封装在本类。"""

    name = "xtquant"
    _supported = {
        DataKind.DAILY, DataKind.MINUTE, DataKind.TICK, DataKind.REALTIME,
        DataKind.STOCK_BASIC, DataKind.TRADE_CALENDAR, DataKind.FINANCIAL,
        DataKind.ADJ_FACTOR, DataKind.LEVEL2,
        DataKind.ST, DataKind.SECTOR_MEMBER, DataKind.INSTRUMENT,
    }

    def __init__(self, xtdata_client: Any | None = None, ticker_mapper: TickerMapper | None = None,
                 require_bridge: bool = False) -> None:
        self.xtdata = xtdata_client
        self.ticker_mapper = ticker_mapper or TickerMapper()
        self.require_bridge = require_bridge
        self._callbacks: list[Callback] = []
        self._subscriptions: dict[str, list[Any]] = {}
        self._counter = itertools.count(1)

    def _api(self) -> Any:
        if self.xtdata is not None:
            return self.xtdata
        try:
            from bigqmt_signal_trader.xtquant_compat import xtdata  # type: ignore
        except ImportError as bridge_error:
            if self.require_bridge:
                raise ProviderUnavailable("未安装 Big QMT 桥接客户端 xtquant-big-convert") from bridge_error
            try:
                from xtquant import xtdata  # type: ignore
            except ImportError as exc:  # pragma: no cover - deployment guard
                raise ProviderUnavailable("未安装 xtquant-big-convert，且找不到官方 xtquant.xtdata") from exc
        self.xtdata = xtdata
        return xtdata

    def supports(self, data_kind: DataKind) -> bool:
        return data_kind in self._supported

    def is_available(self) -> bool:
        try:
            self._api()
        except ProviderUnavailable:
            return False
        return True

    def get_daily(self, request: DataRequest) -> DataResult:
        return self._get_history(request, DataKind.DAILY, "1d")

    def get_minute(self, request: DataRequest) -> DataResult:
        return self._get_history(request, DataKind.MINUTE, request.frequency)

    def get_tick(self, request: DataRequest) -> DataResult:
        return self._get_history(request, DataKind.TICK, "tick")

    def _get_history(self, request: DataRequest, kind: DataKind, period: str) -> DataResult:
        api = self._api()
        symbols = [self.ticker_mapper.to_xtquant(item, "market_data") for item in request.symbols]
        start, end = _date(request.start), _date(request.end)
        postclose = bool(request.options.get("postclose"))
        if postclose and period == "1m":
            start, end = start[:8] + "093000", end[:8] + "160000"
        if postclose and request.options.get("download") and symbols:
            try:
                accepted = api.call_method(
                    "download_history_data2", stock_list=symbols, period=period,
                    start_time=start, end_time=end, incrementally=False,
                )
                if not accepted:
                    raise ProviderUnavailable("QMT 端未受理历史行情下载")
            except Exception as exc:
                raise ProviderUnavailable(f"QMT 桥接端下载 {period} 失败: {exc}") from exc
        elif not postclose and request.options.get("download", True) and hasattr(api, "download_history_data2") and symbols:
            try:
                api.download_history_data2(stock_list=symbols, period=period, start_time=start, end_time=end)
            except (TimeoutError, ConnectionError) as exc:
                raise DataSourceTimeout(f"XtQuant 下载历史数据失败: {exc}") from exc
        kwargs = {
            "field_list": list(request.fields) or ["open", "high", "low", "close", "volume", "amount", "preClose"],
            "stock_list": symbols,
            "period": period,
            "start_time": start,
            "end_time": end,
            "count": -1,
            # XtQuant 官方参数是 none/front/back；DataHub 对外统一为
            # none/qfq/hfq，不能把内部值直接传给第三方。
            "dividend_type": {"none": "none", "qfq": "front", "hfq": "back"}[request.adjust.value],
            "fill_data": bool(request.options.get("fill_data", True)),
        }
        try:
            getter = getattr(api, "get_market_data_ex", None) or getattr(api, "get_market_data")
            # 桥接扩展支持 subscribe；历史查询不需要常驻订阅，避免批量读取时
            # QMT 持续累积订阅。官方 SDK 的部分版本没有此参数，保持兼容。
            try:
                parameters = inspect.signature(getter).parameters
            except (TypeError, ValueError):
                parameters = {}
            if "subscribe" in parameters:
                kwargs["subscribe"] = False
            if postclose:
                if "subscribe" not in parameters:
                    raise ProviderUnavailable("QMT 桥接行情 Adapter 缺少 subscribe=False 支持")
                for option in ("use_formula", "heal", "backfill_pre_close"):
                    if option in parameters:
                        kwargs[option] = False
                if "timeout_seconds" in parameters:
                    kwargs["timeout_seconds"] = 60
            payload = getter(**kwargs)
        except (TimeoutError, ConnectionError) as exc:
            raise DataSourceTimeout(f"XtQuant 历史行情请求失败: {exc}") from exc
        except PermissionError as exc:
            raise ProviderPermissionError(f"XtQuant 行情权限不足: {exc}") from exc
        except Exception as exc:
            if postclose and (isinstance(exc, MemoryError) or
                              str(exc).startswith(("MemoryError:", "std::bad_alloc", "bad allocation"))):
                raise ProviderCapacityError(f"QMT 读取 {period} 资源不足，共 {len(symbols)} 只: {exc}") from exc
            raise ProviderUnavailable(f"XtQuant 历史行情请求失败: {exc}") from exc
        frame = self._market_payload(payload, symbols)
        if not frame.empty and "symbol" in frame.columns:
            # 某些桥接/模拟实现会返回请求列表之外的证券；Provider 必须
            # 在统一边界截断，避免单证券请求拿到另一证券的最后一根 K 线。
            allowed = set(symbols)
            frame = frame[frame["symbol"].astype(str).isin(allowed)].copy()
        return DataResult(frame, self.name, kind, request.request_id, metadata={"provider_unit_contract": "xtquant-native-volume-amount"})

    def get_realtime(self, request: DataRequest) -> DataResult:
        api = self._api()
        symbols = [self.ticker_mapper.to_xtquant(item, "realtime") for item in request.symbols]
        try:
            payload = api.get_full_tick(symbols)
        except Exception as exc:
            raise ProviderUnavailable(f"XtQuant 实时行情请求失败: {exc}") from exc
        rows = []
        execution_state = {}
        for symbol, value in (payload or {}).items():
            row = dict(value) if isinstance(value, dict) else {"value": value}
            row["symbol"] = symbol
            rows.append(row)
            # Big QMT get_full_tick documents stockStatus as obsolete:
            # cash securities use openInt (13 = continuous trading). Preserve
            # this separately because the canonical OHLCV columns omit it.
            state_field = "openInt" if "openInt" in row else "stockStatus"
            execution_state[self.ticker_mapper.normalize(symbol)] = {
                "security_status": row.get(state_field), "status_field": state_field,
                "bid_prices": row.get("bidPrice", []), "ask_prices": row.get("askPrice", []),
            }
        return DataResult(pd.DataFrame(rows), self.name, DataKind.REALTIME, request.request_id,
                          metadata={"execution_state": execution_state})

    def get_stock_basic(self, request: DataRequest) -> DataResult:
        api = self._api()
        rows = []
        for symbol in request.symbols:
            code = self.ticker_mapper.to_xtquant(symbol, "instrument")
            detail = api.get_instrument_detail(code, True)
            if detail:
                rows.append({"symbol": code, **detail})
        return DataResult(pd.DataFrame(rows), self.name, DataKind.STOCK_BASIC, request.request_id)

    def get_trade_calendar(self, request: DataRequest) -> DataResult:
        api = self._api()
        market = request.exchange or "SH"
        getter = getattr(api, "get_trading_calendar", None) or getattr(api, "get_trading_dates")
        values = getter(market, _date(request.start), _date(request.end))
        frame = pd.DataFrame({"exchange": market, "trade_date": list(values or []), "is_open": 1})
        return DataResult(frame, self.name, DataKind.TRADE_CALENDAR, request.request_id)

    def get_financial(self, request: DataRequest) -> DataResult:
        api = self._api()
        symbols = [self.ticker_mapper.to_xtquant(item, "financial") for item in request.symbols]
        tables = [request.table or "Income"]
        try:
            payload = api.get_financial_data(
                symbols, table_list=tables, start_time=_date(request.start),
                end_time=_date(request.end), report_type=request.report_type or "report_time",
            )
        except TypeError:
            # 部分桥接版本将 stock_list 定义为关键字参数；两种签名均在
            # Adapter 内兼容，业务层不需要判断安装版本。
            payload = api.get_financial_data(
                stock_list=symbols, table_list=tables, start_time=_date(request.start),
                end_time=_date(request.end), report_type=request.report_type or "report_time",
            )
        frames = []
        for symbol, table_data in (payload or {}).items():
            table_frame = table_data.get(tables[0], table_data) if isinstance(table_data, dict) else table_data
            frame = self._as_frame(table_frame)
            if not frame.empty:
                frame["symbol"] = symbol
                frames.append(frame)
        return DataResult(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), self.name, DataKind.FINANCIAL, request.request_id)

    def get_adj_factor(self, request: DataRequest) -> DataResult:
        api = self._api()
        frames = []
        for symbol in request.symbols:
            frame = self._as_frame(api.get_divid_factors(self.ticker_mapper.to_xtquant(symbol, "market_data"), _date(request.start), _date(request.end)))
            if not frame.empty:
                frame["symbol"] = symbol
                frames.append(frame)
        return DataResult(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), self.name, DataKind.ADJ_FACTOR, request.request_id)

    def get_level2(self, request: DataRequest) -> DataResult:
        return self._get_history(request, DataKind.LEVEL2, request.frequency or "l2quote")

    def get_extension(self, data_kind: DataKind, request: DataRequest) -> DataResult:
        api = self._api()
        if data_kind == DataKind.INSTRUMENT:
            rows = []
            for symbol in request.symbols:
                external = self.ticker_mapper.to_xtquant(symbol, "instrument")
                # Bridge 0.3.78 accepts only stock_code; official SDK also
                # permits the single-argument form.
                detail = api.get_instrument_detail(external)
                if detail:
                    rows.append({**detail, "symbol": self.ticker_mapper.normalize(symbol)})
            return DataResult(pd.DataFrame(rows), self.name, data_kind, request.request_id,
                              metadata={"adjust": "none", "frequency": "snapshot"})
        if data_kind == DataKind.SECTOR_MEMBER:
            sector_name = str(request.options.get("sector_name", ""))
            getter = getattr(api, "get_stock_list_in_sector", None)
            if getter is None:
                raise ProviderUnavailable("XtQuant 未提供板块成分查询")
            if request.as_of is not None and request.options.get("postclose"):
                point = pd.Timestamp(request.as_of)
                if point.tzinfo is None:
                    point = point.tz_localize("Asia/Shanghai")
                values = getter(sector_name, real_timetag=int(point.timestamp() * 1000))
            else:
                values = getter(sector_name)
            return DataResult(pd.DataFrame({"symbol": list(values or [])}), self.name, data_kind, request.request_id)
        if data_kind == DataKind.ST:
            getter = getattr(api, "get_his_st_data", None)
            if getter is None:
                raise ProviderUnavailable("XtQuant 未提供历史 ST 查询")
            rows = []
            for symbol in request.symbols or (request.options.get("ts_code", ""),):
                if not symbol:
                    continue
                rows.extend(_as_records(getter(self.ticker_mapper.to_xtquant(symbol, "instrument"))))
            return DataResult(pd.DataFrame(rows), self.name, data_kind, request.request_id)
        raise NotImplementedError(f"XtQuant 不支持扩展数据类型 {data_kind.value}")

    def get_local_data(self, **kwargs: Any) -> Any:
        """读取 QMT 本地缓存，不触发下载；仅暴露给 DataHub 迁移适配层。"""

        api = self._api()
        getter = getattr(api, "get_local_data", None)
        if getter is None:
            raise ProviderUnavailable("XtQuant 当前版本未提供 get_local_data")
        try:
            return getter(**kwargs)
        except (TimeoutError, ConnectionError) as exc:
            raise DataSourceTimeout(f"XtQuant 本地行情读取失败: {exc}") from exc
        except Exception as exc:
            raise ProviderUnavailable(f"XtQuant 本地行情读取失败: {exc}") from exc

    def subscribe_quote(self, symbols: Sequence[str], callback: Callback | None = None) -> str:
        return self._subscribe(symbols, "tick", callback)

    def subscribe_tick(self, symbols: Sequence[str], callback: Callback | None = None) -> str:
        return self._subscribe(symbols, "tick", callback)

    def _subscribe(self, symbols: Sequence[str], period: str, callback: Callback | None) -> str:
        api = self._api()
        if not symbols:
            raise SubscriptionError("订阅列表不能为空")
        sink = callback or self._emit
        ids = []
        for symbol in symbols:
            external = self.ticker_mapper.to_xtquant(symbol, "realtime")
            try:
                sub_id = api.subscribe_quote(external, period=period, count=0, callback=sink)
            except Exception as exc:
                raise SubscriptionError(f"XtQuant 订阅 {symbol} 失败: {exc}") from exc
            ids.append(sub_id)
        subscription_id = "|".join(str(item) for item in ids)
        self._subscriptions[subscription_id] = ids
        return subscription_id

    def unsubscribe_quote(self, subscription_id: str) -> None:
        self._unsubscribe(subscription_id)

    def unsubscribe_tick(self, subscription_id: str) -> None:
        self._unsubscribe(subscription_id)

    def _unsubscribe(self, subscription_id: str) -> None:
        api = self._api()
        ids = self._subscriptions.pop(subscription_id, [item for item in subscription_id.split("|") if item])
        for sub_id in ids:
            try:
                api.unsubscribe_quote(int(sub_id) if str(sub_id).isdigit() else sub_id)
            except Exception as exc:
                raise SubscriptionError(f"XtQuant 取消订阅 {sub_id} 失败: {exc}") from exc

    def register_callback(self, callback: Callback) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def _emit(self, payload: Any) -> None:
        for callback in tuple(self._callbacks):
            callback(payload)

    def close(self) -> None:
        for subscription_id in tuple(self._subscriptions):
            try:
                self._unsubscribe(subscription_id)
            except SubscriptionError:
                continue
        self._callbacks.clear()

    @classmethod
    def _market_payload(cls, payload: Any, symbols: list[str]) -> pd.DataFrame:
        frames = []
        if isinstance(payload, dict):
            # 官方 get_market_data 的 K 线返回是
            # dict[field] -> DataFrame(index=stock, columns=time)，而桥接层的
            # get_market_data_ex 返回 dict[stock] -> DataFrame；两种结构都在
            # Adapter 内收敛，业务层不需要分支。
            field_names = {"time", "open", "high", "low", "close", "volume", "amount", "preClose", "pre_close"}
            if set(payload).intersection(field_names) and any(isinstance(value, pd.DataFrame) for value in payload.values()):
                return cls._field_payload(payload, symbols)
            for symbol, value in payload.items():
                frame = cls._as_frame(value)
                if frame.empty:
                    continue
                frame["symbol"] = symbol
                frames.append(frame)
        else:
            frame = cls._as_frame(payload)
            if not frame.empty:
                frame["symbol"] = symbols[0] if len(symbols) == 1 else pd.NA
                frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    @classmethod
    def _field_payload(cls, payload: dict[str, Any], symbols: list[str]) -> pd.DataFrame:
        rows = []
        available = next((value for value in payload.values() if isinstance(value, pd.DataFrame)), pd.DataFrame())
        stocks = list(available.index) if not available.empty else symbols
        times = list(available.columns) if not available.empty else []
        for stock in stocks:
            for timestamp in times:
                row: dict[str, Any] = {"symbol": stock, "time": timestamp}
                for field, value in payload.items():
                    if not isinstance(value, pd.DataFrame) or stock not in value.index or timestamp not in value.columns:
                        continue
                    row[field] = value.loc[stock, timestamp]
                rows.append(row)
        return pd.DataFrame(rows)

    @staticmethod
    def _as_frame(value: Any) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.DataFrame):
            frame = value.reset_index() if value.index.name is not None or not isinstance(value.index, pd.RangeIndex) else value.copy()
            if "index" in frame.columns and "time" not in frame.columns:
                frame = frame.rename(columns={"index": "time"})
            return frame
        if isinstance(value, dict) and value.get("__bigqmt_type__") == "DataFrame":
            return pd.DataFrame(value.get("records", []))
        if isinstance(value, (list, tuple, dict)):
            return pd.DataFrame(value)
        return pd.DataFrame()


def _date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:14]


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item if isinstance(item, dict) else {"value": item} for item in value]
    return []
