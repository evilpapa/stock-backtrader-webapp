# 智能编程助手指南

## 快速开始

- Python 3.13+，使用 `uv sync` 同步依赖。
- 激活虚拟环境
  - Windows ：`./.venv/Scripts/activate.ps1`
  - macOS/Linux：`source .venv/bin/activate`
- 运行应用：`python -m streamlit run app.py`
- 常用测试：
  - `python -m unittest tests.ma_test.MaStrategyTest`
  - `python -m unittest tests.macross_test.MaCrossStrategyTest`
  - `python -m pytest -s -k <pattern>`

## 项目结构

- `app.py`：Streamlit 主入口与协调逻辑。
- `src/strategy/`：策略实现；共享基类在 `src/strategy/_base.py`。
- `src/config/strategy.yaml`：策略参数 UI 配置，需与策略参数保持同步。
- `src/frames/`：Streamlit UI 组件。
- `src/charts/`：图表渲染。
- `src/datahub/`：统一数据访问层，包含 Provider Adapter、DataRouter、Normalizer、缓存、Repository 和实时订阅能力。
- `src/utils/`：数据处理、日志、schemas 以及 DataHub 兼容便捷入口等工具；不得在业务模块中直接调用第三方数据源 SDK。
- `tests/`：测试用例，**仅使用模拟数据**。
- `examples/`：策略运行示例，策略运行结果文件按照策略名保存；**接入qmt真实数据**。
- `docs/`：策略调研与实现说明，按策略名分目录。
- `r/`：R 语言策略脚本。

## 关键约定

- 策略类命名为 `{Name}Strategy`，文件名使用小写下划线 `name.py`；文件较多时可整理为同名包目录。
- 业务层统一使用 `src.datahub.MarketDataService`，或使用仅作便捷适配的 `src.utils.datahub_client.DataHubClient`；不要直接导入或调用 Tushare、XtQuant、QMT 原生 API。
- Provider 的创建、优先级、备用切换、重试、缓存、单位转换和代码格式统一由 `src/datahub/config/datahub.yaml` 与 `DataRouter` 管理。
- 内部证券代码统一使用 `000001.SZ`、`600000.SH`、`430047.BJ` 格式；业务代码不得手工替换市场后缀，使用 `TickerMapper` 完成转换。
- 历史行情请求必须通过 DataHub 标准请求模型获取，并保留 `source`、`frequency`、`adjust`、`data_version` 等追溯信息；财务回测需要设置 `as_of`，避免公告时点之后的数据泄漏。
- 获取数据的方法可参考 tushare-data、xtquant 相关 skill，但第三方接口调用只能放在 `src/datahub/providers/` Adapter 内；数据需使用 DataHub 缓存或 Repository，减少重复远程请求。
- 接入 Backtrader 时使用 `to_backtrader_ohlcv()` 输出 `date/open/high/low/close/volume` 列。
- 回测时手续费严格按照 `src/utils/commission.py` 的定义。
- 修改 Streamlit 缓存相关逻辑时，注意缓存键和数据模式变更。
- 运行 ETF 动量示例时使用 `--data-source tushare|qmt|cache` 选择 DataHub 数据源；不要在示例或策略中直接调用 Tushare/XtQuant 原生 API。
- `cache` 模式读取 `data/etf.duckdb` 等只读本地 QMT 日线缓存；该缓存保存 `none` 口径，运行时必须显式传 `--dividend-type none`。

## 数据流

1. `src/frames/sidebar.py` 收集行情请求和 Backtrader 参数。
2. `src/utils/processing.gen_stock_df` 通过 `DataHubClient`/`MarketDataService` 获取统一行情，并返回精简 DataFrame。
3. DataHub 完成证券代码映射、字段映射、时间标准化、单位转换、复权口径、质量校验和数据源记录。
4. 运行 Backtrader 前将列名转换为 Backtrader 友好格式。
5. `src/frames/form.py` 根据 `src/config/strategy.yaml` 渲染策略参数。
6. `src/utils/processing.run_backtrader` 执行回测并返回结果。
7. `src/charts/` 渲染 K 线和回测指标。

## DataHub 开发约定

- 默认路由：日线、股票基础信息和财务数据优先使用 Tushare；分钟、Tick、实时和 Level2 数据优先使用 XtQuant；具体规则以 YAML 为准。
- 新增数据类型时，先扩展 `DataKind`、统一请求/结果模型和 Provider Adapter，再修改业务调用方；不要在策略、页面或脚本中拼接第三方 API 参数。
- 实时行情使用 `RealtimeDataService`，通过 Observer 回调分发事件；多个策略共享同一证券订阅，避免重复建立底层订阅。
- 单元测试必须使用 Mock Provider/Fake SDK，不依赖真实账号；Tushare 账户和 QMT 环境测试放在 `tests/integration/`，并与普通测试分开执行。
- 修改数据字段、单位、路由或缓存 Key 时，同时更新 `docs/datahub/README.md`、YAML 示例和 DataHub 测试。
- 修改 ETF 数据源或回测取数流程后，至少分别执行一次 Tushare、QMT 和 cache 模式的 `examples/etf_momentum.py`，并将结果写入按数据源区分的输出目录。
