# xtquant.xttrader FAQ

来源：[XtQuant.Xttrade 交易模块](https://dict.thinktrader.net/nativeApi/xttrader.html?id=olYCD5)

## 为什么没有回调？

### 先检查这几个前置条件

- 是否已经创建并注册回调类：`register_callback(callback)`
- 是否已经调用 `start()`
- 是否已经调用 `connect()`，且返回值为 `0`
- 是否已经调用 `subscribe(account)`，且返回值为 `0`
- 进程是否仍在运行，例如是否进入了 `run_forever()` 或自行维持事件循环

### 回调排查中的常见误区

- 只 `connect()` 不 `subscribe(account)`，通常拿不到账号相关主推。
- 只实现了回调类，但没有 `register_callback(callback)`。
- 程序下单后立刻退出，来不及接收主推。
- 使用了错误的账户对象，导致订阅的不是实际目标账号。

### 最小排查顺序

1. 看 `connect()` 是否返回 `0`
2. 看 `subscribe(account)` 是否返回 `0`
3. 确认 callback 已注册
4. 确认程序没有提前退出
5. 再检查是否真的发生了会触发回调的事件

## 异步下单如何拿订单号？

### 关键区别

- `order_stock_async(...)` 的直接返回值不是订单号，而是请求序号 `seq`。
- 真正的订单号会在异步回报里出现，对应回调是：`on_order_stock_async_response(data)`。
- 回调参数对象类型是 `XtOrderResponse`，其中包含：
  - `account_id`
  - `order_id`
  - `strategy_name`
  - `order_remark`
  - `seq`

### 实用对应关系

- 调用时先保存 `seq`
- 在 `on_order_stock_async_response` 中，用回报里的 `seq` 对应回原始请求
- 再从回报对象中取 `order_id`

### 最小示例

```python
pending = {}


class MyCallback(XtQuantTraderCallback):
    def on_order_stock_async_response(self, response):
        print('seq=', response.seq, 'order_id=', response.order_id)
        pending[response.seq] = response.order_id


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
print('request seq =', seq)
```

### 如果一直拿不到订单号

- 先确认异步接口是否成功返回了大于 `0` 的 `seq`
- 再确认是否收到了 `on_order_stock_async_response`
- 如果没有回调，回到“为什么没有回调”这节继续排查

## 同步查询为什么卡住？

### 高概率原因

- 在 `on_stock_order`、`on_stock_trade` 等推送回调内部，直接调用了同步查询接口。

文档明确提到，主动请求接口的返回和推送默认存在时序约束；在推送回调里同步等待查询结果时，可能出现阻塞。

### 官方文档给出的处理方向

- 优先改用异步版本查询接口，如果对应接口可用。
- 或者避免在推送回调里立刻做重同步查询。
- 必要时可以调用：`set_relaxed_response_order_enabled(True)`

### 但要知道它的代价

- 开启宽松时序后，查询返回和推送消息的先后关系不再严格一致。
- 也就是说，查询结果可能反映的是比当前正在处理的推送“更晚”的状态。

### 实战建议

1. 能不在回调里做同步查询，就不要做
2. 能用异步接口就优先用异步接口
3. 只有确实需要时，再考虑 `set_relaxed_response_order_enabled(True)`
4. 开启后要接受时序变宽松的事实，策略逻辑要能容忍这种不严格顺序

## `order_id` 和 `order_sysid` 有什么区别？

### `order_id`

- 接口侧订单编号
- 常见来源：
  - `order_stock(...)` 的同步返回值
  - `XtOrderResponse.order_id`
  - `XtOrder.order_id`

### `order_sysid`

- 柜台合同编号
- 常见来源：
  - `XtOrder.order_sysid`
  - `XtTrade.order_sysid`
  - 柜台回报相关对象

### 撤单时怎么选

- 如果你手里拿的是接口返回的订单编号，用：`cancel_order_stock(account, order_id)`
- 如果你手里拿的是柜台合同编号，用：`cancel_order_stock_sysid(account, market, order_sysid)`
- 异步撤单同理：
  - `cancel_order_stock_async(account, order_id)`
  - `cancel_order_stock_sysid_async(account, market, order_sysid)`

### 信用与约券场景中的常见误区

- 把 `order_id` 当成 `order_sysid` 去调按柜台合同编号撤单接口
- 已经只有 `order_sysid`，却还去调按 `order_id` 的撤单接口
- 不传 `market` 就想用 `order_sysid` 撤单

## 为什么异步下单返回了 `seq`，但后来又报下单失败？

- `seq` 只表示异步请求已经成功发出。
- 这不等于柜台最终接受、报单成功或成交成功。
- 如果下单失败，文档说明会通过 `on_order_error(data)` 推送失败信息。
- 所以异步链路里要同时处理：
  - `on_order_stock_async_response`
  - `on_order_error`

## 为什么撤单失败了？

### 先看是哪一种失败

- 接口直接返回 `-1`
- 或者异步撤单后收到 `on_cancel_error(data)`

### 常见原因

- 撤单标识用错：`order_id` / `order_sysid` 混用
- 订单已经成交完成或已经撤完
- 订单本身不可撤
- `market` 与 `order_sysid` 不匹配

### 排查建议

1. 先确认你持有的是 `order_id` 还是 `order_sysid`
2. 再看订单当前状态，必要时查询 `query_stock_orders(account, cancelable_only=True)`
3. 如果有 `on_cancel_error`，直接看 `error_id` 和 `error_msg`

## 为什么只查一次 `query_*` 看不到后续变化？

- `query_*` 只是一次性的主动查询快照。
- 它不会持续推送后续状态变化。
- 如果你要持续跟踪委托、成交、账号状态，需要：
  - 注册 callback
  - `subscribe(account)`
  - 保持进程持续运行

## 为什么信用或约券接口拿不到数据？

### 先检查账户类型

- 信用业务通常要使用：`StockAccount('账号', 'CREDIT')`
- 期货持仓统计通常要使用：`StockAccount('账号', 'FUTURE')`

### 常见误区

- 用普通股票账户对象去调用信用查询接口
- 账户类型正确，但没有对应柜台权限或业务权限

## FAQ 路由

- 回调收不到 → 本页“为什么没有回调？”
- 异步下单拿订单号 → 本页“异步下单如何拿订单号？”
- 回调里同步查询卡住 → 本页“同步查询为什么卡住？”
- 撤单标识区分 → 本页“`order_id` 和 `order_sysid` 有什么区别？”
