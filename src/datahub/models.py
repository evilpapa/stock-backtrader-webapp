"""DataHub 的请求、结果和统一事件模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Mapping, Sequence

import pandas as pd


class DataKind(StrEnum):
    """统一数据类型名，也是 YAML 路由配置的 key。"""

    DAILY = "daily"
    MINUTE = "minute"
    TICK = "tick"
    REALTIME = "realtime"
    STOCK_BASIC = "stock_basic"
    TRADE_CALENDAR = "trade_calendar"
    FINANCIAL = "financial"
    ADJ_FACTOR = "adj_factor"
    LEVEL2 = "level2"
    # Tushare/其它 Provider 的专用扩展能力。它们仍通过 DataHub 路由，
    # 但保留原始字段，便于行业、ETF 和微盘研究使用。
    ETF_BASIC = "etf_basic"
    ETF_SHARE = "etf_share"
    FUND_DAILY = "fund_daily"
    FUND_ADJ = "fund_adj"
    INDEX_DAILY = "index_daily"
    INDEX_MEMBER = "index_member"
    INDEX_WEIGHT = "index_weight"
    CI_DAILY = "ci_daily"
    DAILY_BASIC = "daily_basic"
    MONEY_FLOW = "money_flow"
    ST = "st"
    HOT_RANK = "hot_rank"
    BOARD_MEMBER = "board_member"
    SECTOR_MEMBER = "sector_member"
    DAILY_BULK = "daily_bulk"


class Adjust(StrEnum):
    """统一复权口径。"""

    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class BarTimestamp(StrEnum):
    """K 线 datetime 的业务语义。"""

    START = "start"
    END = "end"


@dataclass(frozen=True)
class DataRequest:
    """历史行情/基础数据通用请求。

    ``as_of`` 用于财务数据的 point-in-time 查询：只有公告时间不晚于该时点
    的记录才允许进入回测数据。
    """

    symbols: tuple[str, ...] = ()
    start: str | date | datetime | None = None
    end: str | date | datetime | None = None
    frequency: str = "1d"
    adjust: Adjust | str = Adjust.NONE
    fields: tuple[str, ...] = ()
    exchange: str | None = None
    as_of: str | date | datetime | None = None
    report_type: str | None = None
    table: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "fields", tuple(self.fields))
        adjust = str(self.adjust).lower()
        adjust = {"front": "qfq", "back": "hfq"}.get(adjust, adjust)
        object.__setattr__(self, "adjust", Adjust(adjust))
        if self.start is not None and self.end is not None:
            start = pd.Timestamp(self.start)
            end = pd.Timestamp(self.end)
            if start > end:
                raise ValueError(f"start 必须不晚于 end: {self.start!r} > {self.end!r}")

    @property
    def symbol(self) -> str | None:
        """兼容单证券 Provider 的便捷属性。"""

        return self.symbols[0] if self.symbols else None

    def cache_key(self, provider: str | None = None) -> str:
        """生成包含口径的稳定缓存键。"""

        payload = {
            "provider": provider,
            "symbols": self.symbols,
            "start": _serialize_date(self.start),
            "end": _serialize_date(self.end),
            "frequency": self.frequency,
            "adjust": self.adjust.value,
            "fields": self.fields,
            "exchange": self.exchange,
            "as_of": _serialize_date(self.as_of),
            "report_type": self.report_type,
            "table": self.table,
            "options": dict(self.options),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FinancialRequest(DataRequest):
    """财务数据请求的语义化别名。"""

    table: str = "income"


@dataclass
class DataResult:
    """Provider 返回的统一结果包装。

    ``data`` 一定是 DataFrame；调用方不需要理解第三方返回的 dict/ndarray
    结构。Normalizer 完成后，``data.attrs`` 还会带有版本和时间语义。
    """

    data: pd.DataFrame
    source: str
    data_kind: DataKind
    request_id: str | None = None
    timestamp_semantics: BarTimestamp = BarTimestamp.START
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.data.empty


@dataclass(frozen=True)
class RealtimeEvent:
    """实时行情 Observer 收到的统一事件。"""

    symbol: str
    data_kind: DataKind
    datetime: pd.Timestamp
    payload: Mapping[str, Any]
    source: str
    subscription_id: str | None = None


def _serialize_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def as_symbols(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """将单代码/代码序列统一为 tuple。"""

    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)
