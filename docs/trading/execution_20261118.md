# 2026-11-18 QMT 唯一一次下单记录

本次只发送一次510300.SH买入100份的委托请求，没有补单或改价重发。
**未取得券商受理证据，真实撤单未执行，最终状态保留 unknown。**

## 请求与检查

| 项目 | 记录 |
|---|---|
| 时间 | 2026-11-18 11:27:09开始执行，北京时间 |
| 账户 | 尾号6423，STOCK |
| 策略 | qmt_lifecycle_demo |
| client_id / remark | 0fa672de5d94589043254435 |
| 证券、方向、数量 | 510300.SH，买入，100份 |
| 准备时/发送前最新价 | 4.038元 |
| 限价 | 4.018元，下方20个0.001元价位 |
| 名义金额上限 | 401.80元 |
| 本地策略预算 | 1000元 |
| 模型冻结 | 406.80元，含5元预估费用 |
| 客户端/服务端 | 既有xtquant-big-convert环境；服务端0.3.78 |
| 服务端开关 | allow_order_methods=true |

发送前验证了实时行情、交易日历、连续交易状态、价格步长和涨跌停范围，
账户现金充足且无当日委托，监听和订单/成交查询已启动。
真实账户原有510300持仓10000份不归本示例策略所有，未自动导入或卖出。

## 实际返回

1. 委托RPC返回时没有真实合同编号，适配器记为 unknown，没有自动重发。
2. 桥接在253次扩展查找后发出状态57的错误，信息为
   `passorder submitted but order not found in system`。
3. 首次代码曾把该回调视为 rejected。经核对，这是桥接“查不到订单”生成的诊断，
   不能证明券商拒绝。现已修正适配器和引擎，追加回归测试，并将本次账本恢复 unknown、
   保留冻结；保留原始报告和状态修正审计事件。
4. 11:29:51再查询，账户委托仍为0，成交未查到，合同编号仍为空。
   真实现金1565449.71元，券商冻结0元，510300持仓仍为10000份、可卖10000份。
5. 因无真实合同编号，没有盲目发撤单请求。撤单回报链路由离线测试覆盖，
   本次未取得真实撤单成功证据。

服务端诊断提到“模型交易运行模式为模拟”“终端在创建委托前拒绝”
“ORDER行或回调延迟”等可能原因，当前RPC诊断没有暴露足以确定运行模式的证据，
不能将任何一个原因当作已确认根因。需要在QMT端核对模型交易的运行模式、委托界面、
弹窗及 `D:\gjzq_qmt_new` 下运行日志；本次没有改动QMT配置或重启服务。

## 策略接口与原子性

`ExecutionEngine.submit_order/order_status/cancel` 为公共入口；权重策略的
`rebalance()`共用同一个 `_dispatch()`。资金、持仓和订单按账户及策略隔离，
本地原子落盘在券商调用之前完成。已有身份不会重发，改参数复用身份直接拒绝。
撤单请求也先落盘防重，等待最终回报后才释放未成交部分。

本地事务不构成券商分布式事务，也不保证多证券篮子全部成交或回滚。
本次 unknown 意图仍阻止本示例策略的新委托，不能将其手动改为失败后重新发送。

## 文件与验证

- `examples/trading/qmt_lifecycle_20261118/preflight.json`：只读预检。
- `examples/trading/qmt_lifecycle_20261118/execution_initial.json`：保留首次原始报告，
  其中 rejected 判定已由后续状态修正取代，不能用它作为释放冻结依据。
- `examples/trading/qmt_lifecycle_20261118/execution.json`：含状态修正的最终报告。
- `examples/trading/qmt_lifecycle_20261118/recovery.json`：11:29:51再次查询结果。
- `data/trading/portfolios.sqlite`：唯一订单、原始事件及修正审计记录。

测试使用Fake SDK/Mock Broker，无真实交易。覆盖策略信号接入、共享账本、
身份冲突、重复提交、超时、拒单、合成错误、撤单防重、终态先到/成交后到、
交易状态字段及示例重复运行恢复。真实成交与真实撤单仍未验收。

最终92项测试通过，`git diff --check`通过；本地只读审计确认1条订单、
0条撤单请求，订单为unknown，冻结仍保留。测试命令：

```bash
.venv/bin/python -m unittest tests.trading_lifecycle_test tests.trading_execution_test \
  tests.trading_strategies_test tests.trading_targets_test tests.datahub_test tests.qmt_paper_test -q
```
