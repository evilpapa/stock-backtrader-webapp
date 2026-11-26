"""Streamlit 账户资产、净值和持仓视图。"""

import asyncio
import os
import sqlite3

import pandas as pd
import streamlit as st

from src.datahub.account_assets import SHANGHAI, AccountAssets, load_account_assets, save_account_assets
from src.datahub.providers.qmt_trading import read_test_account_assets
from src.datahub.providers.tonghuashun_ledger import fetch_live_accounts
from src.trading.qmt_paper import SIMULATED_ACCOUNT_ID


def _amount(value):
    return f"¥{value:,.2f}" if value is not None else "—"


def _render_overview(account: AccountAssets):
    source_time = (
        account.source_as_of.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
        if account.source_as_of else "未知"
    )
    fetch_time = account.fetched_at.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"来源数据时间 {source_time} · 获取时间 {fetch_time}（北京时间）")
    metrics = {
        "资产净值": account.net_asset,
        "总资产": account.total_asset,
        "可用资金": account.cash,
        "持仓市值": account.market_value,
        "负债" if account.source == "live" else "冻结资金": (
            account.liabilities if account.source == "live" else account.frozen_cash
        ),
    }
    for column, (label, value) in zip(st.columns(len(metrics)), metrics.items()):
        column.metric(label, _amount(value))
    if account.period_start and account.period_end:
        st.caption(f"收益统计区间 {account.period_start:%Y-%m-%d} 至 {account.period_end:%Y-%m-%d}")
        profit, returns = st.columns(2)
        profit.metric("区间盈亏", _amount(account.period_profit))
        returns.metric("区间收益率", f"{account.period_return:.2%}" if account.period_return is not None else "—")


def _render_history(account: AccountAssets):
    st.subheader("净值走势")
    if account.source == "test":
        st.caption("每日保留最近一次成功拉取的账户净值。")
    if not account.history:
        st.info("暂无净值记录。")
        return
    columns = {"资产净值（元）": "net_asset", "累计净值指数": "net_value_index"}
    available = [label for label, key in columns.items()
                 if any(getattr(point, key) is not None for point in account.history)]
    metric = st.radio("净值指标", available, horizontal=True, label_visibility="collapsed")
    values = [
        {"日期": point.day, metric: float(value)}
        for point in account.history
        if (value := getattr(point, columns[metric])) is not None
    ]
    frame = pd.DataFrame(values)
    if len(frame) == 1:
        st.dataframe(frame, hide_index=True, use_container_width=True)
        return
    st.line_chart(frame, x="日期", y=metric, height=280)


def _render_holdings(account: AccountAssets):
    st.subheader(f"持仓（{len(account.holdings)}）")
    if not account.holdings:
        st.info("当前账户空仓。")
        return
    fields = {
        "持仓数量": "quantity",
        "可卖数量": "sellable",
        "成本价": "cost_price",
        "现价": "price",
        "市值": "market_value",
        "持仓盈亏": "profit",
        "持仓收益率": "return_rate",
    }
    rows = []
    for holding in account.holdings:
        row = {"证券代码": holding.symbol, "证券名称": holding.name}
        for label, field in fields.items():
            value = getattr(holding, field)
            row[label] = float(value) if value is not None else None
        if account.net_asset and holding.market_value is not None:
            row["占净值比例"] = float(holding.market_value / account.net_asset)
        rows.append(row)
    frame = pd.DataFrame(rows).dropna(axis="columns", how="all")
    if "市值" in frame:
        frame = frame.sort_values("市值", ascending=False)
    st.dataframe(
        frame,
        hide_index=True,
        use_container_width=True,
        column_config={
            "成本价": st.column_config.NumberColumn(format="%.4f"),
            "现价": st.column_config.NumberColumn(format="%.4f"),
            "市值": st.column_config.NumberColumn(format="%.2f"),
            "持仓盈亏": st.column_config.NumberColumn(format="%.2f"),
            "持仓收益率": st.column_config.NumberColumn(format="percent"),
            "占净值比例": st.column_config.NumberColumn(format="percent"),
        },
    )


def render_asset_management():
    st.title("资产管理")
    selected = st.radio("账户类型", ("实盘", "测试盘"), horizontal=True)
    source = "live" if selected == "实盘" else "test"
    live_token = os.getenv("ASSET_THS_MCP_TOKEN")
    test_account = os.getenv("ASSET_QMT_TEST_ACCOUNT_ID", SIMULATED_ACCOUNT_ID).strip()
    st.caption("同花顺投资账本 MCP" if source == "live" else "QMT 测试账户")
    if st.button("刷新资产与持仓", key=f"refresh_assets_{source}"):
        if source == "live" and not live_token:
            st.info("页面可显示 ChatGPT 同花顺 MCP 导入的快照。页面直连刷新需要配置 ASSET_THS_MCP_TOKEN。")
        else:
            try:
                with st.spinner("正在查询账户数据…"):
                    if source == "live":
                        snapshots = asyncio.run(fetch_live_accounts(live_token))
                    else:
                        snapshots = [read_test_account_assets(test_account, vk_url=os.getenv("ASSET_QMT_TEST_VK_URL"))]
                    save_account_assets(snapshots)
                if snapshots:
                    st.success("资产和持仓已更新。")
                else:
                    st.info("同花顺投资账本未返回股票账户。")
            except TimeoutError:
                st.warning("账户查询超时。下方显示上次成功获取的数据（如有）。")
            except (sqlite3.Error, OSError):
                st.warning("资产同步未完成，请检查数据源连接与本地存储。下方显示已保存的快照（如有）。")
            except Exception:
                details = (
                    "请检查同花顺 MCP 授权和服务状态。"
                    if source == "live" else "请检查 QMT 测试账户及桥接服务配置。"
                )
                st.warning(f"刷新失败。{details} 下方显示上次成功获取的数据（如有）。")

    try:
        accounts = load_account_assets(source)
    except (sqlite3.Error, ValueError, OSError):
        st.error("无法读取本地资产快照。")
        return
    if source == "test":
        accounts = [account for account in accounts if account.account_key == test_account]
    if not accounts:
        st.info("当前没有已同步的账户数据。")
        return
    labels = {account.account_key: account.name for account in accounts}
    key = st.selectbox("账户", list(labels), format_func=labels.__getitem__, key=f"asset_account_{source}")
    account = next(item for item in accounts if item.account_key == key)
    _render_overview(account)
    _render_history(account)
    _render_holdings(account)
