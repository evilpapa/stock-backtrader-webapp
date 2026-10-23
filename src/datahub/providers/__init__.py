"""第三方数据源 Adapter。"""

from .tushare import TushareProvider
from .xtquant import XtQuantProvider

__all__ = ["TushareProvider", "XtQuantProvider"]
