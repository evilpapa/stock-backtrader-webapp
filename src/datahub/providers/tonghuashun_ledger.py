"""同花顺投资账本 MCP 的股票账户只读适配器。"""

import asyncio
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.datahub.account_assets import (
    SHANGHAI,
    AccountAssets,
    AssetPoint,
    Holding,
    holding_symbol,
    save_account_assets,
)

DEFAULT_MCP_URL = "https://tzzb.10jqka.com.cn/mcp"
STOCK_GROUPS = {
    "fund_key": "fundKey",
    "rzrq_fund_key": "rzrqFundKey",
    "manual_id": "manualId",
}
HOLDING_FIELDS = {
    "cost_price": "costPrice",
    "price": "currentPrice",
    "market_value": "marketValue",
    "profit": "holdProfit",
    "return_rate": "holdRate",
}


def normalize_snapshot(
    group: str,
    account: dict,
    positions: dict,
    pnl: dict,
    start: date,
    end: date,
    fetched_at: datetime,
) -> AccountAssets:
    sync_time = account.get("lastSyncTime")
    source_as_of = datetime.fromisoformat(sync_time) if sync_time else None
    if source_as_of is not None and source_as_of.tzinfo is None:
        source_as_of = source_as_of.replace(tzinfo=SHANGHAI)
    holdings = [
        Holding(
            symbol=holding_symbol(str(row["stockCode"])),
            name=row.get("stockName") or "",
            quantity=row["holdQuantity"],
            **{field: row.get(key) if row.get(key) != "" else None for field, key in HOLDING_FIELDS.items()},
        )
        for row in positions["holdings"]
    ]
    history = [
        AssetPoint(
            day=datetime.strptime(row["time"], "%Y%m%d").date(),
            net_asset=row["netAsset"],
            net_value_index=row.get("totalNetValueIndex"),
        )
        for row in pnl["netValueTrend"]
    ]
    total = Decimal(str(positions["totalAsset"]))
    liability = positions.get("totalLiability")
    net_asset = total - Decimal(str(liability)) if liability not in (None, "") else None
    return AccountAssets(
        source="live",
        account_key=f"{group}:{account['id']}",
        name=account["name"],
        fetched_at=fetched_at,
        source_as_of=source_as_of,
        total_asset=total,
        net_asset=net_asset,
        liabilities=liability if liability != "" else None,
        cash=positions.get("availableFunds"),
        market_value=positions.get("totalMarketValue"),
        holdings=holdings,
        history=history,
        period_start=start,
        period_end=max((point.day for point in history if start <= point.day <= end), default=None),
        period_profit=pnl.get("totalProfitLoss"),
        period_return=pnl.get("totalReturnRate"),
    )


async def _call(session, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"投资账本 MCP 调用失败（{name}）")
    payload = result.structuredContent
    if payload is None:
        text = [item.text for item in result.content if item.type == "text"]
        payload = json.loads("".join(text))
    if not isinstance(payload, dict):
        raise ValueError(f"投资账本 MCP 响应无效（{name}）")
    return payload


async def query_accounts(session, fetched_at: datetime) -> list[AccountAssets]:
    end = fetched_at.astimezone(SHANGHAI).date()
    start = end - timedelta(days=29)
    groups = await _call(session, "promptAccountSelection", {"scope": "stock"})
    if not STOCK_GROUPS.keys() & groups.keys():
        raise ValueError("投资账本 MCP 未返回股票账户分组")
    snapshots = []
    for group, parameter in STOCK_GROUPS.items():
        for account in groups.get(group, []):
            if account.get("param", parameter) != parameter or not account.get("id"):
                raise ValueError("投资账本 MCP 返回的账户类型或 ID 无效")
            ids = dict.fromkeys(STOCK_GROUPS.values(), "") | {parameter: str(account["id"])}
            positions = await _call(session, "queryStockPosition", ids)
            pnl = await _call(session, "queryPnlSummary", ids | {
                "fundId": "",
                "custId": "",
                "startDate": start.strftime("%Y%m%d"),
                "endDate": end.strftime("%Y%m%d"),
            })
            snapshots.append(normalize_snapshot(group, account, positions, pnl, start, end, fetched_at))
    return snapshots


async def fetch_live_accounts(token: str) -> list[AccountAssets]:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    url = os.environ.get("ASSET_THS_MCP_URL") or DEFAULT_MCP_URL
    async with asyncio.timeout(90), httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(45),
    ) as client:
        async with streamable_http_client(url, http_client=client) as (reader, writer, _):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
                await session.initialize()
                return await query_accounts(session, datetime.now(SHANGHAI))


def import_chatgpt_snapshot(payload: dict) -> AccountAssets:
    """接收通过 ChatGPT 同花顺投资账本 MCP 获取的单账户响应。"""
    group = payload["group"]
    account = payload["account"]
    if account.get("param") != STOCK_GROUPS[group]:
        raise ValueError("投资账本账户分组与查询参数不匹配")
    snapshot = normalize_snapshot(
        group, account, payload["positions"], payload["pnl"],
        date.fromisoformat(payload["start"]), date.fromisoformat(payload["end"]),
        datetime.now(SHANGHAI),
    )
    save_account_assets([snapshot])
    return snapshot


if __name__ == "__main__":
    import sys

    import_chatgpt_snapshot(json.load(sys.stdin))
