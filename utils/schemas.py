import datetime
from typing import Any, Dict

from pydantic import BaseModel


class XtDataParams(BaseModel):
    """XtDataParams 模型"""

    symbol: str         # 股票代码，如 "000001"（需要加上交易所后缀，如 "000001.SZ"）
    period: str         # 数据周期，如 "1d"（日线）、"1h"（小时线）等
    start_date: str     # 开始时间，日期格式为 "YYYY-MM-DD"
    end_date: str       # 结束时间，日期格式为 "YYYY-MM-DD"
    dividend_type: str  # 利率类型，如 "qfq"（前复权）、"hfq"（后复权）等


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
