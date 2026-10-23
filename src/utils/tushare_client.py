"""Tushare 行情客户端。

项目的回测、Streamlit 页面和批量同步脚本都通过本模块读取行情。Tushare
返回的字段和日期格式在这里统一成项目内部使用的 ``date/open/high/low``
格式，业务层不需要感知 Tushare 的接口差异。
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd





