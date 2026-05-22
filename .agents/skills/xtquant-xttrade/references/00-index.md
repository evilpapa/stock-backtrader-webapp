# xtquant-xttrade 二次整理索引

来源：[XtQuant.Xttrade 交易模块](https://dict.thinktrader.net/nativeApi/xttrader.html?id=olYCD5)

## 参考文件

- 分卷（推荐检索）：
  - `概述.md`
  - `1-数据字典.md`
  - `2-数据结构说明.md`
  - `3-系统与操作接口.md`
  - `4-查询接口.md`
  - `5-约券与回调.md`
  - `6-FAQ.md`

## 检索建议

- 想找 trader 初始化、连接、下单、撤单：优先看 `3-系统与操作接口.md`
- 想找资产/委托/成交/持仓/信用查询：优先看 `4-查询接口.md`
- 想找约券和异步回调：优先看 `5-约券与回调.md`
- 想排查常见问题：优先看 `6-FAQ.md`
- 想确认市场、账号类型、委托类型、报价类型、状态枚举：优先看 `1-数据字典.md`
- 想确认对象字段：优先看 `2-数据结构说明.md`

## 函数索引

### 系统设置接口

- `XtQuantTrader(path, session_id)`
- `register_callback(callback)`
- `start()`
- `connect()`
- `stop()`
- `run_forever()`
- `set_relaxed_response_order_enabled(enabled)`

### 操作接口

- `subscribe(account)`
- `unsubscribe(account)`
- `order_stock(account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark)`
- `order_stock_async(account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark)`
- `cancel_order_stock(account, order_id)`
- `cancel_order_stock_sysid(account, market, order_sysid)`
- `cancel_order_stock_async(account, order_id)`
- `cancel_order_stock_sysid_async(account, market, order_sysid)`
- `fund_transfer(account, transfer_direction, price)`
- `sync_transaction_from_external(operation, data_type, account, deal_list)`

### 股票与期货查询接口

- `query_stock_asset(account)`
- `query_stock_orders(account, cancelable_only=False)`
- `query_stock_trades(account)`
- `query_stock_positions(account)`
- `query_position_statistics(account)`

### 信用查询接口

- `query_credit_detail(account)`
- `query_stk_compacts(account)`
- `query_credit_subjects(account)`
- `query_credit_slo_code(account)`
- `query_credit_assure(account)`

### 其他查询接口

- `query_new_purchase_limit(account)`
- `query_ipo_data()`
- `query_account_infos()`
- `query_account_status()`
- `query_com_fund(account)`
- `query_com_position(account)`
- `export_data(account, result_path, data_type, start_time=None, end_time=None, user_param={})`
- `query_data(account, result_path, data_type, start_time=None, end_time=None, user_param={})`

### 约券相关接口

- `smt_query_quoter(account)`
- `smt_negotiate_order_async(account, src_group_id, order_code, date, amount, apply_rate, dict_param={})`
- `smt_query_compact(account)`

### 回调类

- `on_disconnected()`
- `on_account_status(data)`
- `on_stock_order(data)`
- `on_stock_trade(data)`
- `on_order_error(data)`
- `on_cancel_error(data)`
- `on_order_stock_async_response(data)`
- `on_smt_appointment_async_response(data)`

## 对象索引

- `XtAsset`
- `XtOrder`
- `XtTrade`
- `XtPosition`
- `XtPositionStatistics`
- `XtOrderResponse`
- `XtCancelOrderResponse`
- `XtOrderError`
- `XtCancelError`
- `XtCreditDetail`
- `StkCompacts`
- `CreditSubjects`
- `CreditSloCode`
- `CreditAssure`
- `XtAccountStatus`
- `XtAccountInfo`
- `XtSmtAppointmentResponse`

## 高频问题跳转

- 没有回调 → `6-FAQ.md`
- 异步下单如何拿订单号 → `6-FAQ.md`
- 同步查询为什么卡住 → `6-FAQ.md`
- `order_id` 和 `order_sysid` 区别 → `6-FAQ.md`
