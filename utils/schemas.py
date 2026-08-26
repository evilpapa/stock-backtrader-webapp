import datetime
from typing import Any, Dict

from pydantic import BaseModel


class DataSourceParams(BaseModel):
    """Market data source settings."""

    data_source: str = "xtdata"
    dividend_type: str = "front"
    qmt_base_url: str = "http://0.0.0.0:10086"
    qmt_token: str = "123456789"
    qmt_timeout: float = 10.0


class XtDataParams(DataSourceParams):
    """XtDataParams 模型"""

    symbol: str         # 股票代码，如 "000001"（需要加上交易所后缀，如 "000001.SZ"）
    period: str         # 数据周期，如 "1d"（日线）、"1h"（小时线）等
    start_date: str     # 开始时间，日期格式为 "YYYY-MM-DD"
    end_date: str       # 结束时间，日期格式为 "YYYY-MM-DD"


class BacktraderParams(BaseModel):
    """BacktraderParams 模型"""

    start_date: datetime.date     # 开始时间
    end_date: datetime.date       # 结束时间
    start_cash: float             # 初始资金
    commission_fee: float         # 佣金费用率，如 0.001 表示万分之一
    stake: int                    # 每次交易的固定股数


class StrategyBase(BaseModel):
    """策略基础模型"""

    name: str
    params: Dict[str, Any]
