---
name: xtquant-xttrade
description: Retrieve and use the official XtQuant xttrader documentation from dict.thinktrader.net for questions about xtquant.xttrader trading APIs, trader lifecycle, account subscription, order placement and cancelation, stock and futures queries, credit account queries, fund transfer, generic data export/query, appointment borrowing APIs, callback classes, xtconstant enums, and xttrader data structures. Use when the user asks about xttrader function signatures, return objects, callback flows, account types, order types, or wants example code aligned with the official docs.
---

# xtquant-xttrade

Use this skill as the authoritative reference for the official XtQuant xttrader trading manual.

## Primary reference

Read in this order:

1. `references/00-index.md` (entrypoint + function index)
2. The matching split volume:
   - `references/概述.md`
   - `references/1-数据字典.md`
   - `references/2-数据结构说明.md`
   - `references/3-系统与操作接口.md`
   - `references/4-查询接口.md`
   - `references/5-约券与回调.md`
   - `references/6-FAQ.md`

Source:

- https://dict.thinktrader.net/nativeApi/xttrader.html?id=olYCD5

Read this skill when the user asks about:

- `xtquant.xttrader` 交易接口签名、参数和返回值
- `XtQuantTrader` 生命周期：创建、启动、连接、订阅、阻塞运行、停止
- 下单、撤单、异步回报、错误回调
- 资产、委托、成交、持仓、期货持仓统计查询
- 信用账户、两融标的、可融券、担保品、约券接口
- `xtconstant` 中市场、账号类型、委托类型、报价类型、状态等枚举
- `XtAsset`、`XtOrder`、`XtTrade`、`XtPosition` 等对象字段
- xttrader 常见排障问题，例如没有回调、异步下单如何拿订单号、同步查询卡住、`order_id` 与 `order_sysid` 的区别

Do not use this skill for:

- `xtquant.xtdata` 行情下载与订阅接口
- QMT `ContextInfo` 策略生命周期问题
- 非 `xttrader` 模块的第三方交易封装

## Core operating model

- `xttrader` 通过 `MiniQmt` 进行交易、撤单、查询和主推接收。
- 标准流程通常是：
  - 创建 `XtQuantTrader(path, session_id)`
  - `register_callback(callback)`
  - `start()`
  - `connect()`
  - `subscribe(account)`
  - 调用下单/查询接口
  - `run_forever()` 持续接收回调
- `connect()` 是一次性连接；断开后不会自动重连，需要再次主动调用。
- 异步接口正常返回 `seq` 后，结果通常通过对应回调推送返回。
- 在推送回调中直接调用同步查询接口，可能受到时序影响；必要时考虑异步查询或 `set_relaxed_response_order_enabled(True)`。

## Workflow

1. 先在文档中定位精确函数名和所属分类：系统设置、操作、查询、信用、约券、回调、数据结构、数据字典。
2. 明确用户问的是“发起操作”还是“接收回报”，不要把同步返回值和异步主推混在一起。
3. 回答交易相关问题时，优先说明前置条件：
   - 是否已经 `start()` 和 `connect()`
   - 是否已经 `subscribe(account)`
   - 是否需要注册 `XtQuantTraderCallback`
   - 账号类型是否匹配，例如 `STOCK`、`CREDIT`、`FUTURE`
4. 返回值说明必须保留对象类型差异，例如：
   - `query_stock_asset` 返回 `XtAsset` 或 `None`
   - `query_stock_orders` 返回 `list[XtOrder]` 或 `None`
   - `order_stock_async` 返回 `seq`，后续经 `on_order_stock_async_response` 回推
5. 如果给示例代码，保持最小可运行，优先展示：
   - trader 初始化与连接
   - 注册回调
   - `subscribe(account)`
   - 同步/异步下单与撤单
6. 如果表格抓取后字段排版不稳定，要明确说明“字段名和枚举以官方文档为准”。

## Common routing

- Trader 初始化与连接 → `XtQuantTrader`, `register_callback`, `start`, `connect`, `run_forever`, `stop`
- 订阅与反订阅 → `subscribe`, `unsubscribe`
- 同步下单 → `order_stock`
- 异步下单 → `order_stock_async`, `on_order_stock_async_response`
- 同步撤单 → `cancel_order_stock`, `cancel_order_stock_sysid`
- 异步撤单 → `cancel_order_stock_async`, `cancel_order_stock_sysid_async`, `on_cancel_error`
- 股票/期货查询 → `query_stock_asset`, `query_stock_orders`, `query_stock_trades`, `query_stock_positions`, `query_position_statistics`
- 信用查询 → `query_credit_detail`, `query_stk_compacts`, `query_credit_subjects`, `query_credit_slo_code`, `query_credit_assure`
- 其他查询 → `query_new_purchase_limit`, `query_ipo_data`, `query_account_infos`, `query_account_status`, `query_com_fund`, `query_com_position`, `export_data`, `query_data`
- 划拨与外部成交 → `fund_transfer`, `sync_transaction_from_external`
- 约券 → `smt_query_quoter`, `smt_negotiate_order_async`, `smt_query_compact`, `on_smt_appointment_async_response`
- 枚举与状态 → `xtconstant.*`

## Important distinctions

### 同步接口 vs 异步接口

- 同步下单/撤单接口直接返回订单编号或结果码。
- 异步接口先返回请求序号 `seq`，后续结果通过回调对象推送。
- 异步接口的“请求已发出”不等于“柜台最终已成交”。

### 订单编号 vs 柜台合同编号

- `order_id` 是接口侧订单编号。
- `order_sysid` 是柜台合同编号。
- 撤单接口按这两个标识分别提供不同版本，不要混用。

### 股票查询 vs 信用查询

- 普通股票查询主要返回 `XtAsset`、`XtOrder`、`XtTrade`、`XtPosition`。
- 信用查询返回 `XtCreditDetail`、`StkCompacts`、`CreditSubjects`、`CreditSloCode`、`CreditAssure`。
- 信用接口通常需要 `StockAccount(..., 'CREDIT')`。

### 查询返回 vs 主推回调

- `query_*` 是主动查询当前快照。
- `on_stock_order`、`on_stock_trade`、`on_account_status` 等是状态变化主推。
- 如果用户要“实时跟踪”，只查一次 `query_*` 不够，需要订阅并保持事件循环。

### 宽松时序设置

- `set_relaxed_response_order_enabled(True)` 可以避免在推送回调里调用同步请求时被卡住。
- 但开启后，推送和查询返回在时间顺序上会更不严格。
- 一般优先推荐异步查询或避免在推送回调中做重同步查询。

## Answering rules

- 优先给出文档中的精确函数签名。
- 明确账户通常用 `StockAccount(account_id, account_type)` 表示；账号类型要和接口场景一致。
- 明确 `order_type`、`price_type`、`market`、`account_type` 等参数优先引用 `xtconstant` 原名。
- 当用户问对象字段时，优先引用数据结构说明页中的字段名。
- 当用户问状态、市场、报价方式、开平标记时，优先引用数据字典页中的枚举。
- 生成代码示例时，区分“文档解释/示例代码”和“真实交易执行”。
- 不把交易接口文档问题扩展成投资建议。

## Minimal example patterns

### Trader 初始化

```python
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount


class MyCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        print('connection lost')


path = r'D:\迅投极速交易终端 睿智融科版\userdata_mini'
session_id = 123456
xt_trader = XtQuantTrader(path, session_id)
xt_trader.register_callback(MyCallback())
xt_trader.start()
xt_trader.connect()

account = StockAccount('1000000365')
xt_trader.subscribe(account)
```

### 同步下单和撤单

```python
from xtquant import xtconstant

order_id = xt_trader.order_stock(
    account,
    '600000.SH',
    xtconstant.STOCK_BUY,
    1000,
    xtconstant.FIX_PRICE,
    10.5,
    'strategy1',
    'order_test',
)

cancel_result = xt_trader.cancel_order_stock(account, order_id)
```

### 异步下单

```python
seq = xt_trader.order_stock_async(
    account,
    '600000.SH',
    xtconstant.STOCK_BUY,
    1000,
    xtconstant.FIX_PRICE,
    10.5,
    'strategy1',
    'order_test',
)
```

## When to be cautious

- 用户问“为什么没有回调”时，先检查是否注册了 callback、是否 `connect()` 成功、是否 `subscribe(account)` 成功、进程是否仍在运行。
- 用户问“为什么同步查询卡住”时，先检查是否在推送回调内部直接调用同步查询接口。
- 用户问信用或约券接口时，先确认账户类型是否正确。
- 用户问市价单时，提醒文档说明模拟环境通常不支持市价方式报单。
- 用户问撤单标识时，先确认要用 `order_id` 还是 `order_sysid`。
