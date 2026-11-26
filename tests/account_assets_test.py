from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.datahub.account_assets import SHANGHAI, load_account_assets, save_account_assets
from src.datahub.providers.qmt_trading import read_test_account_assets
from src.datahub.providers.tonghuashun_ledger import query_accounts


class FakeLedger:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        data = {
            "promptAccountSelection": {
                "fund_key": [{"id": "10", "name": "普通账户", "param": "fundKey"}],
                "rzrq_fund_key": [{"id": "10", "name": "信用账户", "param": "rzrqFundKey"}],
            },
            "queryStockPosition": {
                "totalAsset": "10000", "totalLiability": "2000", "availableFunds": "0",
                "totalMarketValue": "8000", "holdings": [
                    {"stockCode": "600000", "holdQuantity": "100", "holdProfit": 0},
                    {"stockCode": "00700", "holdQuantity": "10", "holdProfit": ""},
                ],
            },
            "queryPnlSummary": {
                "netValueTrend": [{"time": "20261120", "netAsset": "7990", "totalNetValueIndex": "1055"}],
                "totalProfitLoss": "6", "totalReturnRate": "0.01",
            },
        }
        return SimpleNamespace(isError=False, structuredContent=data[name])


def test_ledger_queries_each_account_group_and_keeps_reported_values():
    import asyncio

    session = FakeLedger()
    snapshots = asyncio.run(query_accounts(session, datetime(2026, 11, 26, tzinfo=SHANGHAI)))
    assert session.calls[1] == ("queryStockPosition", {"fundKey": "10", "rzrqFundKey": "", "manualId": ""})
    assert session.calls[4][1]["rzrqFundKey"] == "10"
    assert session.calls[4][1]["fundKey"] == ""
    assert session.calls[4][1]["startDate"] == "20261028"
    assert [snapshot.account_key for snapshot in snapshots] == ["fund_key:10", "rzrq_fund_key:10"]
    first = snapshots[0]
    assert first.net_asset == Decimal("8000")
    assert first.cash == Decimal(0)
    assert first.period_end == date(2026, 11, 20)
    assert first.history[0].net_value_index == Decimal("1055")
    assert [(holding.symbol, holding.profit) for holding in first.holdings] == [
        ("600000.SH", Decimal(0)), ("00700", None),
    ]


class FakeQmt:
    def __init__(self):
        self.client = SimpleNamespace(account_id="10001", call=self.ping)
        self.stopped = False
        self.total_asset = "2000"
        self.positions = [
            {"account_id": "10001", "stock_code": "000001.SZ", "volume": 100,
             "can_use_volume": 50, "cost_price": "8.15", "market_value": "1000"},
        ]

    def ping(self, method):
        assert method == "ping"
        return {"pong": True, "account_id": "10001"}

    def query_stock_asset(self, account):
        assert account.account_id == "10001"
        return {"account_id": "10001", "total_asset": self.total_asset, "cash": "1000"}

    def query_stock_positions(self, account):
        assert account.account_id == "10001"
        return self.positions

    def stop(self):
        self.stopped = True


def test_qmt_test_snapshot_persists_daily_history_and_rejects_stale_replacement(tmp_path):
    bridge = FakeQmt()
    account = read_test_account_assets("10001", trader=bridge)
    assert bridge.stopped
    assert account.holdings[0].profit == Decimal("185")
    assert account.holdings[0].sellable == Decimal("50")

    location = tmp_path / "assets.sqlite3"
    save_account_assets([account], location)
    bridge.total_asset = "3000"
    latest = read_test_account_assets("10001", trader=bridge)
    save_account_assets([latest], location)

    prior_day = latest.history[0].day - timedelta(days=1)
    history = account.history + [account.history[0].model_copy(update={"day": prior_day})]
    save_account_assets([account.model_copy(update={"history": history})], location)
    saved, = load_account_assets("test", location)
    assert saved.net_asset == Decimal("3000")
    assert [(point.day, point.net_asset) for point in saved.history] == [
        (prior_day, Decimal("2000")), (latest.history[0].day, Decimal("3000")),
    ]
    assert load_account_assets("live", location) == []


def test_qmt_rejects_other_accounts_and_incomplete_positions():
    bridge = FakeQmt()
    with pytest.raises(ValueError, match="configured QMT account differs"):
        read_test_account_assets("20002", trader=bridge)
    assert bridge.stopped
    bridge.positions = None
    with pytest.raises(RuntimeError, match="响应不完整"):
        read_test_account_assets("10001", trader=bridge)
