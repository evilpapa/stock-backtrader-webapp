# 日内价量选股因子复现：会话交接

整理日期：2026-11-15（Asia/Shanghai）。最后一次完整刷新完成于2026-11-13。
本文件依据可访问对话、当前源码、产物及审计记录整理；11月15日整理交接时未改业务代码或续拉行情。
11月16日新增公共持仓与订单执行，见文末补充和执行验证报告。

当前保留的数据版本截至 2026 年 11 月 24 日。日常竞价源为
`/data3/stock_data/stk_open_auction/YYYYMM/YYYYMMDD.csv`。最新完整周信号为 11 月 20 日，
原定 11 月 23 日执行，共 47 只。11 月 25 日另用券商模拟账户执行该篮子。
见[回测指标](../../examples/intraday_factors/refresh_20261124/backtest/metrics.json)、
[选股名单](../../examples/intraday_factors/refresh_20261124/backtest/latest_selection.csv)和
[券商模拟执行记录](../../examples/intraday_factors/refresh_20261124/qmt_simulation_20261125/execution.json)。
下文为历史研究记录。归档的旧刷新目录需要恢复后才能打开对应明细或执行旧命令。

## 1. 最终目标与完成状态

最初需求是用日内高频数据复现选股研究，并逐步扩展股票池和历史区间。最终研究对象为广发多因子系列41《高频价量数据的因子化方法》，建立了**39个分钟因子、7个竞价因子、动态中证500近似股票池、周度IC研究及46因子组合回测**。这里的高频指输入频率，策略按周调仓。

当前任务已完成：将成分快照、竞价和分钟因子统一补至2026-10-30，按既定组合规则回测至2026-11-02开盘，并导出最近调仓名单。它是基于研报因子的研究组合，**不能表述为研报指定组合的严格复现**，也不是最初背景介绍中的5分钟对数收益偏度单因子策略。

最先查看：

- [本次结果报告及完整48只名单](refresh_20261030.md)。
- [策略口径与早期验证说明](README.md)、[竞价原始数据整理说明](auction_tick_data.md)。
- [机器审计结果](../../examples/intraday_factors/refresh_20261030/audit.json)、[回测指标](../../examples/intraday_factors/refresh_20261030/backtest/metrics.json)。

## 2. 最终数据与架构

```text
本地年度/日度1分钟Parquet → LocalMinuteRepository ┐
本地竞价日分区Parquet    → AuctionTickRepository ├→ MarketDataService → 日因子
本地日线/ST/上市资料     → ResearchDailyRepository┘
Tushare经DataHub补成分权重、日历和必要参考日线
  → 同日资格与未来收益表 → 46因子周度IC → 历史IC定向组合 → 净值/调仓/审计
```

业务取行情经DataHub请求和Repository；不在策略、示例中直接调用第三方行情SDK。最终历史回测不依赖在线QMT桥接；Tushare分钟下载保持停用。

| 数据/产物 | 最终位置与事实 |
|---|---|
| 分钟原始数据 | `data/tick_1m_parquet`是指向`/data3/stock_data/tick_1m_parquet`的符号链接；2020–2025为`year=YYYY/YYYY.parquet`，2026为`year=2026/month=MM/day=DD/YYYYMMDD.parquet`；本次核对最新原始日为2026-11-06 |
| 分钟字段 | `ts_code, trade_time, open, high, low, close, vol, amount`；Repository按日、证券过滤，映射为标准分钟字段并记录源文件SHA-256 |
| 竞价原始与整理数据 | `data/tick_auction/`年月RAR → `data/tick_auction_parquet/YYYY/MM/YYYYMMDD.parquet`及同名JSON；当前目录清单为2020-01-02至2026-10-30，共1653个交易日、82个月，日历缺日/多日均为空 |
| 竞价字段 | 保留19列；`md_time=91500000`代表09:15:00.000；`min/max`是价格上下限，**不是阶段价格极值**；数量列允许float64，不擅自取整 |
| 成分快照 | `data/intraday_factors/refresh_20261030/csi500/snapshots.parquet`；2020-12-31至2026-10-30，71期、每期500只、并集968只、无缺失月份 |
| 刷新因子 | `data/intraday_factors/refresh_20261030/minute/`与`auction/daily/`；均为2021-01-04至2026-10-30的1410个交易日，每日Parquet和JSON元信息 |
| 参考行情 | `data/intraday_factors/refresh_20261030/reference_data/`；`raw`及`stock_basic.parquet`链接共享旧研究缓存，指数行情为本次独立文件；新增2026-11-02日线并补齐基准至该日 |
| 资格与IC | `examples/intraday_factors/refresh_20261030/auction_history/coverage.parquet`、`universe_snapshots.csv`；`factor_research/weekly_research.csv`含46因子、292个不同信号日、13426条周度记录 |
| 回测与名单 | `examples/intraday_factors/refresh_20261030/backtest/`；`nav.csv`、`trades.csv`、`targets.csv`、`scores.parquet`、`directions.csv`、`training_windows.csv`、`latest_selection.csv`、`latest_holdings.csv`、`metrics.json`、`nav.png` |

**日期边界：**共同因子截止2026-10-30受竞价数据限制；2026-11-02仅为下一交易日执行/估值日。当前名单不能称为2026-11-15的实时信号。因原规则滞后31个自然日，10月30日实际采用**8月31日快照**；9月30日快照到10月31日才可用。

## 3. 已确认有效的计算与回测规则

### 3.1 分钟与竞价因子

- 分钟先用`normalize_bars()`保留09:31–11:30、13:01–15:00，要求整分、无重复且完整240条，剔除全日零成交量；不填缺失分钟，保留15:00收盘竞价分钟。
- 39因子以相邻**1分钟简单收益率**`close[t]/close[t-1]-1`计算，不跨日；样本方差`ddof=1`。尾盘14:31–15:00，收益基准14:30收盘；大成交量取最高1/3分钟，成交量平局按时间顺序，收益仍取原相邻分钟。
- `daily_factors()`为原始逐股实现；`daily_factors_fast()`为批量矩阵实现，只接受已规范的完整240分钟。加速版保持公式、样本方差、平局顺序和lag/lead边界。
- 竞价阶段为`[09:15,09:20)`和`[09:20,09:25)`；每阶段至少2条有效快照。有效价要求有限正数、`last≈bid1≈ask1`且在有效上下限内；09:25–09:30的`open`及全天正数`pre_close`分别需唯一。
- 7因子为`ret_open2AH1/AL1/AH2/AL2`、`diverge_A1/A2`和`ret_overnight`；分别使用开盘/阶段高低价减1、阶段振幅/参考前收、开盘/参考前收减1。**振幅分母是实现假设**，快照不保证捕捉全部极值。

### 3.2 股票池、IC与组合

1. 用Tushare `index_weight`月度权重快照，按快照日期加31个自然日，选信号日最近可用快照。`observed_changes.parquet`只记录相邻快照观察到的增删，不能当作精确进出日期。
2. 剔除ST、上市不足一年、已退市、信号日无成交，以及竞价开盘/参考前收与日线不符的证券；匹配容差为绝对价差`<0.0051`元。
3. 按证券×交易日历网格重建面板，46因子均取连续5个交易日均值；缺失日会打断窗口。组合只接受46个MA5全部有限的合格证券，完整候选少于20只则不生成组合。
4. 单因子周度IC收益为T+1至T+6开盘的近似公司行为调整收益；**先按信号日数据分组，再处理缺失未来收益**，不借未来价格可用性预选股票。
5. 方向仅用`exit_date <= signal_date`的最近52条非空周度秩IC；均值非负取+1，否则−1，任一因子不足52条则不生成组合。截面百分位排名乘方向后对46因子等权平均，按得分降序稳定排序，买入`ceil(完整候选数×10%)`。
6. 每周最后交易日收盘信号、下一交易日开盘等权调仓；初始100万元。缺执行价不能买卖，已持仓沿用上次估值；未成交目标保留现金，不自动清算长期缺价股票。

本次补入2026年已完成持有期的IC，恢复52个已完成周的滚动窗口。旧版因IC输入未更新，2026年沿用了较早历史；**不能把旧版冻结历史描述为本次仍在沿用的规则**。

### 3.3 成交、公司行为与费用

用不复权日线开盘代理成交价，以“上个可用收盘/当前参考前收”累乘构造调整开盘价格，近似公司行为再投资。连续股数，无100股整手限制，先卖后按排名买入，费用和现金约束可能造成实际权重偏离目标。

佣金沿用`src/utils/commission.py::ChinaStockCommission`：双向成交额×0.0000854，每笔至少5元。基准为中证500开盘价格净值；相对净值=`策略净值/基准净值`，其年化不等于两个年化简单相减。

## 4. 关键决策与可复用经验

| 决策 | 原因及边界 |
|---|---|
| 历史分钟以本地Parquet为主 | 用户已准备长历史；所用普通/券商QMT历史覆盖不足（用户在本会话确认），不应继续依赖它补齐2021–2025或重启Tushare分钟下载 |
| 真实竞价快照独立接入 | 常规1分钟线无法还原09:15–09:25报价路径；不能由分钟OHLC伪造阶段高低价或有效观察数量 |
| 按共同截止日而非最长单一数据截止日回测 | 避免新分钟因子配旧竞价/股票池；另外保留下一执行日参考价 |
| 月度权重延迟使用 | 沿用现有可复现股票池，减少直接使用当期快照的时点问题；31天延迟并非已核实发布时间，仍是近似 |
| 独立刷新目录，验证后复用历史 | 原股票并集930只，新增38只最早2026-07-31才进入滞后股票池；原因子截至2月27日，此前无需为尚不合格的新股票补算因子；3月起按968只并集计算 |
| 旧日文件硬链接，新元信息保留父来源 | 避免重复计算与占空间；这是共享同一文件内容，不是独立备份，禁止原地改写链接文件 |
| 竞价仅合并全字段完全相同的行 | 9月21–24日出现重复快照，不能算作两次独立观察；同证券同时间戳的不同报价仍拒绝，原始分区不改 |
| 保留严格版本校验 | Schema v2绑定股票集合、快照、刷新脚本、因子实现和输出SHA；分钟另绑定Repository和加速实现；不要为复用过期缓存修改元信息绕过校验 |

竞价去重策略为`dedup_exact_rows_v1`，发生清洗时改变`data_version`，并记录`duplicates_removed`。本次968只并集读取范围内，2026-09-21/22/23/24分别移除89012/94468/89578/87665条完全重复行，见[清洗审计](../../examples/intraday_factors/refresh_20261030/duplicate_cleanup.csv)。

## 5. 最终文件变更与依赖

下面是最后刷新阶段可由当前工作树确认的增改；不能据此反推所有早期文件的创建时间或作者。

| 文件 | 最终改动 |
|---|---|
| `scripts/prepare_intraday_refresh.py`（新增） | 合并新旧成分快照，校验每期500只和月份覆盖；准备交易日历、参考数据链接、独立指数日线及输入manifest |
| `scripts/refresh_intraday_factors.py`（新增） | 校验复用旧因子、补算新分钟/竞价因子、真实子集公式比对，保存Schema v2日元信息和因子覆盖 |
| `scripts/audit_intraday_refresh.py`（新增） | 检查产物、清洗版本、IC时点和52条窗口、最新名单分数、佣金/资金对账及旧版净值重叠区间 |
| `src/strategy/intraday_factors_fast.py`（新增） | 与原39因子对应的矩阵计算 |
| `src/strategy/intraday_artifacts.py`（新增） | `sha()`与`load_factors()`统一读取、主键/日期/股票范围及版本校验，兼容旧缓存和Schema v2 |
| `src/datahub/auction_tick_repository.py`（修改） | 增加全字段精确去重、冲突拒绝、清洗元信息与条件版本变更 |
| `examples/auction_history_research.py`（修改） | 使用统一因子读取校验；构建资格与近似收益表 |
| `examples/local_minute_factor_research.py`（修改） | 使用统一校验；增加快照和参考目录参数，输出更新后的46因子IC |
| `examples/intraday_all_factor_backtest.py`（修改） | 输入/输出路径参数化，允许延长终点；日线经DataHub读取；增加IC时间校验、训练窗口审计、最新模拟持仓、资金对账及来源记录 |
| `tests/intraday_factors_fast_test.py`（新增） | 合成行情验证加速版等价、平局/常量/零量/无效价格和缺失分钟 |
| `tests/auction_tick_repository_test.py`（修改） | 覆盖精确去重和冲突报价拒绝 |
| `docs/datahub/README.md`、`docs/intraday_factors/README.md`（修改） | 补充去重契约和最新报告入口 |
| `docs/intraday_factors/refresh_20261030.md`（新增） | 本次完整结果、名单、验证与重现命令 |

沿用的最终依赖：`scripts/organize_auction_ticks.py`、`catalog_auction_ticks.py`负责RAR流式转日分区和日历核对；`fetch_csi500_history.py`负责分批权重快照；`build_local_minute_factors.py`提供原构建器及`normalize_bars()`；`build_auction_factor_history.py`提供旧竞价构建流程；`src/strategy/intraday_factors.py`、`auction_factors.py`、`intraday_factor_research.py`保留因子/研究基准；三个Repository负责本地取数。以上“沿用”不表示本次新增或修改。

本流程未新增DataHub YAML路由。离线仓库由脚本显式注入；在线补充经现有DataHub配置和Tushare凭据。2026-11-15实际环境：Python 3.13.15、pandas 2.2.3、NumPy 2.4.6、PyArrow 24.0.0、DuckDB 1.5.5、Backtrader 1.9.78.123、Tushare 1.4.29、SciPy 1.17.1、Matplotlib 3.10.9；这是整理时环境记录，不证明整个历史运行期间版本未变。重新解压竞价需`unrar`。

工作树仍有未提交修改及未跟踪脚本/成果，尚不能仅靠现有提交恢复完整结果。`.gitignore`、`claude.sh`等其他已有变动不据此归因于该策略；接手时保留，不清理或回滚。

## 6. 已验证结果与证据边界

### 6.1 最后一次完整回测（2026-11-13）

| 指标 | 已落盘结果 |
|---|---:|
| 交易/估值区间 | 2022-02-21至2026-11-02开盘 |
| 调仓次数 | 240 |
| 初始资金 / 期末权益 | 1,000,000 / 1,065,077.15元 |
| 累计 / 年化收益 | +6.51% / +1.35% |
| 最大回撤 | −23.78% |
| 同期中证500累计收益 | −7.80% |
| 相对净值累计 / 年化收益 | +15.52% / +3.12% |
| 累计佣金 / 期末现金 | 89,160.00 / 1.86元 |
| 最新完整候选 / 目标 / 可取价目标 / 模拟持仓 | 475 / 48 / 48 / 48 |
| 最新方向所用IC最晚持有期结束日 | 2026-10-26 |

最新名单见[latest_selection.csv](../../examples/intraday_factors/refresh_20261030/backtest/latest_selection.csv)，前3为中国核建、首创环保、五矿资本；每只目标1/48，实际权重另列。`latest_holdings.csv`的`adjusted_shares`是公司行为近似下的模型份额，不是券商实际股数。

[audit.json](../../examples/intraday_factors/refresh_20261030/audit.json)记录：两类因子均1410日；最新排名和分数独立重算一致；所有方向窗口52条且`last_exit <= signal_date`；逐笔佣金、现金与持仓对账通过；2026年前重叠940个估值日与旧版权益完全一致，最大差异0元。累计37个“持仓×日”沿用旧估值，不能解释为37个独立交易日或永久停牌数量。

### 6.2 测试、数据口径与本次整理核验

以下命令2026-11-13成功执行，2026-11-15整理时再次执行，结果**17 tests / OK**，均为合成或Mock数据，不依赖在线QMT/Tushare：

```bash
.venv/bin/python -m unittest \
  tests.intraday_factors_fast_test tests.auction_tick_repository_test \
  tests.intraday_all_factor_backtest_test tests.intraday_factors_test \
  tests.intraday_factor_research_test tests.auction_factors_test \
  tests.local_minute_repository_test
```

- 真实加速比对：本次刷新及恢复运行在2026-03-02、2026-09-22各取10只股票，39因子与原实现逐项通过`rtol=1e-10, atol=1e-12`比对；这不是全历史双实现重算证明。
- 价格口径证据：`examples/intraday_factors/price_adjustment_check_20261110/summary.csv`保留6只股票×2026-01-05/10-30共12个股票日，匹配2880条分钟；本地/QMT价格比中位数为1。`historical_daily_comparison.csv`有2020–2025年36个股票日的首开/末收与不复权日线对照。**支持不复权假设，未证明全样本逐分钟完全一致**；Repository仍标记`none_assumed/end_assumed`。
- 2026-11-15本次核验：实际因子文件数及首末日与manifest一致；关键成果SHA和回测代码SHA与审计相符；确认原始最新日及符号链接目标；没有重拉数据、重算全量因子、重跑回测或重写审计产物。
- 2026-11-13的完整流水线和`git diff --check`均成功；本次整理未进行项目全量测试、全历史原始数据逐字节重验、供应商完整性认证或实盘成交验证。
- 代码图索引仍为2026-09-20版本，相关新文件未收录且scripts/examples被排除；本交接结构结论来自直接源码核对，不能根据图查询无结果推断功能不存在。

## 7. 复现入口与续更注意事项

所有命令从项目根目录执行，使用现有`.venv`。**完整按顺序执行过的刷新命令已保存在[结果报告的重现命令](refresh_20261030.md#重现命令)**，依次为：

1. `fetch_csi500_history.py --start 20260201 --end 20261031 --output-dir data/intraday_factors/refresh_20261030/csi500_new`。
2. `prepare_intraday_refresh.py`：准备合并快照和参考数据。
3. `refresh_intraday_factors.py`：复用/补算分钟与竞价因子。
4. `auction_history_research.py`：用刷新路径生成资格与收益。
5. `local_minute_factor_research.py`：用刷新路径生成46因子周度IC。
6. `intraday_all_factor_backtest.py`：明确指定刷新快照、因子、覆盖、IC、参考和输出路径。
7. `audit_intraday_refresh.py`及上述17项离线测试。

后三个示例脚本的默认路径仍多指旧版；不要省略报告中的目录参数，以免混用旧数据或覆盖旧结果。审计会写出审计文件，单纯查阅交接时读现有JSON即可。

为避免重复踩坑：

- `scripts/duckdb`会遮蔽第三方`duckdb`包，两个分钟构建入口已移除脚本目录再导入；新增独立脚本要注意同名包搜索路径。
- 新输出独立，但旧日因子是**硬链接**，参考日线/ST及基础资料是**符号链接**。不要原地编辑共享文件；搬迁需保留源缓存和外部`/data3`数据。
- 因子元信息含实现代码和构建脚本SHA，连代码文本变化都可能使缓存失效。应在新版本目录重新生成相应产物，而非改JSON“适配”；不要在运行中修改构建器。
- 新刷新器直接写日Parquet后写JSON；若中断留下单边文件，当前恢复逻辑不保证自行修复。先检查完整性，使用新目录或明确恢复方案；不要删除目录/批量文件绕过项目安全红线。

## 8. 已知限制与后续工作

原任务已完成；以下为后续增强事项，未在本次整理中实施。

1. **继续更新数据：**补齐10月30日之后的真实竞价与分钟、成分及参考数据，再选择共同截止日和下一执行日。当前未产生11月15日信号。
2. **股票池时点：**取得并核实精确历史进出及公布/生效日期，替换月度权重加31天近似；基础资料仍取共享缓存，未做完整历史版本化。
3. **价格与报价质量：**确认供应商全历史复权、分钟标签和单位；竞价采样完整性及振幅定义仍待核实。竞价数量字段曾出现小数，使用数量类新因子前需确认单位。日历齐全不证明逐股逐阶段完整。
4. **可成交与成本：**补充印花税、过户费、滑点、涨跌停/停牌、整手、容量和公司行为现金账；处理长期缺价或退市持仓。当前不保证开盘价可成交，未来缺价退出IC样本仍可能带来偏差。
5. **续更脚本泛化（源码可见边界）：**准备器仍固定旧快照基线和起始日，`retrieval_date`写死2026-11-13；刷新manifest的旧截止日写死2月27日，旧范围复用依赖新增证券尚未生效的特例；审计依赖旧版`all_factor_backtest/nav.csv`；回测仍限制2021-01-04起点。更换基线/日期时须先调整并验证，不能只改`--end`。
6. **待验证的日历边界（源码推断）：**周末信号按`W-FRI`组内最后观测日生成，非完整周截止可能被当作周末；本次10月30日为周五。IC固定T+1至T+6，而周调仓遇长假时实际间隔可能不同，需检验一致性。这两项尚未作为新修复实施。
7. **交付固化：**将必要的未跟踪代码、文档及小型manifest纳入版本管理，按项目约定管理大型外部数据；保留旧版及本次结果供回归。下一会话仍需遵守AGENTS.md：SDK仅在Provider层、测试用Mock、手续费沿用项目模型、不做递归或通配符删除。

## 2026-11-16补充：公共持仓与订单执行

在原研究回测之后新增独立的`examples/intraday_execution.py`及公共`src/trading/`模块；
没有改写原研究回测和`refresh_20261030`产物。当前最新完整执行回放输出为
`examples/intraday_factors/execution_verified_20261116/`。使用和验证详情见
[执行验证](execution_20261116.md)和[公共交易模块](../trading/README.md)。

公共PortfolioLedger按账户/策略隔离现金、实际股数、T+1可卖数量、冻结、订单和成交；
PaperBroker与QMT Adapter共用ExecutionEngine。券商接口仅在
`src/datahub/providers/qmt_trading.py`内；行情使用MarketDataService和独立trading.yaml。
新增instrument数据类型保留完整合约和涨跌停信息，未改变stock_basic精简字段。

当前33项交易测试及相关回归共74项通过，真实QMT只读账户/监听/行情/48股计划验证成功；
没有发送真实下单或撤单，桥接端禁用设置保持原状，真实成交/撤单仍未验收。
原48只股集合不变，整数股执行回放的权益和权重与连续份额研究口径不同。
最新历史信号10月30日、执行11月2日，不能作为11月16日实时委托。

生产中各策略必须共用同一账本，不能自动归属券商手工持仓。当前实盘费用、税费、
真实公司行为和外部划转仍需按券商流水显式处理；对账有差异时停止自动执行。
