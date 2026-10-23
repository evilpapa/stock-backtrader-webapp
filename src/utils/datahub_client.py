"""面向项目业务的 DataHub 便捷客户端。

本模块只依赖 ``src.datahub`` 的统一接口，不导入 Tushare 或 XtQuant。它提供
少量历史脚本仍需要的 ``history_ohlcv``/``market_bars`` 形状转换；真正的
Provider 选择、代码映射、单位转换、缓存和重试全部由 DataHub 完成。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.datahub import (
    DataKind,
    DataRequest,
    DataRouter,
    MarketDataService,
    TickerMapper,
    create_service,
)
from src.datahub.exceptions import DataHubError
from src.datahub.providers.tushare import TushareProvider
from src.datahub.providers.xtquant import XtQuantProvider
from src.datahub.providers.local_cache import DuckDBCacheProvider
from src.datahub.router import RoutePolicy

DEFAULT_OHLCV_FIELDS = ["open", "high", "low", "close", "volume"]
DAILY_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
TICK_FIELDS = ["lastPrice", "volume", "amount", "bidPrice", "askPrice", "bidVol", "askVol"]
INTRADAY_PERIODS = {"1m", "5m", "15m", "30m", "60m"}

_KIND_BY_API = {
    "etf_basic": DataKind.ETF_BASIC,
    "etf_share_size": DataKind.ETF_SHARE,
    "fund_daily": DataKind.FUND_DAILY,
    "fund_adj": DataKind.FUND_ADJ,
    "index_daily": DataKind.INDEX_DAILY,
    "ci_index_member": DataKind.INDEX_MEMBER,
    "index_weight": DataKind.INDEX_WEIGHT,
    "ci_daily": DataKind.CI_DAILY,
    "daily_basic": DataKind.DAILY_BASIC,
    "moneyflow": DataKind.MONEY_FLOW,
    "stock_st": DataKind.ST,
    "ths_hot": DataKind.HOT_RANK,
    "ths_member": DataKind.BOARD_MEMBER,
    "sector_member": DataKind.SECTOR_MEMBER,
    "daily": DataKind.DAILY_BULK,
    "stock_basic": DataKind.STOCK_BASIC,
    "trade_cal": DataKind.TRADE_CALENDAR,
}


class DataSourceError(RuntimeError):
    """数据源相关异常的抽象基类"""
    pass

class DataHubClient:
    """将 DataHub Facade 适配为项目旧脚本使用的少量便捷方法。"""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        service: MarketDataService | None = None,
        tushare_client: Any | None = None,
        xtdata_client: Any | None = None,
        ticker_mapper: TickerMapper | None = None,
        prefer_xtquant: bool = False,
        data_source: str = "auto",
        cache_path: str | None = None,
    ) -> None:
        selected_source = data_source.lower().strip()
        if selected_source not in {"auto", "tushare", "qmt", "cache"}:
            raise ValueError(f"不支持的数据源模式: {data_source}")
        if selected_source == "cache":
            if not cache_path:
                raise ValueError("cache 模式必须提供 cache_path")
            mapper = ticker_mapper or TickerMapper()
            cache_provider = DuckDBCacheProvider(cache_path, ticker_mapper=mapper)
            self.service = MarketDataService(
                DataRouter({"cache": cache_provider}, {DataKind.DAILY: RoutePolicy(("cache",))}),
                ticker_mapper=mapper,
            )
            self.data_source = "cache"
            return
        if service is not None:
            self.service = service
            self.data_source = selected_source
            return
        prefer_xtquant = prefer_xtquant or selected_source == "qmt"
        if token is None and tushare_client is None and xtdata_client is None:
            # 生产路径使用 YAML 中的启停、路由、缓存、单位和代码格式配置。
            self.service = create_service()
            if prefer_xtquant:
                self._prefer_xtquant()
            self.data_source = "qmt" if prefer_xtquant else "auto"
            return
        mapper = ticker_mapper or TickerMapper()
        tushare = TushareProvider(token=token, timeout=timeout, pro_client=tushare_client, ticker_mapper=mapper)
        xtquant = XtQuantProvider(xtdata_client=xtdata_client, ticker_mapper=mapper)
        providers = {"tushare": tushare, "xtquant": xtquant}
        # 采用与默认 YAML 相同的优先级；测试注入的 fake Provider 也经过同一 Router。
        policies = dict(DataRouter.DEFAULT_POLICIES)
        # 显式注入 xtdata 表示调用方选择 QMT/桥接口径（也是旧 QmtDataClient
        # 的兼容场景），不能因为进程环境恰好有 TUSHARE_TOKEN 就被 Tushare
        # 抢先路由。生产 YAML/ProviderFactory 路径仍遵循 Tushare 日线优先。
        if (xtdata_client is not None and tushare_client is None and not token) or prefer_xtquant:
            for kind, policy in tuple(policies.items()):
                if "xtquant" in policy.providers:
                    policies[kind] = RoutePolicy(
                        tuple(["xtquant"] + [name for name in policy.providers if name != "xtquant"]),
                        policy.retries,
                        policy.fallback_on_empty,
                    )
                elif kind in {DataKind.FINANCIAL, DataKind.ST, DataKind.SECTOR_MEMBER}:
                    policies[kind] = RoutePolicy(("xtquant", *policy.providers), policy.retries, policy.fallback_on_empty)
        self.service = MarketDataService(
            DataRouter(providers, policies),
            ticker_mapper=mapper,
        )
        self.data_source = "qmt" if prefer_xtquant else ("tushare" if selected_source == "tushare" else "auto")

    def _prefer_xtquant(self) -> None:
        for kind, policy in tuple(self.service.router.policies.items()):
            if "xtquant" in policy.providers:
                self.service.router.policies[kind] = RoutePolicy(
                    ("xtquant", *[name for name in policy.providers if name != "xtquant"]),
                    policy.retries,
                    policy.fallback_on_empty,
                )

    def query(self, api_name: str, **kwargs: Any) -> pd.DataFrame:
        """通过 DataHub 查询一个扩展接口，兼容旧的 ``_call(name, **kw)`` 语义。"""

        kind = _KIND_BY_API.get(api_name)
        if kind is None:
            raise ValueError(f"DataHub 未注册扩展接口: {api_name}")
        options = dict(kwargs)
        start = options.pop("start_date", None)
        end = options.pop("end_date", None)
        fields = options.pop("fields", ())
        if isinstance(fields, str):
            fields = tuple(item.strip() for item in fields.split(",") if item.strip())
        return self.service.query(
            kind,
            DataRequest(start=start, end=end, fields=tuple(fields), options=options),
            use_cache=True,
        )

    def history_ohlcv(
        self,
        symbol: str,
        start_date: Any,
        end_date: Any,
        *,
        period: str = "1d",
        dividend_type: str = "front",
        fields: list[str] | None = None,
    ) -> pd.DataFrame:
        if period not in {"1d", "1w", "1mon", *INTRADAY_PERIODS}:
            raise ValueError(f"DataHub 不支持周期: {period}")
        normalized = normalize_dividend_type(dividend_type)
        adjust = {"none": "none", "front": "qfq", "back": "hfq"}[normalized]
        request = DataRequest(
            symbols=(symbol,), start=start_date, end=end_date, frequency=period,
            adjust=adjust, fields=tuple(fields or DEFAULT_OHLCV_FIELDS),
        )
        frame = self.service.get(DataKind.DAILY if period in {"1d", "1w", "1mon"} else DataKind.MINUTE, request)
        if frame.empty:
            return pd.DataFrame(columns=["date", *(fields or DEFAULT_OHLCV_FIELDS)])
        result = frame.rename(columns={"datetime": "date"}).copy()
        result["date"] = _legacy_datetime(result["date"])
        requested = fields or DEFAULT_OHLCV_FIELDS
        for field in requested:
            if field not in result:
                result[field] = float("nan")
        return result[["date", *requested]].sort_values("date").reset_index(drop=True)

    def close(self) -> None:
        """释放 DataHub Provider 和本地缓存连接。"""

        self.service.close()

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
        result: dict[str, pd.DataFrame] = {}
        fields = TICK_FIELDS if period == "tick" else DAILY_FIELDS
        kind = DataKind.TICK if period == "tick" else DataKind.DAILY if period == "1d" else DataKind.MINUTE
        for symbol in symbols:
            try:
                normalized = normalize_dividend_type(dividend_type)
                request = DataRequest(
                    symbols=(symbol,), start=start_date, end=end_date, frequency=period,
                    adjust={"none": "none", "front": "qfq", "back": "hfq"}[normalized],
                    fields=tuple(fields), options={"download": download_missing},
                )
                frame = self.service.get(kind, request)
            except DataHubError:
                raise
            if frame.empty:
                result[symbol] = _empty_legacy_bars()
                continue
            frame = frame.rename(columns={"datetime": "bar_time", "pre_close": "preClose"}).copy()
            frame["bar_time"] = _legacy_datetime(frame["bar_time"])
            frame = frame.rename(columns={
                "lastPrice": "last", "bidPrice": "bid", "askPrice": "ask",
                "bidVol": "bid_volume", "askVol": "ask_volume",
            })
            for column in ["last", "bid", "ask", "bid_volume", "ask_volume"]:
                if column not in frame:
                    frame[column] = float("nan")
            for column in ["open", "high", "low", "close", "last", "volume", "amount", "bid", "ask", "bid_volume", "ask_volume"]:
                if column not in frame:
                    frame[column] = float("nan")
            result[symbol] = frame[["bar_time", "open", "high", "low", "close", "volume", "amount", "last", "bid", "ask", "bid_volume", "ask_volume"]]
        return result

    def daily_bars(self, symbols: list[str], start_date: Any, end_date: Any, **kwargs: Any) -> dict[str, pd.DataFrame]:
        result = self.market_bars(symbols, start_date, end_date, period="1d", **kwargs)
        return {symbol: self._bar_frame_to_daily(frame) for symbol, frame in result.items()}

    def local_data(self, **kwargs: Any) -> Any:
        """通过 XtQuant Adapter 读取本地缓存行情，不直接接触 SDK。"""

        provider = self.service.router.providers.get("xtquant")
        getter = getattr(provider, "get_local_data", None)
        if getter is None:
            raise DataHubError("当前 DataHub 未启用 XtQuant 本地行情能力")
        params = dict(kwargs)
        symbols = params.get("stock_list", [])
        params["stock_list"] = [self.service.ticker_mapper.to_xtquant(item, "market_data") for item in symbols]
        return getter(**params)

    @staticmethod
    def _bar_frame_to_daily(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.rename(columns={"bar_time": "date"}).copy()
        if result.empty:
            return pd.DataFrame(columns=["date", *DAILY_FIELDS])
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.tz_localize(None)
        return result[["date", *DAILY_FIELDS]]

    def stock_list_in_sector(self, sector_name: str) -> list[str]:
        try:
            frame = self.query("sector_member", sector_name=sector_name)
            if "symbol" in frame and not frame.empty:
                return [
                    self.service.ticker_mapper.normalize(item)
                    for item in frame["symbol"].dropna().astype(str).tolist()
                ]
        except DataHubError:
            # XtQuant 没有板块服务时，回退到标准基础信息/ETF 查询。
            pass
        if "ETF" in sector_name or "基金" in sector_name:
            frame = self.query("etf_basic", list_status="L")
            column = "ts_code" if "ts_code" in frame else "code"
            return frame[column].dropna().astype(str).tolist() if column in frame else []
        frame = self.service.get_stock_basic(DataRequest())
        if frame.empty:
            return []
        values = frame["symbol"].dropna().astype(str)
        if "北证" in sector_name:
            values = values[values.str.endswith(".BJ")]
        elif "A股" in sector_name:
            values = values[~values.str.endswith(".BJ")]
        return values.tolist()

    @staticmethod
    def sector_list(*, allow_fallback: bool = False) -> list[str]:
        return ["沪深A股", "北证A股", "沪深ETF", "沪深指数"]

    def instrument_detail(self, symbol: str, *, is_detail: bool = True) -> dict[str, Any] | None:
        frame = self.service.get_stock_basic(DataRequest(symbols=(symbol,)))
        if frame.empty:
            return None
        row = frame.iloc[0].to_dict()
        return {**row, "InstrumentName": row.get("name", ""), "OpenDate": row.get("list_date"), "ExpireDate": row.get("delist_date") or "99999999"}

    def historical_st_data(self, symbol: str) -> pd.DataFrame:
        return self.query("stock_st", ts_code=self.service.ticker_mapper.normalize(symbol))

    def financial_period(self, table: str, period: Any, *, fields: list[str] | None = None) -> pd.DataFrame:
        """全市场某报告期的财务报表（income/cashflow/balancesheet），返回标准化 DataFrame。

        ``symbol``/``end_date``/``ann_date``/``f_ann_date`` 已由 Normalizer 统一；
        回测方需自行按 ``f_ann_date`` 做 point-in-time 过滤。
        """

        return self.service.get_financial(
            DataRequest(table=table, fields=tuple(fields or ()), report_type="1", options={"period": format_date(period)}),
            use_cache=False,
        )

    def financial_data(self, symbols: list[str], *, tables: list[str], end_date: Any) -> dict[str, list[dict[str, Any]]]:
        try:
            frame = self.service.get_financial(
                DataRequest(symbols=tuple(symbols), start=end_date, end=end_date, table=tables[0] if tables else "Capital")
            )
            return {
                symbol: frame[frame.get("symbol", pd.Series(dtype=str)).astype(str).map(self.service.ticker_mapper.normalize) == symbol].to_dict(orient="records")
                if not frame.empty and "symbol" in frame else []
                for symbol in symbols
            }
        except DataHubError:
            # Tushare 的流通股本来自 daily_basic；XtQuant 则通常提供
            # get_financial_data。两者都被隐藏在 DataHub 路由之后。
            result: dict[str, list[dict[str, Any]]] = {}
            for symbol in symbols:
                frame = self.query("daily_basic", ts_code=self.service.ticker_mapper.normalize(symbol), trade_date=format_date(end_date, leng=14))
                result[symbol] = frame.to_dict(orient="records")
            return result


def format_date(value: Any, leng=8) -> str:
    """将日期、时间或字符串转换为 Tushare 使用的 ``YYYYMMDD``。"""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:leng]


def normalize_symbol(symbol: str) -> str:
    """将裸代码或旧市场后缀规范化为 Tushare 的 ``code.exchange`` 格式。"""
    value = str(symbol).strip().upper()
    if value.endswith(".SS"):
        return value[:-3] + ".SH"
    if value.endswith((".SH", ".SZ", ".BJ")):
        return value
    if len(value) == 6 and value.startswith(("5", "6", "9")):
        return value + ".SH"
    if len(value) == 6 and value.startswith(("0", "1", "2", "3")):
        return value + ".SZ"
    if len(value) == 6 and value.startswith(("4", "8")):
        return value + ".BJ"
    return value


def normalize_dividend_type(value: str | None) -> str:
    """保留旧页面值，并转换为内部复权标识。"""
    mapping = {
        None: "none", "": "none", "none": "none",
        "qfq": "front", "hfq": "back", "front": "front", "back": "back",
        # Tushare 没有直接等价的比例复权参数，使用同方向复权。
        "front_ratio": "front", "back_ratio": "back",
    }
    key = value.lower() if isinstance(value, str) else value
    if key not in mapping:
        raise DataSourceError(f"Unsupported Tushare dividend_type: {value}")
    return mapping[key]


def _tushare_asset_for_code(ts_code: str) -> str:
    """区分股票行情和场内基金/ETF 行情接口。"""
    code = ts_code.split(".", maxsplit=1)[0]
    return "FD" if code.startswith(("15", "16", "18", "50", "51", "52", "56", "58")) else "E"


def _as_frame(payload: Any) -> pd.DataFrame:
    if payload is None:
        return pd.DataFrame()
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, dict):
        if payload.get("__bigqmt_type__") == "DataFrame":
            records = payload.get("records", [])
            return pd.DataFrame(records if isinstance(records, (list, tuple)) else records)
        return pd.DataFrame(payload)
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    raise DataSourceError(f"Unsupported Tushare response type: {type(payload).__name__}")


def _normalize_ohlcv_frame(frame: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    """将 Tushare 的 trade_date/vol 列规范为项目字段。"""
    if frame.empty:
        return pd.DataFrame(columns=["date", *fields])
    frame = frame.copy()
    frame.columns = [str(column) for column in frame.columns]
    aliases = {"trade_date": "date", "datetime": "date", "time": "date", "vol": "volume"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "date" not in frame.columns:
        raise DataSourceError("Tushare response missing trade_date")
    frame["date"] = _normalize_time_values(frame["date"])
    for field in fields:
        if field not in frame.columns:
            frame[field] = float("nan")
        if field not in {"date", "lastPrice", "bidPrice", "askPrice", "bidVol", "askVol"}:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)[["date", *fields]]


def _normalize_time_values(values: pd.Series) -> pd.Series:
    raw = values.astype(str).str.replace(r"\.0$", "", regex=True)
    lengths = raw.str.len()
    if lengths.eq(8).all():
        return pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    if lengths.eq(14).all():
        return pd.to_datetime(raw, format="%Y%m%d%H%M%S", errors="coerce")
    numeric = pd.to_numeric(raw, errors="coerce")
    if numeric.notna().all() and not numeric.empty:
        magnitude = numeric.abs().median()
        if magnitude >= 1e11:
            return pd.to_datetime(numeric, unit="ms", errors="coerce")
        if magnitude >= 1e9:
            return pd.to_datetime(numeric, unit="s", errors="coerce")
    return pd.to_datetime(raw, errors="coerce")


def market_data_payload_to_frame(
    data: Any,
    symbol: str,
    fields: list[str],
    *,
    numeric_fields: list[str] | None = None,
) -> pd.DataFrame:
    """兼容旧测试/缓存载荷的通用 OHLCV 解析器。"""
    if isinstance(data, dict) and data.get("__bigqmt_type__") == "DataFrame":
        records = data.get("records", [])
        frame = pd.DataFrame(records if isinstance(records, (list, tuple)) else records)
    elif isinstance(data, dict) and symbol in data:
        return market_data_payload_to_frame(data[symbol], symbol, fields, numeric_fields=numeric_fields)
    elif isinstance(data, dict) and all(field in data for field in fields):
        columns: dict[str, pd.Series] = {}
        for field in fields:
            value = data[field]
            if isinstance(value, pd.DataFrame):
                if symbol in value.index:
                    row = value.loc[symbol]
                    if isinstance(row, pd.DataFrame):
                        row = row.iloc[0]
                elif len(value.index) == 1:
                    row = value.iloc[0]
                else:
                    raise DataSourceError(f"response missing symbol: {symbol}")
                columns[field] = pd.Series(row.to_numpy(), index=row.index)
            elif isinstance(value, dict):
                item = value.get(symbol, value)
                columns[field] = pd.Series(item if isinstance(item, (list, tuple, pd.Series)) else [item])
            else:
                columns[field] = pd.Series(value if isinstance(value, (list, tuple, pd.Series)) else [value])
        frame = pd.DataFrame(columns)
        frame.insert(0, "date", frame.index)
    else:
        frame = _as_frame(data)
    if frame.empty:
        return pd.DataFrame(columns=["date", *fields])
    if symbol in frame.columns and len(frame) == 1:
        frame = frame.T.reset_index(names="date")
    if not any(column in frame.columns for column in ("date", "trade_date", "datetime", "time")):
        frame = frame.reset_index(names="date")
    if numeric_fields:
        for field in numeric_fields:
            if field in frame.columns:
                frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return _normalize_ohlcv_frame(frame, fields)


def _legacy_datetime(values: pd.Series) -> pd.Series:
    result = pd.to_datetime(values, errors="coerce")
    if getattr(result.dt, "tz", None) is not None:
        result = result.dt.tz_localize(None)
    return result


def _empty_legacy_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=["bar_time", "open", "high", "low", "close", "volume", "amount", "last", "bid", "ask", "bid_volume", "ask_volume"])


def to_upper_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    if "date" in frame.columns:
        frame.index = pd.to_datetime(frame["date"], errors="coerce")
    return frame.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })[["Open", "High", "Low", "Close", "Volume"]]


def to_chinese_ohlcv(data_frame: pd.DataFrame) -> pd.DataFrame:
    frame = data_frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return frame.rename(columns={
        "date": "日期", "open": "开盘", "close": "收盘", "high": "最高",
        "low": "最低", "volume": "成交量",
    })[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]


def market_data_payload_to_ohlcv(data: Any, symbol: str, fields: list[str] | None = None) -> pd.DataFrame:
    field_list = fields or DEFAULT_OHLCV_FIELDS
    return market_data_payload_to_frame(data, symbol, field_list, numeric_fields=field_list)


__all__ = [
    "DataHubClient", "DataSourceError",
    "DAILY_FIELDS", "DEFAULT_OHLCV_FIELDS", "INTRADAY_PERIODS", "TICK_FIELDS",
    "format_date", "market_data_payload_to_frame", "market_data_payload_to_ohlcv",
    "normalize_dividend_type", "normalize_symbol", "normalize_symbol",
    "to_chinese_ohlcv", "to_upper_ohlcv",
]
