"""Tushare Pro Adapter。

所有 Tushare API 名称、日期和单位差异都限制在本文件内。业务层只看到
``MarketDataProvider`` 的 DataFrame 结果。
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from ..exceptions import DataSourceTimeout, ProviderPermissionError, ProviderUnavailable
from ..models import DataKind, DataRequest, DataResult
from ..provider import MarketDataProvider
from ..ticker import TickerMapper


class TushareProvider(MarketDataProvider):
    """Tushare Pro 的 Adapter。

    ``pro_client`` 是为离线单元测试注入的 fake；生产环境从
    ``TUSHARE_TOKEN`` 环境变量创建官方 Pro 客户端，Token 不落盘。
    """

    name = "tushare"
    _supported = {
        DataKind.DAILY, DataKind.MINUTE, DataKind.STOCK_BASIC,
        DataKind.TRADE_CALENDAR, DataKind.FINANCIAL, DataKind.ADJ_FACTOR,
        DataKind.ETF_BASIC, DataKind.ETF_SHARE, DataKind.FUND_DAILY, DataKind.FUND_ADJ,
        DataKind.INDEX_DAILY, DataKind.INDEX_MEMBER, DataKind.INDEX_WEIGHT,
        DataKind.CI_DAILY, DataKind.DAILY_BASIC, DataKind.MONEY_FLOW, DataKind.ST,
        DataKind.HOT_RANK, DataKind.BOARD_MEMBER,
        DataKind.DAILY_BULK,
    }

    _extension_apis = {
        DataKind.ETF_BASIC: "etf_basic",
        DataKind.ETF_SHARE: "etf_share_size",
        DataKind.FUND_DAILY: "fund_daily",
        DataKind.FUND_ADJ: "fund_adj",
        DataKind.INDEX_DAILY: "index_daily",
        DataKind.INDEX_MEMBER: "ci_index_member",
        DataKind.INDEX_WEIGHT: "index_weight",
        DataKind.CI_DAILY: "ci_daily",
        DataKind.DAILY_BASIC: "daily_basic",
        DataKind.MONEY_FLOW: "moneyflow",
        DataKind.ST: "stock_st",
        DataKind.HOT_RANK: "ths_hot",
        DataKind.BOARD_MEMBER: "ths_member",
        DataKind.DAILY_BULK: "daily",
    }

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 30.0,
        pro_client: Any | None = None,
        ticker_mapper: TickerMapper | None = None,
    ) -> None:
        self.token = token or os.getenv("TUSHARE_TOKEN", "")
        self.timeout = timeout
        self.pro = pro_client
        self.ticker_mapper = ticker_mapper or TickerMapper()

    def supports(self, data_kind: DataKind) -> bool:
        return data_kind in self._supported

    def is_available(self) -> bool:
        if self.pro is not None:
            return True
        return bool(self.token)

    def _api(self) -> Any:
        if self.pro is not None:
            return self.pro
        if not self.token:
            raise ProviderUnavailable("Tushare 未配置 TUSHARE_TOKEN")
        try:
            import tushare as ts
        except ImportError as exc:  # pragma: no cover - depends on deployment
            raise ProviderUnavailable("未安装 tushare，请执行 uv sync") from exc
        try:
            self.pro = ts.pro_api(self.token)
        except Exception as exc:  # pragma: no cover - depends on deployment
            raise ProviderUnavailable(f"Tushare 客户端初始化失败: {exc}") from exc
        return self.pro

    def _call(self, method: str, **kwargs: Any) -> Any:
        api = self._api()
        function = getattr(api, method, None)
        if function is None:
            raise ProviderUnavailable(f"Tushare Pro 不支持接口 {method}")
        try:
            return function(**kwargs)
        except (TimeoutError, ConnectionError) as exc:
            raise DataSourceTimeout(f"Tushare {method} 请求超时/连接失败: {exc}") from exc
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if any(word in message for word in ("权限", "积分", "token", "授权")) or "permission" in lowered:
                raise ProviderPermissionError(f"Tushare {method} 权限不足: {message}") from exc
            if any(word in message for word in ("参数", "字段", "接口不存在", "invalid", "not found")):
                raise ValueError(f"Tushare {method} 参数或字段错误: {message}") from exc
            raise ProviderUnavailable(f"Tushare {method} 请求失败: {message}") from exc

    def get_daily(self, request: DataRequest) -> DataResult:
        frames = []
        symbols = request.symbols
        for symbol in symbols:
            code = self.ticker_mapper.to_tushare(symbol)
            if _is_fund_code(code) and request.frequency == "1d":
                # Tushare 的 daily 主要返回股票；ETF/场内基金要走 fund_daily。
                # 该分支仍在 Adapter 内，业务层继续只使用 DataKind.DAILY。
                frame = self._call("fund_daily", ts_code=code, **self._date_kwargs(request))
                if request.adjust.value != "none":
                    frame = self._adjust_fund_daily(frame, code, request)
            elif request.adjust.value == "none" and request.frequency == "1d":
                frame = self._call("daily", ts_code=code, **self._date_kwargs(request))
            else:
                frame = self._pro_bar(code, request)
            frames.append(self._frame(frame))
        return self._result(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), DataKind.DAILY, request)

    def _adjust_fund_daily(self, frame: Any, code: str, request: DataRequest) -> Any:
        """用 fund_adj 在 Adapter 内完成 ETF 前/后复权。"""

        daily = self._frame(frame)
        factors = self._frame(self._call("fund_adj", ts_code=code, **self._date_kwargs(request)))
        if daily.empty or factors.empty:
            return daily
        if "trade_date" not in daily or "trade_date" not in factors or "adj_factor" not in factors:
            raise ValueError("Tushare fund_daily/fund_adj 缺少 ETF 复权所需字段")
        merged = daily.merge(factors[["trade_date", "adj_factor"]], on="trade_date", how="left")
        merged["adj_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce")
        base_factor = merged["adj_factor"].dropna()
        if base_factor.empty:
            return daily
        base_factor = float(base_factor.iloc[0])
        price_columns = [column for column in ("open", "high", "low", "close", "pre_close") if column in merged]
        factor = merged["adj_factor"]
        for column in price_columns:
            values = pd.to_numeric(merged[column], errors="coerce")
            merged[column] = values * factor if request.adjust.value == "hfq" else values * factor / base_factor
        return merged

    def get_minute(self, request: DataRequest) -> DataResult:
        frames = []
        for symbol in request.symbols:
            frame = self._call(
                "stk_mins",
                ts_code=self.ticker_mapper.to_tushare(symbol),
                freq=self._freq(request),
                **self._date_kwargs(request),
            )
            frames.append(self._frame(frame))
        return self._result(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), DataKind.MINUTE, request)

    def _pro_bar(self, code: str, request: DataRequest) -> Any:
        try:
            import tushare as ts
        except ImportError:
            api = self._api()
            method = getattr(api, "pro_bar", None)
            if method is None:
                raise ProviderUnavailable("复权行情需要 tushare.pro_bar")
            return method(
                ts_code=code, adj=self._adj(request), freq=self._freq(request),
                asset="E", **self._date_kwargs(request),
            )
        return ts.pro_bar(
            api=self._api(), ts_code=code, adj=self._adj(request), freq=self._freq(request),
            # Tushare 官方 pro_bar 的 E 包含股票和交易所基金；FD 是场外基金。
            asset="E",
            **self._date_kwargs(request),
        )

    def get_tick(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("Tushare Provider 没有统一 Tick 能力")

    def get_realtime(self, request: DataRequest) -> DataResult:
        raise NotImplementedError("Tushare Provider 没有统一实时订阅能力")

    def get_stock_basic(self, request: DataRequest) -> DataResult:
        kwargs = dict(request.options)
        if request.symbols:
            kwargs["ts_code"] = ",".join(self.ticker_mapper.to_tushare(item) for item in request.symbols)
        frame = self._call("stock_basic", **kwargs)
        return self._result(self._frame(frame), DataKind.STOCK_BASIC, request)

    def get_trade_calendar(self, request: DataRequest) -> DataResult:
        kwargs = dict(request.options)
        kwargs.update(self._date_kwargs(request))
        if request.exchange:
            kwargs["exchange"] = request.exchange.upper()
        frame = self._call("trade_cal", **kwargs)
        return self._result(self._frame(frame), DataKind.TRADE_CALENDAR, request)

    _VIP_PAGE_SIZE = 3000

    def get_financial(self, request: DataRequest) -> DataResult:
        table = request.table or "income"
        frames = []
        if not request.symbols and request.options.get("period"):
            # 全市场按报告期批量获取：走 ``{table}_vip`` 并在 Adapter 内分页，
            # 业务层只传 ``options={"period": "YYYYMMDD"}``。
            return self._result(self._financial_by_period(table, request), DataKind.FINANCIAL, request)
        for symbol in request.symbols:
            kwargs: dict[str, Any] = {"ts_code": self.ticker_mapper.to_tushare(symbol)}
            if request.end:
                kwargs["end_date"] = _date(request.end)
            if request.report_type:
                kwargs["report_type"] = request.report_type
            frames.append(self._frame(self._call(table, **kwargs)).assign(table=table))
        return self._result(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), DataKind.FINANCIAL, request)

    def _financial_by_period(self, table: str, request: DataRequest) -> pd.DataFrame:
        kwargs: dict[str, Any] = {"period": _date(request.options["period"])}
        if request.fields:
            kwargs["fields"] = ",".join(request.fields)
        if request.report_type:
            kwargs["report_type"] = request.report_type
        pages, offset = [], 0
        while True:
            page = self._frame(self._call(f"{table}_vip", offset=offset, limit=self._VIP_PAGE_SIZE, **kwargs))
            pages.append(page)
            offset += len(page)
            if len(page) < self._VIP_PAGE_SIZE:
                break
        frame = pd.concat(pages, ignore_index=True)
        # 分页边界可能重复返回同一行；内容完全相同的行只保留一条。
        frame = frame.drop_duplicates(ignore_index=True)
        if "ts_code" in frame:
            # VIP 接口偶尔返回 ``833243!1.BJ`` 之类的脏代码，无法映射到内部格式，直接丢弃。
            frame = frame[frame["ts_code"].astype(str).str.fullmatch(r"\d{6}\.(SH|SZ|BJ)")].reset_index(drop=True)
        if "update_flag" in frame:
            # 同一报告期可能同时返回原始(0)与更正后(1)记录；排到最后，
            # 使 Normalizer 的 keep="last" 去重保留更正后的口径。
            frame = frame.sort_values("update_flag", kind="stable", ignore_index=True)
        return frame.assign(table=table)

    def get_adj_factor(self, request: DataRequest) -> DataResult:
        frames = []
        for symbol in request.symbols:
            frames.append(self._frame(self._call("adj_factor", ts_code=self.ticker_mapper.to_tushare(symbol), **self._date_kwargs(request))))
        return self._result(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), DataKind.ADJ_FACTOR, request)

    def get_extension(self, data_kind: DataKind, request: DataRequest) -> DataResult:
        """在 Adapter 内调用 Tushare 专用接口，业务层不接触 ``pro``。"""

        method = self._extension_apis.get(data_kind)
        if method is None or data_kind not in self._supported:
            raise NotImplementedError(f"Tushare 不支持扩展数据类型 {data_kind.value}")
        kwargs = dict(request.options)
        # 统一请求模型中的日期优先级高于 options，避免业务层拼接 API 日期参数。
        if request.start is not None and "start_date" not in kwargs:
            kwargs["start_date"] = _date(request.start)
        if request.end is not None and "end_date" not in kwargs:
            kwargs["end_date"] = _date(request.end)
        if request.symbols and "ts_code" not in kwargs:
            kwargs["ts_code"] = ",".join(self.ticker_mapper.to_tushare(item) for item in request.symbols)
        if request.fields and "fields" not in kwargs:
            kwargs["fields"] = ",".join(request.fields)
        frame = self._frame(self._call(method, **kwargs))
        return self._result(frame, data_kind, request)

    def close(self) -> None:
        self.pro = None if self.pro is not None and not self.token else self.pro

    @staticmethod
    def _frame(value: Any) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.DataFrame):
            return value.copy()
        if isinstance(value, (list, tuple, dict)):
            return pd.DataFrame(value)
        raise ValueError(f"Tushare 返回了不支持的类型: {type(value).__name__}")

    def _result(self, frame: pd.DataFrame, kind: DataKind, request: DataRequest) -> DataResult:
        return DataResult(frame, self.name, kind, request.request_id, metadata={"provider_unit_contract": "tushare-vol-hand-amount-thousand-cny"})

    @staticmethod
    def _date_kwargs(request: DataRequest) -> dict[str, str]:
        kwargs: dict[str, str] = {}
        if request.start is not None:
            kwargs["start_date"] = _date(request.start)
        if request.end is not None:
            kwargs["end_date"] = _date(request.end)
        return kwargs

    @staticmethod
    def _adj(request: DataRequest) -> str | None:
        return {"none": None, "qfq": "qfq", "hfq": "hfq"}[request.adjust.value]

    @staticmethod
    def _freq(request: DataRequest) -> str:
        return {"1d": "D", "1w": "W", "1mon": "M", "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "60m": "60min"}.get(request.frequency, request.frequency)


def _date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "")[:8]


def _is_fund_code(ts_code: str) -> bool:
    """识别场内基金/ETF代码，供 Tushare Adapter 选择 fund_daily。"""

    code = ts_code.split(".", maxsplit=1)[0]
    return code.startswith(("15", "16", "18", "50", "51", "52", "56", "58"))
