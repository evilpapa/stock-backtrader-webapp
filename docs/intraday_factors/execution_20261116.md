# 46因子策略：公共持仓与模拟订单执行验证

日期：2026-11-16。实现入口为`examples/intraday_execution.py`，公共模块说明见
[公共持仓与执行](../trading/README.md)。

## 实现范围

保留原46因子信号、历史成分和研究回测，新增独立执行层：目标权重输入、账户和策略
隔离的持久持仓、买卖调仓、资金/股份冻结、部分成交、T+1、委托/成交回调、查询补偿、
撤单及超时防重发。PaperBroker与QMT Adapter共用同一公共持仓和订单引擎。

本机未找到名为`xtquant-big-quant`的技能；实际参考已安装的`xtquant-big-convert`
技能及桥接包0.3.78的接口实现。QMT端禁用下单的配置没有改动，没有实发委托或撤单。

## 历史模拟结果

读取最后一次成功研究回测的`refresh_20261030/backtest/targets.csv`，经DataHub的
ResearchDailyRepository读取不复权日线，回放2022-02-21至2026-11-02的240次目标组合。
这不是重新训练因子，也没有将原研究中的连续复权份额直接当作券商实际股数。

| 指标 | 本次订单执行模拟 | 原研究回测 |
|---|---:|---:|
| 初始资金 | 1,000,000.00元 | 1,000,000.00元 |
| 调仓次数 | 240 | 240 |
| 期末权益 | 1,101,509.30元 | 1,065,077.15元 |
| 累计收益 | 10.15% | 6.51% |
| 年化收益 | 2.08% | 1.35% |
| 最大回撤 | -23.41% | -23.78% |
| 累计佣金 | 81,815.00元 | 89,160.00元 |
| 模拟委托/成交笔数 | 16,363 / 16,363 | 原研究不使用此订单账本 |
| 期末持仓数 | 48 | 48 |
| 期末现金 | 14,232.22元 | 1.86元 |
| 期末未决订单 | 0 | 不适用 |

执行版加入整数股、板块买入数量规则、零股清仓、T+1和涨跌停近似等约束，交易数量、
再平衡小额委托及费用因此发生变化。两者不是相同成交口径，不能把差额解释为策略改进
或实盘收益保证。最新48只股票集合与原研究一致，股数、现金和权重以新的执行输出为准。

最终输出目录：
[execution_verified_20261116](../../examples/intraday_factors/execution_verified_20261116)。

- [metrics.json](../../examples/intraday_factors/execution_verified_20261116/metrics.json)：指标、输入SHA和执行源码SHA。
- [latest_holdings.csv](../../examples/intraday_factors/execution_verified_20261116/latest_holdings.csv)：实际整数股模拟持仓。
- [orders.csv](../../examples/intraday_factors/execution_verified_20261116/orders.csv)、[fills.csv](../../examples/intraday_factors/execution_verified_20261116/fills.csv)：订单和成交账。
- [audit.json](../../examples/intraday_factors/execution_verified_20261116/audit.json)：独立资金、费用、持仓和完整性检查。

## 最后一次调仓的单独模拟

`paper`入口从100万元独立模拟现金出发，只执行2026-11-02的目标组合。结果：
48笔订单、48笔成交、48只持仓，佣金240元，期末权益999,760.00元，现金11,905.36元。
这是单次新建组合的冒烟验证，与完整历史回放的期末资金不同。
结果保存在[execution_paper_20261116](../../examples/intraday_factors/execution_paper_20261116)。

## 已执行的验证

1. 74项离线测试通过，包括33项新交易测试；覆盖成交驱动持仓、重复回报、部分成交
   最低佣金、T+1、策略隔离、跨数据库连接冻结、卖出未完成不买入、撤单等待终态、
   未知订单不重发、错误回报身份、券商拒单、数据接口和短历史端到端回放。
2. SQLite完整性通过；所有模拟订单均全额成交，成交身份无重复，现金历史无负值，
   每笔佣金与项目ChinaStockCommission一致，最大误差0。
3. 以初始现金、逐笔买卖、费用和公司行为代理现金重建期末现金，与账本一致；期末
   股票市值加现金等于期末权益。原研究回测代码和metrics的SHA保持不变。
4. QMT真实只读联通：账户和配置匹配、8只券商原有持仓、0条当日委托；启动监听并查询
   订单/成交，检查期间没有新的成交/订单推送。原持仓没有自动纳入新策略。
5. 经DataHub读取000001.SZ、600000.SH、688425.SH实时行情、价格上下限及交易日历成功；
   48只最新目标股的QMT计划预览成功，明确标记历史目标过期。
6. `watch --seconds 2 --interval 1`命令运行完成，未决委托为0；下单和撤单发送次数均为0。

只读检查和计划预览证据：
[execution_bridge_check_20261116](../../examples/intraday_factors/execution_bridge_check_20261116)。
其中`validation.sqlite`只是本次只读验证用本地钱包，不是生产公共账本。

## 重现

```bash
.venv/bin/python examples/intraday_execution.py backtest \
  --targets examples/intraday_factors/refresh_20261030/backtest/targets.csv \
  --reference-dir data/intraday_factors/refresh_20261030/reference_data \
  --capital 1000000 --output-dir /path/to/new_execution_output

.venv/bin/python examples/intraday_execution.py paper \
  --capital 1000000 --output-dir /path/to/new_paper_output
```

完整下单、计划、监听和公共持仓接入命令见[公共模块文档](../trading/README.md)。
输出目录已有账本时不能重复覆盖，使用新的明确目录。

## 尚未验证和已知限制

- QMT真实下单受理、券商成交、撤单和断线补推未进行实单验证。当前只确认查询、监听
  启动、行情和计划；订单分支通过Fake SDK测试，不宣称已完成实盘投产验收。
- 当前最近信号仍为2026-10-30，执行日期为2026-11-02，不能直接拿来在11月16日下单。
  执行入口拒绝过期信号和非当日计划，不会更改桥接端禁用设置。
- 历史回放假设开盘限价可全额成交，板块涨跌停仅近似；无成交量约束、滑点、冲击、
  印花税和过户费。公司行为是价值守恒代理，不是真实分红送转流水。
- 公共账本按项目佣金估算费用；券商实际费用、税费、公司行为或外部划转不一致会使
  对账停止后续自动执行，需要按券商流水显式处理，不能擅自归属或自动抹平余额差异。
- 所有策略使用同一生产账本文件并分别分配现金；不支持把多个独立账本各自当作拥有
  整个物理账户的现金和持仓。未来策略需扩展资产制度时不能沿用未验证的股票规则。
