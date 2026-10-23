# 股票回测 Web 应用

基于 Python 的 A 股策略回测应用。应用通过 Streamlit 提供交互界面，使用
Backtrader 执行回测，并通过统一的 `DataHub` 数据访问层获取行情和基础数据。DataHub
根据数据类型和 YAML 路由策略选择 Tushare Pro 或 QMT XtQuant，业务层不直接依赖任一
第三方 SDK。日线数据可以同步到 `duckdb`，扩展行情数据使用 `kdb-x` 存储。

门槛：你需要了解什么是「迅投 qmt」,并找你的券商帮你开通。或者你自己找 AI 帮你改造成 AKShare。

![demo](demo.gif)

## 核心特性

- **策略回测**：使用 Backtrader 测试交易策略表现。
- **结果可视化**：使用 Pyecharts 展示行情与回测结果。
- **交互界面**：使用 Streamlit 配置数据源、策略参数和回测参数。
- **数据维护**: 使用 duckdb 存储日线数据，包括股票、etf 等数据；tick 使用 kdb-x 存储。
- **统一数据访问层**：`src.datahub` 提供统一请求模型、代码映射、字段和单位标准化、缓存、持久化、质量校验及数据版本追踪。
- **多数据源路由**：默认日线和基本信息优先使用 Tushare，分钟、Tick、实时行情优先使用 XtQuant；主数据源不可用时按配置切换备用源。
- **实时行情**：通过 `RealtimeDataService` 提供订阅、取消订阅、事件分发、共享订阅和重连能力。
- **兼容桥接入口**：`src.utils.datahub_client.DataHubClient` 供现有回测、同步和研究脚本使用；旧行情函数仅作为迁移兼容层保留。

## 技术架构

| 组件                    | 功能                                  | 链接                                                  |
|-------------------------|---------------------------------------|-------------------------------------------------------|
| **DataHub** | 统一数据访问 Facade、路由、标准化、缓存和版本管理 | [`src/datahub`](src/datahub) |
| **Tushare Adapter** | 通过 DataHub 接入 Tushare Pro | [官方网站](https://tushare.pro/) |
| **XtQuant Adapter** | 通过 DataHub 接入 QMT XtQuant/桥接服务 | [XtQuant 文档](https://dict.thinktrader.net/) |
| **Streamlit**           | 构建交互式数据应用界面                | [官方仓库](https://github.com/streamlit/streamlit)    |
| **Backtrader**          | 执行量化交易策略回测                  | [官方仓库](https://github.com/mementum/backtrader)    |
| **Pyecharts**           | 生成金融数据图表                      | [官方仓库](https://github.com/pyecharts/pyecharts)    |

## 快速开始

### 1. 安装项目依赖

在项目根目录执行：

```powershell
uv sync
```

### 2. 配置 DataHub 数据源

DataHub 配置文件位于 [`src/datahub/config/datahub.yaml`](src/datahub/config/datahub.yaml)。
敏感凭证通过环境变量提供，不要写入 YAML 或代码。

配置 Tushare Pro：

```powershell
$env:TUSHARE_TOKEN = "你的 Tushare Pro Token"
```

配置 QMT/XtQuant（需要本机安装 QMT 或可用的桥接服务）：

```powershell
$env:QMT_PATH = "你的 QMT userdata_mini 路径"
```

DataHub 会从上述环境变量读取连接信息。路由、重试、缓存、数据单位和 XtQuant
代码格式均在 YAML 中配置。

### 3. 启动应用

```powershell
uv run streamlit run app.py
```

在侧边栏填写股票代码、周期和日期范围后，应用通过 DataHub 请求统一行情数据。
DataHub 完成代码映射、复权口径、时间格式、成交量/成交额单位和质量校验，再转换为
Backtrader 使用的 `date/open/high/low/close/volume` 列。

### 4. 运行测试

```powershell
uv run python -m pytest tests -q
```

DataHub 的离线测试不需要真实账号：

```powershell
uv run python -m pytest -q tests/datahub_test.py
```

DataHub 的完整使用方式、路由规则、Provider 接入和集成测试说明见
[`docs/datahub/README.md`](docs/datahub/README.md)。

### ETF 动量策略的三种 DataHub 数据源

`examples/etf_momentum.py` 的业务代码只调用 `DataHubClient`，可以用同一条回测流程验证
Tushare、QMT/XtQuant 和本地 QMT DuckDB cache。结果默认按数据源写入独立目录，避免相互覆盖：

```bash
uv run python examples/etf_momentum.py \
  --data-source tushare --start 2025-01-01 --end 2026-09-23

uv run python examples/etf_momentum.py \
  --data-source qmt --start 2025-01-01 --end 2026-09-23

uv run python examples/etf_momentum.py \
  --data-source cache --cache-path data/etf.duckdb --dividend-type none \
  --start 2025-01-01 --end 2026-09-23
```

本地 `data/etf.duckdb` 是 QMT 日线同步库，当前保存不复权数据，因此 cache 模式必须显式
使用 `--dividend-type none`；复权行情应通过 Tushare 或 QMT Provider 获取。每次运行都会打印
实际 DataHub Provider、各标的记录数和回测指标，结果包括 `performance_metrics.csv`、每日收益、
回撤、权重及 PNG 图表。

### DataHub 编程接口

业务代码应依赖统一的 `MarketDataService` 或项目便捷入口 `DataHubClient`：

```python
from src.datahub import DataRequest, create_service

service = create_service()
try:
    bars = service.get_daily(
        DataRequest(
            symbols=("000001.SZ",),
            start="2024-01-01",
            end="2024-12-31",
            frequency="1d",
            adjust="qfq",
        )
    )
finally:
    service.close()
```

统一行情结果包含 `symbol`、`datetime`、`open`、`high`、`low`、`close`、
`volume`、`amount`、`source`、`frequency` 和 `adjust` 等字段。内部证券代码统一使用
`000001.SZ`、`600000.SH`、`430047.BJ` 格式；业务代码不应手工替换市场后缀。

## 数据与回测参数

### DataHub 行情参数

| 参数                      | 说明                                                              |
|---------------------------|-------------------------------------------------------------------|
| **symbol**                | 股票代码，例如 `600070` 或 `600070.SH`；客户端会补全交易所后缀。  |
| **period**                | 数据周期，例如 `1d`、`1w`、`1mon`。                               |
| **start date / end date** | 行情数据的起止日期。                                              |
| **dividend type**         | 复权方式：`front`（前复权）、`back`（后复权）、`none`（不复权）。 |
| **data source**           | 由 DataHub 路由配置决定，业务层无需指定第三方 API。                 |
| **TUSHARE_TOKEN**         | Tushare Adapter 使用的访问令牌；从环境变量读取。                   |
| **QMT_PATH**              | XtQuant/QMT Adapter 使用的本地 QMT 路径；从环境变量读取。           |
| **timeout / retries**     | 在 DataHub YAML 中配置请求超时和重试次数。                          |
| **cache / storage**       | 在 DataHub YAML 中配置内存缓存、SQLite/Parquet 持久化和版本记录。    |

### Backtrader 回测参数

| 参数                      | 说明                 |
|---------------------------|----------------------|
| **start date / end date** | 回测起止日期。       |
| **start cash**            | 初始资金。           |
| **commission fee**        | 交易佣金比例。       |
| **stake**                 | 每次交易的固定股数。 |

## 支持的策略

- **MA 策略**：基于单一移动平均线的趋势跟踪策略。
- **MACross 策略**：基于快慢双均线交叉的交易策略。
- **ETF 动量策略**
- **行业 ETF 轮动策略**
- **龙头动量轮动策略**
- **海龟交易法则策略**：写着玩，无用途
- **神秘螺旋**

## 常见问题

| 现象                       | 排查方向                                                                               |
|----------------------------|----------------------------------------------------------------------------------------|
| 请求失败                   | 检查 DataHub 路由、Provider 可用性、`TUSHARE_TOKEN`、QMT 环境和接口权限。             |
| 行情返回为空               | 检查统一证券代码、日期范围、Provider 权限和 DataHub 请求日志。                       |
| XtQuant 不可用             | 检查 QMT/MiniQmt、`QMT_PATH`、桥接服务和本机 Python 环境。                         |
| 单位或复权不一致           | 检查 `src/datahub/config/datahub.yaml` 中的 `units`、`routing` 和 `adjust` 配置。    |
