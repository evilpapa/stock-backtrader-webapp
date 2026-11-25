# QMT 下单、查单、撤单与原子提交

所有现金多头策略共用 `ExecutionEngine` 和同一个物理账户的
`data/trading/portfolios.sqlite`。权重策略继续调用 `rebalance()`；
直接产生订单意图的策略调用 `submit_order()`，不需要自行拼 QMT 参数。
券商 SDK 只在 `src/datahub/providers/` 内调用。

## 单笔委托接口

```python
state = engine.submit_order(
    client_id="yourDurableIntentId",  # 1..24位ASCII字母或数字；同一意图永久复用
    symbol="510300.SH", side="buy", quantity=100,
    limit_price=limit_price, quote=quotes["510300.SH"], now=now,
)
state = engine.order_status("yourDurableIntentId", refresh=True)
state = engine.cancel("yourDurableIntentId")
```

`quote` 从 `live_quotes(MarketDataService, symbols, now)` 获取，必须为新鲜的
XtQuant 报价。引擎检查账户、策略预算、日期、连续竞价时段、涨跌停价、价格步长、
买入整手、可卖持仓及现有订单。同一策略存在未决委托时，单笔入口拒绝新意图。
已有订单使用相同身份和参数调用时只恢复状态；改动参数将报错。

| 返回字段 | 判定 |
|---|---|
| `accepted` | 已取得真实券商合同编号，且没有明确拒绝；不代表成交 |
| `success` | 全部成交，且逐笔成交流水已入账 |
| `failed` | 已取得明确拒单终态，且没有未入账成交 |
| `settled` | 已到终态，且报告成交量与成交流水已对齐 |
| `outcome=pending` | 已报、部成或撤单处理中，继续查询 |
| `outcome=unknown` | 发送/超时结果不明，保留冻结，禁止自动重发 |
| `outcome=awaiting_trades` | 已收到终态但缺成交明细，继续冻结和查询 |
| `outcome=canceled` | 已撤且无成交，不代表买入成交成功 |
| `outcome=partially_filled_canceled` | 部分成交、剩余已撤；已成交部分继续计入持仓 |
| `cancellation.state` | 本地撤单请求为 sending / acknowledged / unknown |

`success=False` 本身不能作为失败检测；应检查 `failed`、`settled` 和 `outcome`。
明确状态57且带券商合同编号的拒单回报计为 rejected。桥接在多次查不到订单后可能
合成状态57的错误，这不是券商拒单证据；无合同编号或含“order not found in system”
的错误保持 unknown，继续冻结。服务端明确禁用属于发送前拒绝，可直接判定失败。
重复回调、轮询补报和成交早于委托回报都走同一账本去重逻辑。

## 原子性的边界

SQLite `BEGIN IMMEDIATE` 在一个事务中检查资金/可卖股数、验证订单身份并写入
`sending` 意图。事务提交后才调用一次券商接口。并发进程共享同一账本时，只有
成功创建意图的一方可以提交；崩溃发生在本地落盘和券商调用之间时也不自动重发。
权重调仓与单笔入口共用 `_dispatch()`。

本地数据库与券商系统没有分布式事务。这里提供的是本地原子冻结和最多一次自动发送，
不承诺网络层端到端 exactly-once，也不承诺多只证券组成的篮子全部成交或全部回滚。
提交超时只能按 client_id/remark、真实字符串合同编号查询恢复，不能换身份重试。

撤单同样先在 `cancel_requests` 中原子记录，再发送一次请求。同一撤单身份在重启、
重复调用、超时之后不会自动重发。RPC 返回0仅表示请求受理；最终以委托状态53/54
及成交流水为准。撤单结果未知时继续冻结，人工核对后再决定后续操作。
已成交部分不可通过撤单回滚，不会自动反向卖出。

## 510300 一次性生命周期示例

```bash
# 只读预检，绝不提交
.venv/bin/python -m examples.qmt_order_lifecycle

# 用户授权后：510300.SH限价买入100份，查询后撤销未成交部分
.venv/bin/python -m examples.qmt_order_lifecycle --execute --enable-orders
```

示例限价默认取准备时最新价下方20个最小价位，以覆盖挂单及撤单链路；
行情变动仍可能导致成交。发送前重新获取实时报价并通过引擎检查。
数量固定100，方向固定买入，不自动追价、不补单、不反向卖出。
合同编号晚到时只查单恢复；观察期默认30秒，仍不明则保留账本和冻结供后续查询。
同一账户、策略、日期生成固定24位身份，重复运行恢复原订单，不产生新委托。

输出包括 `preflight.json`、`execution.json` 和共享 SQLite 账本。报告遮蔽账号，
保留时间、限价、报价、合同编号、状态观察、策略资金和持仓及最终账户对账。
示例的1000元是独立策略预算，不是重复分配账户全部资产。
命令退出码：0为预检成功或订单已正常结束且账户对账通过，2为明确拒单，
3为仍未决，4为订单结束但账户对账未通过；不能把进程退出当作成交成功。

2026-11-18唯一一次实单提交的结果及未完成环节见
[实单记录](execution_20261118.md)。

## 大 QMT 实时交易状态

大 QMT 内置 Python `get_full_tick` 文档标明 `stockStatus` 已作废，
现金证券应读取 `openInt`；13表示连续交易，1/17/20等表示停牌或暂停。
`XtQuantProvider` 在 `DataFrame.attrs["execution_state"]` 保留每证券的
`security_status/status_field/bid_prices/ask_prices`，避免OHLCV规范化丢失。
存在实时状态时以它判断是否可交易；没有状态时保留原合约字段回退逻辑。
实盘执行不使用行情缓存。该逻辑不适用于将 openInt 解释为持仓量的期货。
