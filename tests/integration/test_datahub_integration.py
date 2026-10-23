"""真实数据源集成测试（显式 opt-in，不属于普通单元测试）。"""

from __future__ import annotations

import os

import pytest

from src.datahub import DataRequest, DataKind, create_service

pytestmark = pytest.mark.integration


def test_tushare_daily_integration() -> None:
    if os.getenv("DATAHUB_RUN_TUSHARE_INTEGRATION") != "1":
        pytest.skip("设置 DATAHUB_RUN_TUSHARE_INTEGRATION=1 才运行真实 Tushare 测试")
    if not os.getenv("TUSHARE_TOKEN"):
        pytest.skip("缺少 TUSHARE_TOKEN")
    service = create_service()
    try:
        frame = service.get_daily(DataRequest(symbols=("000001.SZ",), start="2024-01-02", end="2024-01-03"), use_cache=False)
        assert not frame.empty
        assert frame["source"].iloc[0] == "tushare"
    finally:
        service.close()


def test_xtquant_integration() -> None:
    if os.getenv("DATAHUB_RUN_QMT_INTEGRATION") != "1":
        pytest.skip("设置 DATAHUB_RUN_QMT_INTEGRATION=1 才运行真实 QMT 测试")
    service = create_service()
    try:
        frame = service.get(DataKind.REALTIME, DataRequest(symbols=("000001.SZ",)), use_cache=False)
        assert "source" in frame.attrs or "source" in frame.columns
    finally:
        service.close()
