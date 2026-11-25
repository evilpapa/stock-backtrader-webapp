# 公共持仓、回测与QMT订单执行

本模块把策略的“目标权重”转换成订单。信号生成、公共持仓账本、券商执行分别独立。
单笔限价委托、成功/失败检测、撤单防重和原子提交边界见
[订单生命周期](order_lifecycle.md)，包含510300买入100份的QMT示例。
已接入11个Backtrader具体策略、双轮行业ETF、微盘择时增强、自由现金流及约束账户，
并保留46因子中证500策略，共16个策略入口。统一命令、清单、输入格式与限制见
[全策略接入说明](strategies.md)。海龟仅支持显式关闭做空后的现金多头模式。
没有修改QMT服务端配置，也没有启用或绕过服务端下单开关。

## 模块与数据流

```text
策略输出 targets.csv / {证券代码: 目标权重}
                   ↓
ExecutionEngine：目标股数、先卖后买、报价检查、订单身份
                   ↓
PortfolioLedger：账户＋策略的资金、持仓、冻结、订单、成交
                   ↓
Broker协议 ── PaperBroker / QmtTradingProvider
                   ↑
        回调事件队列＋委托/成交轮询补偿
```

| 文件 | 职责 |
|---|---|
| `src/trading/models.py` | 与券商无关的报价、委托、成交事件、Broker协议 |
| `src/trading/portfolio.py` | SQLite持久账本，按账户和策略隔离；成交驱动持仓更新 |
| `src/trading/execution.py` | 权重调仓、资金/可卖数量冻结、生命周期、撤单、断点恢复 |
| `src/trading/paper.py` | 确定性本地限价成交，回调和轮询重复送达也只记一次账 |
| `src/trading/market.py` | 经MarketDataService读取执行报价、交易日历、合约涨跌停价 |
| `src/trading/replay.py` | 保存的历史目标权重经同一引擎、同一账本回放 |
| `src/trading/targets.py` | 统一目标格式、显式空仓、策略身份和日期/权重校验 |
| `src/trading/strategies.py` | 16个策略注册、原生权重/订单意图适配和信号生成 |
| `examples/strategy_execution.py` | 全策略list/generate及公共交易CLI |
| `src/datahub/providers/qmt_trading.py` | 唯一新增券商SDK调用边界；下单、撤单、账户、监听、轮询 |
| `src/datahub/config/trading.yaml` | 执行行情仅用XtQuant，关闭行情缓存，避免研究路由影响交易 |
| `examples/intraday_execution.py` | backtest/paper/plan/execute/watch/status/cancel统一CLI |
| `tests/trading_execution_test.py` | Mock Broker、Fake SDK和合成日线验证，不依赖真实账户 |

使用当前环境已有的Python、pandas、SQLite、ChinaStockCommission及
`xtquant-big-convert>=0.3.78`，没有新增第三方依赖。`src.trading`已加入安装包列表。

## 公共持仓模块约定

- 所有策略共享**同一个物理账户对应的同一账本文件**。钱包主键为`account + strategy`，
  持仓主键增加证券代码；同一股票可被多个策略分别持有。
- 账本保存现金、成本、整数持仓、T+1可卖数量、委托冻结和成交流水。券商总持仓仅用于
  对账，不会自动分配给某个策略；手动持仓也不会被新策略自动卖出。
- `create_portfolio`分配的是该策略独立现金预算，不是重复分配整个账户总资产。
  执行前校验各策略现金合计及可卖数量不超过券商实际可用范围。
- 委托受理不增加持仓；只有成交回报增加/减少持仓。买入当天不可卖，下一交易日滚动
  释放；挂单冻结资金或可卖股数。全部成交、撤单完成或拒单后才按实际结果释放。
- 成交按账户、交易日、证券代码、成交编号去重；冲突载荷报错。每笔委托的分笔成交累计
  计算项目佣金，最低5元只收一次，不按每条成交回报重复收费。
- SQLite WAL及`BEGIN IMMEDIATE`使冻结、资金、成交和持仓同事务提交；实盘账本保留FULL
  同步。历史回放单独使用NORMAL同步提高速度，历史账本可重建，不能拿它替代实盘账本。
- 一个策略同一执行日只允许一套持久调仓计划；订单remark为24位确定性client_id，
  提交前先落盘。重启后已有订单不会重发；超时保留为unknown并继续冻结，先查询对账。
- 撤单RPC成功只表示请求受理；等待订单状态/成交回报确认最终撤单数量。终态订单的成交
  可能尚未到达，此时继续保留相关资金/股份冻结，不能提前当作可用。
- `seed_position()`是显式导入既有持仓的接口，调用者必须确认策略归属、真实股数、可卖
  股数和成本。它不从现金扣除历史买入金额，初始化现金应填当前分配现金。

新策略接入示例：

```python
from src.trading import PortfolioLedger, ExecutionEngine
from src.trading.market import live_quotes
from src.datahub.bootstrap import create_service
from src.datahub.providers.qmt_trading import QmtTradingProvider

# account_id来自现有桥接配置。每个引擎使用自己的Broker实例，共享账本。
ledger = PortfolioLedger("data/trading/portfolios.sqlite")
broker = QmtTradingProvider(enable_orders=False)
ledger.create_portfolio(broker.account_id, "another_strategy", 200_000, trade_date)
engine = ExecutionEngine(ledger, broker, "another_strategy")
service = create_service(config_path="src/datahub/config/trading.yaml")
try:
    symbols = set(weights) | set(ledger.positions(broker.account_id, "another_strategy"))
    quotes = live_quotes(service, symbols, now)
    # 默认客户端开关关闭，实际下发将明确拒绝；不修改服务端权限。
    result = engine.rebalance(weights, quotes, signal_date=signal_date,
                              trade_date=trade_date, now=now)
finally:
    engine.close()
    service.close()
    ledger.close()
```

`now`须是带时区的datetime，`weights`例如`{"000001.SZ": 0.5, "600000.SH": 0.5}`。
实盘行情必须使用当日新鲜报价；历史模拟使用PaperBroker，不通过QMT下发。

## 当前策略的运行命令

在项目根目录执行。原46因子因子生成和研究回测入口保持原样，详见
[刷新报告](../intraday_factors/refresh_20261030.md)。这里只读取其`targets.csv`，
不重新拟合或改变历史选股规则，也不把旧`adjusted_shares`当作真实券商股数。

### 1. 完整历史回放

```bash
.venv/bin/python examples/intraday_execution.py backtest \
  --targets examples/intraday_factors/refresh_20261030/backtest/targets.csv \
  --reference-dir data/intraday_factors/refresh_20261030/reference_data \
  --capital 1000000 \
  --output-dir examples/intraday_factors/execution_verified_20261116
```

输出：`portfolio.sqlite`、`nav.csv`、`orders.csv`、`fills.csv`、`latest_holdings.csv`、
`rebalances.csv`、`corporate_action_proxies.csv`、`data_versions.json`和`metrics.json`。
现有目录已有账本时拒绝覆盖，请指定新的输出目录。可加`--start`、`--end`缩短区间。

### 2. 最后一次调仓的本地模拟下单

```bash
.venv/bin/python examples/intraday_execution.py paper \
  --capital 1000000 \
  --output-dir examples/intraday_factors/execution_paper_20261116
```

只回放输入中最新执行日，从独立模拟现金账户开始，通过PaperBroker产生订单和成交，
不调用QMT下单接口。主板默认100股起/100股增量，科创板200股起/1股增量，北交所默认
100股起/1股增量；清仓支持剩余零股。其他资产交易制度需要配置/扩展，不宣称全品种覆盖。

### 3. QMT实时行情计划预览

```bash
.venv/bin/python examples/intraday_execution.py plan \
  --targets examples/intraday_factors/refresh_20261030/backtest/latest_selection.csv \
  --ledger data/trading/portfolios.sqlite --strategy intraday46 --capital 1000000 \
  --output-dir examples/intraday_factors/qmt_plan
```

这会查询账户、订阅事件、取当日实时行情和合约资料，计算计划股数并输出`qmt_plan.json`，
不冻结交易资金、不创建待发订单、不下单。初始化策略钱包是本地账本动作，原券商持仓
不会自动导入。`stale_target`标记执行日是否过期，预览不等于通过执行检查。

### 4. 下单与持续推进卖出后买入

只有在生成**当日执行的有效新信号**且用户自行配置好QMT服务端之后，才运行：

```bash
.venv/bin/python examples/intraday_execution.py execute \
  --targets /path/to/current_targets.csv \
  --ledger data/trading/portfolios.sqlite --strategy intraday46 --capital 1000000 \
  --enable-orders --seconds 60 --interval 2 \
  --output-dir examples/intraday_factors/qmt_execution
```

客户端不传`--enable-orders`直接拒绝执行；即使传入，服务端禁用时仍保持禁用。
客户端不会更改服务端配置。最近已保存信号为2026-10-30、执行日2026-11-02，不能拿它
在2026-11-16下单。发送前还检查执行日、信号年龄（7自然日内）、交易日历、连续竞价
时段、报价时效（30秒）、涨跌停价、券商账户和公共账本对账。

只有当前批次卖出全部成交后才发送买单；部分成交时继续监听，不能假设卖出资金已到账。
时间到后保留未完成订单和冻结，后续用同一参数再次execute继续，已有订单不重发。
unknown/sending状态禁止进一步自动提交，需先通过监听/查询恢复确定状态。
拒单、部分撤单不会自动用新身份重试。

`completed_with_deviation`表示订单均已处理但因资金、整手或交易限制未完全达到目标股数；
`quantity_deviations`列出差额，不能把“订单处理完”解释为“目标组合完全成交”。

### 5. 监听、持仓与撤单

```bash
.venv/bin/python examples/intraday_execution.py watch \
  --ledger data/trading/portfolios.sqlite --strategy intraday46 --seconds 60 --interval 2

.venv/bin/python examples/intraday_execution.py status \
  --ledger data/trading/portfolios.sqlite --account YOUR_ACCOUNT --strategy intraday46

.venv/bin/python examples/intraday_execution.py cancel \
  --ledger data/trading/portfolios.sqlite --strategy intraday46 \
  --client-id OWNED_CLIENT_ID --enable-orders
```

watch持续接收回调并轮询修复漏推，只更新账本、不自动发新单。execute带seconds参数才
会继续推进同一调仓计划。status读取本地策略账本，若需最新状态先运行watch。撤单只允许
该账户和该策略自己的订单，不能操作其他策略或手工委托。

## 已验证与限制

离线测试命令：

```bash
.venv/bin/python -m unittest tests.trading_execution_test tests.datahub_test tests.qmt_paper_test \
  tests.intraday_factors_fast_test tests.auction_tick_repository_test \
  tests.intraday_all_factor_backtest_test tests.intraday_factors_test \
  tests.intraday_factor_research_test tests.auction_factors_test tests.local_minute_repository_test
```

2026-11-16：74项通过，包含33项新交易测试。QMT只读检查成功，监听已启动且账户查询
匹配，检查期间没有新订单/成交推送；没有发送下单或撤单。3只样本的实时报价、交易日历、
涨跌停元数据读取通过；48只目标股的计划预览成功。桥接0.3.78的合约详情只接受一个证券
参数，不能套用官方SDK的第二个完整信息参数。

适配器保留真实字符串合同编号（包括前导零），不把RPC受理当作成交；查询显式使用
`strategy_name=""`覆盖账户全部委托/成交，再按持久身份归属策略。回调频道不硬编码，
由当前安装包的`register_callback/start/subscribe`管理，避免照搬旧技能文档的频道名。

2026-11-18发送过唯一一次510300买入100份的请求，但未获得合同编号，最终保留unknown；
真实券商受理、成交、撤单和断线补推仍未验收，详情见[实单记录](execution_20261118.md)。
相关分支由Fake SDK和Mock Broker验证。历史策略回放及独立对账见
[2026-11-16执行验证](../intraday_factors/execution_20261116.md)。

历史回放仍是研究近似：日线开盘成交/估值，假设限价可一次全额成交；涨跌停按板块和
参考前收近似，不是历史官方涨跌停；无成交量约束、滑点、市场冲击、印花税和过户费。
公司行为按昨收/今前收近似折算整数股和模拟现金，不是真实分红送转流水。结果会与原连续
股数回测不同，不能直接把原收益当作此执行版本的收益。

公共账本当前按项目佣金估算费用。真实账户费率、税费、分红、划转、送转与模型不一致时
会造成对账差异，程序停止自动执行，需基于券商流水显式校正后再继续；不自动将账户余额
差额平摊给策略。当前不含交易所回报完整性认证、实盘税费清算、自动公司行为归属或7×24
进程托管，不能把只读联通和模拟通过视为实盘投产验收。
