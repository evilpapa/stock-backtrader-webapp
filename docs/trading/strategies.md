# 全策略接入公共交易模块

统一入口：`python -m examples.strategy_execution`。策略先产生目标组合，再经同一
`ExecutionEngine → PortfolioLedger → PaperBroker / QmtTradingProvider` 执行。

## 接入清单

| strategy ID | 策略 | 信号适配 |
|---|---|---|
| `ma` | 单均线 | 原策略固定手数买入、退出意图 |
| `macross` | 双均线 | 原策略固定手数买入、退出意图 |
| `etf_momentum` | ETF动量 | 原生目标权重数组 |
| `qb_etf_momentum` | QB ETF动量 | 原生代码/名称权重映射 |
| `leading_rotation` | 龙头轮动 | 原生目标权重映射，排除策略配置的基准 |
| `sector_rotation` | 行业轮动 | 原生目标权重映射，排除策略配置的基准 |
| `small_cap` | 小市值 | 原生选股权重，含回避月份/风控清仓 |
| `mysterious_spiral` | 神秘螺旋 | 原生上月末信号/月首开盘执行日期 |
| `turtle_trading` | 海龟 | 多头入场、加仓、退出意图；必须显式设置 `allow_short=false` |
| `equal_weight` | 等权持有 | 原策略目标订单 |
| `just_buy_hold` | 买入持有 | 原策略首笔建仓意图 |
| `sector_rotation_dual` | 双轮行业ETF | 原正向/反向篮子 × 配置权重，重叠ETF相加 |
| `micro_cap_timing_plus` | 微盘择时增强 | 原始未平移择时仓位 × 显式时点成分股篮子 |
| `free_cash_flow` | 自由现金流 | 原选股函数输出的逐期权重，保留各版本 |
| `free_cash_flow_account` | 自由现金流约束账户 | 原约束/缓冲选股输出的逐期权重，保留各情景 |
| `intraday46` | 46因子中证500 | 已有 `targets.csv`，保持原执行日期 |

`src/strategy` 中的基类、分析器、绩效工具及分钟/集合竞价因子计算、IC/分组收益研究函数
不独立输出可交易组合，不给它们臆造选股或多空规则。现有46因子组合继续接入原目标文件。

```bash
.venv/bin/python -m examples.strategy_execution list
```

## 统一信号格式与日期

`targets.csv`：

```csv
signal_date,trade_date,symbol,target_weight,strategy_id
2026-11-12,2026-11-13,000001.SZ,0.6,ma
2026-11-13,2026-11-16,,0.0,ma
```

空代码且权重为0的一行，明确表示该执行日**清空此策略自己的持仓**；该日没有行表示
不调仓。部分仓位的剩余资金保留现金。单文件只允许一个策略；有 `strategy_id` 时必须与
执行钱包的 `--strategy` 一致，防止将一个策略的信号写入另一个策略的持仓。

`calendar.csv` 必须来自真实交易所日历，至少覆盖信号日及其下一交易日：

```csv
trade_date,is_open
2026-11-12,1
2026-11-13,1
2026-11-14,0
2026-11-15,0
2026-11-16,1
```

也支持仅含 `date` 列的开市日期列表。不会用工作日偏移猜节假日；缺少下一交易日时报错。
信号生成数据应先通过 DataHub 获取，文件输入支持已保存的标准数据，不直接调用供应商SDK。

## Backtrader策略生成目标

创建输入清单 `manifest.json`，文件路径相对于清单所在目录。价格文件为DataHub转换后的
`date,open,high,low,close,volume`，支持CSV和Parquet；也接受DataHub标准的带时区
`datetime`列，经 `to_backtrader_ohlcv()` 转成上海交易日与标准列，保留 `amount` 和DataFrame
来源/复权/版本属性，不再次做单位转换。`prices`的键是原策略数据源名称。

```json
{
  "prices": {"000001.SZ": "000001.csv"},
  "params": {"maperiod": 15}
}
```

```bash
.venv/bin/python -m examples.strategy_execution generate \
  --strategy ma --input manifest.json --calendar calendar.csv \
  --capital 1000000 --stake 100 --output data/trading/ma/targets.csv
```

MA原策略按固定手数交易，`--stake` 控制该手数。其他策略沿用自己的仓位计算和 `params`。
策略模拟按项目 `ChinaStockCommission` 收取手续费。价格文件需包含充分的指标预热历史。

原数据源名是展示名称时，提供显式代码映射，例如：

```json
{
  "prices": {"沪深300ETF": "510300.csv", "中证500ETF": "510500.csv"},
  "symbol_map": {"沪深300ETF": "510300.SH", "中证500ETF": "510500.SH"},
  "params": {"momentum_window": 20, "rebalance_days": 5}
}
```

`symbol_map` 只把明确的展示名称映射到内部代码；证券代码规范化统一经 `TickerMapper`。

小市值清单另需 `universe_snapshots`：`{"2026-10-30": "universe_20261030.csv"}`。
快照须包含 `StockUniverseSnapshot.REQUIRED_COLUMNS` 中的代码、名称、上市日、ST/停牌/
退市状态、流通股本及流通市值，按原策略的快照日期生效；不得用未来股票池替代历史。
可提供 `market_factors` CSV（`date,nhnl,limit_up_count`），并在 `params` 中指定回测起点、
预热和市场门控等原策略参数。股票池状态列使用CSV布尔值 `True/False`。

海龟清单的 `params` 必须包含 `"allow_short": false`。当前公共引擎为无融资的现金多头；
负权重、总权重超过1、未关闭的海龟做空模式会报错，不会偷偷截成零或缩放成另一种策略。

已有回测结果可直接导出，无需重新取数：

```python
strategy.export_execution_targets(
    calendar, "data/trading/ma/targets.csv",
    symbol_map={"展示名称": "000001.SZ"},
)
```

所有11个Backtrader策略继承公共基类，提交订单时记录当时的持仓、计划数量、价格和权益。
优先使用原生权重历史；无权重历史的MA、海龟等按信号时点的计划股数折算权重。清仓意图在
最后一根K线尚未成交时也能导出。模拟拒单不会抹掉当时的交易意图。

普通日线策略按收盘信号映射下一实际交易日；神秘螺旋启用原来的 `cheat_on_open`，保留
`signal_date/execution_date`，开盘上下文使用开盘价，不再平移一次。其开盘风控仍在原开盘
决策阶段运行。导出的目标权重经公共引擎执行后，会受整手、资金、费用和T+1限制，成交结果
可能与原Backtrader回测不同。它们不是从未来成交后的持仓倒推的权重。

## 自由现金流及约束账户

运行原有 `examples.free_cash_flow` 或 `examples.free_cash_flow_account` 后，新增保存：

```text
<原输出目录>/trading/<版本或情景>/native_weights.csv
```

覆盖原FCF加权、增强、等权，以及各持股数、约束和缓冲情景。文件列为 `date,symbol,weight`，
保留未平移的原始调样日期及全现金日期。选择一个版本后生成交易目标：

```bash
.venv/bin/python -m examples.strategy_execution generate \
  --strategy free_cash_flow_account \
  --input 'examples/free_cash_flow/account_industry/trading/25只-约束缓冲/native_weights.csv' \
  --calendar calendar.csv --output data/trading/free_cash_flow_account/targets.csv
```

Python调用方也可直接 `weight_targets("free_cash_flow", 原逐期权重字典, calendar)`。
原FCF研究有收盘调仓口径；公共执行统一使用下一交易日执行，不把研究收益直接当作实盘收益。
同一策略ID同一执行日只能有一套计划，请选择一种版本，避免不同参数版本覆盖同一钱包。

## 双轮行业ETF

清单使用同日期、同列顺序的宽表CSV/Parquet，首列 `date`，其余列为ETF代码：

```json
{
  "open": "open.csv", "close": "close.csv", "shares": "shares.csv",
  "index_heat": "heat.csv", "industry": "industry.csv",
  "params": {"use_dtw": false, "top_n": 6}
}
```

`industry.csv` 为 `symbol,industry`。其他参数沿用 `SectorRotationDualStrategy`；热度缺失时
仍须原参数 `allow_missing_heat=true` 明确允许降级。`symbol_map` 可用于显式名称映射。

```bash
.venv/bin/python -m examples.strategy_execution generate \
  --strategy sector_rotation_dual --input dual_manifest.json \
  --calendar calendar.csv --output data/trading/sector_rotation_dual/targets.csv
```

默认导出原策略历史结果。清单加入 `"latest": true` 则调用原来的 `latest_target()`；
日历必须确认输入末日是该周最后一个交易日，且覆盖次周首个交易日。不会用周中截断数据
假装完整周信号。空子篮子的配置份额保留现金，重叠ETF合并后总仓位不超过1。

## 微盘择时增强

指数是研究序列，不能直接当作股票下单。清单必须提供每个正仓位信号日的可交易成分篮子：

```json
{
  "index": "microcap_ohlc.csv", "factors": "factors.csv",
  "style_gap": "style_gap.csv", "constituents": "constituents.csv",
  "params": {"ma_window": 15}
}
```

- `index`：`date,open,high,low,close`。
- `factors`：`date,flow_breadth,main_net_ratio,diffusion`。
- `style_gap`：`date,style_gap`。以上三表日期必须相同。
- `constituents`：`date,symbol,weight`，必须是各信号日已知的真实成分权重。

调用原 `compute_signals → build_positions`，将未平移仓位乘成分权重，然后只平移至下一
实际交易日一次。缺成分股会报错；不能将回测中已经shift的持仓再次传入当作原信号。

```bash
.venv/bin/python -m examples.strategy_execution generate \
  --strategy micro_cap_timing_plus --input timing_manifest.json \
  --calendar calendar.csv --output data/trading/micro_cap_timing_plus/targets.csv
```

## 所有策略共用的交易命令

```bash
# 回放：执行价格使用该策略证券覆盖的未复权日线Repository
.venv/bin/python -m examples.strategy_execution backtest --strategy ma \
  --targets data/trading/ma/targets.csv --reference-dir data/my_reference \
  --capital 1000000 --output-dir examples/trading/ma/replay_run_1

# 单期本地模拟：使用目标文件最新日期，从独立现金账户开始
.venv/bin/python -m examples.strategy_execution paper --strategy ma \
  --targets data/trading/ma/targets.csv --reference-dir data/my_reference \
  --output-dir examples/trading/ma/paper_run_1

# QMT计划预览：不发送订单
.venv/bin/python -m examples.strategy_execution plan --strategy ma \
  --targets data/trading/ma/targets.csv --ledger data/trading/portfolios.sqlite

# 本地持仓与订单
.venv/bin/python -m examples.strategy_execution status --strategy ma \
  --ledger data/trading/portfolios.sqlite --account YOUR_ACCOUNT
```

`--reference-dir` 使用研究日线仓库格式 `raw/daily/YYYYMMDD.duckdb`，其中 `data` 表包含
`ts_code,trade_date,open,close,pre_close,vol`。各证券代码及调仓日必须有相应价格数据。
全策略入口要求显式传此路径，避免误用46因子缓存。信号计算可以使用复权数据，执行日线
必须使用未复权价格；DataHub回放保留来源和数据版本。

同样支持原入口的 `execute/watch/cancel` 参数和保护。只有显式传 `--enable-orders` 才会
尝试下单/撤单，服务端开关、报价时效、连续竞价时段、账户对账及订单幂等检查仍然生效。
所有策略共享同一物理账户的同一账本，各策略现金预算独立；不会把券商原有持仓自动分配
给策略。接入和离线验证不会自动开启QMT权限或发送真实委托。

原 `examples/intraday_execution.py` 继续保留46因子的默认路径和ID。

## 验证

```bash
.venv/bin/python -m unittest tests.trading_strategies_test \
  tests.trading_targets_test tests.trading_execution_test -q
```

测试仅使用合成行情、Mock Broker与Fake SDK。覆盖全部11个Backtrader具体策略的原生信号
生成和公共模拟交易、注册清单完整性、双轮重叠/最新信号、微盘择时、FCF两个版本的原生
权重文件转换、统一CLI历史回放、清仓、策略隔离、节假日与月初开盘日期、非法空头/杠杆
拒绝。真实账户的受理、成交、撤单验证仍需独立完成。

2026-11-16最终全量离线回归：**230项通过、10项失败**；交易相关三个测试文件的55项
全部通过。适配前已有相同10项失败，未增加失败项：

- `bigqmt_client_test`：旧调用传入当前接口不支持的 `timeout`。
- `duckdb_sync_test`：Tick字段、补下载和板块fallback的3项旧兼容断言。
- `ma_test`、`macross_test`：旧路径 `./config/strategy.yaml` 不存在。
- `processing_metrics_test`：仍尝试顶层 `import strategy`。
- `sector_rotation_test`：旧参数注入访问属性失败。
- `turtle_trading_test`：旧参数属性注入及加仓单元数断言的2项失败。

未将这些失败计为通过；完整命令为 `.venv/bin/python -m pytest tests --ignore=tests/integration -q`。
