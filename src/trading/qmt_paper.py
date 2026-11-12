"""BigQMT 模拟账户委托适配器；调用方必须事先人工核验券商仿真环境。

STOCK 是账户品种，并不能证明账户是仿真账户。本模块不启用服务端委托权限。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from src.utils.commission import ChinaStockCommission

SHANGHAI = ZoneInfo('Asia/Shanghai')
# 待接入实时行情时效、交易日历、涨跌停、账户委托状态的可验证检查后才可启用。
_SUBMISSION_ENABLED = False
SIMULATED_ACCOUNT_ID = '86962531'


class Broker(Protocol):
    def snapshot(self) -> dict: ...
    def buy_limit(self, symbol: str, quantity: int, price: float, remark: str) -> int: ...


class BigQmtBroker:
    """只支持股票买入限价委托，不自动重试、不撤单。"""
    def __init__(self, account_id: str):
        from bigqmt_signal_trader.xtquant_compat import StockAccount, configure, xt_trader
        configure()
        if str(xt_trader.client.account_id) != account_id:
            raise ValueError('桥接服务配置的账号与委托账号不一致')
        self.trader = xt_trader
        self.account = StockAccount(account_id, 'STOCK')
        self.account_id = account_id

    def snapshot(self) -> dict:
        asset = self.trader.query_stock_asset(self.account)
        positions = self.trader.query_stock_positions(self.account)
        orders = self.trader.query_stock_orders(self.account)
        if asset is None or positions is None or orders is None:
            raise RuntimeError('账户、持仓或委托查询为空响应，停止交易')
        actual = str(getattr(asset, 'account_id', ''))
        if actual != self.account_id:
            raise RuntimeError('返回账户与目标账户不一致')
        cash = float(getattr(asset, 'cash'))
        if not math.isfinite(cash) or cash < 0:
            raise RuntimeError('账户现金无效')
        return {'account_id': actual, 'cash': cash, 'positions': positions, 'orders': orders}

    def buy_limit(self, symbol: str, quantity: int, price: float, remark: str) -> int:
        from bigqmt_signal_trader.xtquant_compat import STOCK_BUY
        from xtquant.xtconstant import FIX_PRICE

        return self.trader.order_stock(self.account, symbol, STOCK_BUY, quantity, FIX_PRICE, price,
                                       'fcf_paper', remark)


def validate_plan(plan: dict, now: datetime, *, max_total: float = 200000.0) -> float:
    """验证日期、限价、整手和总预算；不替代实时报价及交易所规则检查。"""
    if now.tzinfo is None:
        raise ValueError('需要带时区的当前时间')
    today = now.astimezone(SHANGHAI).date()
    if plan.get('environment') != 'broker_simulation':
        raise ValueError('计划必须标记为券商仿真环境；该标记本身不能证明账户类型')
    if plan.get('account_id') != SIMULATED_ACCOUNT_ID:
        raise ValueError('账户不在本次授权范围')
    if date.fromisoformat(plan['trade_date']) != today:
        raise ValueError('交易日期不是上海当前日期')
    signal = date.fromisoformat(plan['signal_date'])
    if signal > today or (today - signal).days > 7:
        raise ValueError('选股信号超过 7 个自然日或来自未来，拒绝交易')
    items = plan.get('orders')
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise ValueError('委托数必须为 1 到 30')
    seen = set()
    total = 0.0
    commission = ChinaStockCommission()
    for item in items:
        symbol, quantity, price = item.get('symbol'), item.get('quantity'), item.get('limit_price')
        if not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol) or symbol in seen:
            raise ValueError('证券代码无效或重复')
        seen.add(symbol)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0 or quantity % 100:
            raise ValueError('数量必须为正的 100 股整数倍')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError('限价必须是正的有限数字')
        total += quantity * price + commission.getcommission(quantity, price)
    if total > max_total + 1e-8:
        raise ValueError('订单总额加佣金超过 20 万元预算')
    return total


def plan_digest(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def submit_plan(broker: Broker, plan: dict, journal: Path, *, now: datetime, confirmation: str,
                simulation_verified: bool) -> list[dict]:
    """持久化意图后逐笔提交，任何失败或未知状态立即停止且不自动重试。

    必须先由用户核验券商侧仿真账户，并确认完整计划 SHA256；重复运行同一计划被拒绝。
    """
    if not _SUBMISSION_ENABLED:
        raise RuntimeError('模拟委托功能尚未启用：缺少实时行情、交易规则和账户状态核验')
    total = validate_plan(plan, now)
    digest = plan_digest(plan)
    if not simulation_verified or confirmation != digest:
        raise ValueError('必须核验仿真账户并确认完整计划 SHA256')
    snapshot = broker.snapshot()
    if snapshot['account_id'] != plan['account_id'] or snapshot['cash'] < total:
        raise ValueError('账户不匹配或可用资金不足')
    if snapshot['positions'] or snapshot['orders']:
        raise ValueError('账户存在持仓或当日委托，不能按空仓计划买入；请先人工核对')
    journal.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with sqlite3.connect(journal) as db:
        db.execute('CREATE TABLE IF NOT EXISTS plans (digest TEXT PRIMARY KEY, account_id TEXT NOT NULL, trade_date TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(account_id, trade_date))')
        db.execute('CREATE TABLE IF NOT EXISTS orders (digest TEXT, idx INTEGER, symbol TEXT, quantity INTEGER, price REAL, status TEXT, broker_id TEXT, detail TEXT, PRIMARY KEY (digest, idx))')
        try:
            db.execute('INSERT INTO plans VALUES (?, ?, ?, ?, ?)',
                       (digest, plan['account_id'], plan['trade_date'], now.isoformat(), 'in_progress'))
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise RuntimeError('该计划已提交或曾尝试提交；禁止重复提交，请人工对账') from exc
        for idx, item in enumerate(plan['orders']):
            remark = f'fcf{digest[:8]}{idx:02d}'
            db.execute('INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (digest, idx, item['symbol'], item['quantity'], item['limit_price'], 'sending', None, remark))
            db.commit()  # 先落盘；进程异常时 sending 视为结果未知，绝不自动重试
            try:
                order_id = broker.buy_limit(item['symbol'], item['quantity'], item['limit_price'], remark)
                if not isinstance(order_id, int) or order_id <= 0:
                    raise RuntimeError(f'券商未返回有效委托编号: {order_id!r}')
            except Exception as exc:
                db.execute('UPDATE orders SET status=?, detail=? WHERE digest=? AND idx=?', ('unknown', str(exc), digest, idx))
                db.execute('UPDATE plans SET status=? WHERE digest=?', ('stopped', digest))
                db.commit()
                raise RuntimeError('委托结果可能未知，已停止；请到券商查询委托成交，禁止盲目重试') from exc
            db.execute('UPDATE orders SET status=?, broker_id=? WHERE digest=? AND idx=?', ('submitted', str(order_id), digest, idx))
            db.commit()
            results.append({'symbol': item['symbol'], 'order_id': order_id, 'remark': remark, 'status': 'submitted'})
        db.execute('UPDATE plans SET status=? WHERE digest=?', ('submitted', digest))
        db.commit()
    return results
