# 智能编程助手指南

本文档作为 AI 代理提供全面的使用说明。使用此文件，以了解当前基于 Streamlit 的股票回测 Web 应用，在哪里进行更改以及如何在本地运行程序。

## 快速开始

### 前置条件

- 环境要求 Python 3.13+。
- 安装 `uv` 用于依赖管理（`uv sync`）以及通过 `uv run` 运行 Python 命令。
- 在 windows 终端使用 `./.venv/Scripts/activate.ps1`，或 macOS 终端使用 `source .venv/bin/activate` 激活虚拟环境。

### 开发流程

- 同步依赖: `uv sync`
- 若需添加依赖，运行: `uv sync`
- 运行程序: `uv run streamlit run app.py`
- 运行测试（AkShare 数据需要网络）:
  - `uv python -m unittest tests.ma_test.MaStrategyTest`
  - `uv python -m unittest tests.macross_test.MaCrossStrategyTest`

### 项目结构

- `app.py`: 主入口，Streamlit UI 和协调逻辑。
- `strategy/`: 策略实现 python 代码。
- `config/strategy.yaml`: 策略参数配置。
- `frames/`: Streamlit UI 组件。
- `charts/`: 图表渲染。
- `utils/`: 辅助函数和工具。
- `tests/`: 测试用例。
- `logs/`: 日志文件夹。
- `datas/`: 本地数据缓存（可选），按照 `{策略名}` 目录组织。
- `examples/`: 示例脚本。
- `R/`: R 语言策略脚本。
- `qmt/`: 基于国金证券 qmt 量化框架的 python 策略脚本。
- `utils/qmt_data_client.py`: 普通 Python 策略/回测代码访问 QMT 本地数据服务的客户端。

注意：

- 策略的运行示例在 `examples/{策略名}` 目录下有对应的运行文件。
- R 语言策略脚本在 `R/{策略名}` 目录下。
- 测试文件在 `tests/` 目录下，按策略分类。
- 实现调研在 `docs/{策略名}` 目录下，包括 `中文策略名.txt`（包含策略参考网页地址）、`RESEARCH.md` 实现说明、`README_PYTHON.md` python 说明等。
- qmt 策略脚本，严格依赖 `qmt-api` skill。
- QMT 数据服务说明在 `docs/qmt_data_service.md`。

### 测试与自动化检查

在提交改动前，确保相关检查通过，并在修改代码时扩展测试覆盖。

#### 单元测试与类型检查

- 运行聚焦测试：

  ```bash
  uv run pytest -s -k <pattern>
  ```

- QMT 数据服务聚焦测试（不需要真实 QMT 终端，使用 fake `ContextInfo`）：

  ```bash
  python -m unittest tests.qmt_data_gateway_test
  ```

## 关键文件

- 程序入口: `app.py` (Streamlit UI + orchestration)
- 策略配置: `config/strategy.yaml`
- 策略实现: `strategy/ma.py`, `strategy/macross.py`, `strategy/just_buy_hold.py`, `strategy/equal_weight.py` 等, 共享基类在 `strategy/base.py`
- UI 组件: `frames/sidebar.py` (输入), `frames/form.py` (策略参数)
- 图表: `charts/stock.py` (K线), `charts/results.py` (结果条)
- 数据与回测运行时: `utils/processing.py`
- QMT 数据客户端: `utils/qmt_data_client.py`
- QMT 数据服务文档: `docs/qmt_data_service.md`
- Schemas: `utils/schemas.py`
- 日志: `utils/logs.py` (每天写入日志到 `./logs/`)

## 数据流（高层次）

1. UI 在 `frames/sidebar.py` 收集 AkShare 和 Backtrader 参数。
2. `utils/processing.gen_stock_df` 获取 AkShare 数据并返回精简的 DataFrame。
3. `backtrader.py` 在运行前将列重命名为 Backtrader 友好的名称。
4. 策略参数通过 `frames/form.py` 选择，由 `config/strategy.yaml` 驱动。
5. `utils/processing.run_backtrader` 运行 Backtrader 和分析器，并返回结果 DataFrame。
6. `charts/` 中的图表渲染 K 线和回测指标。

## QMT 数据服务

QMT 的 `ContextInfo` 只能在 QMT 策略生命周期内可靠访问。数据服务把 QMT 行情数据提供给普通策略/回测代码时，使用本项目的本地只读 HTTP 网关，而不是在 Streamlit 或普通 Python 进程里直接调用 `ContextInfo`。

### 客户端约定

- 普通 Python 代码使用 `utils.qmt_data_client.QmtDataClient` 请求 QMT 本地数据服务。
- OHLCV 类数据优先使用 `/v1/market-data-ex`，再用 `get_market_data_ex_df()` 还原为 `pd.DataFrame`。
- 需要接入 Backtrader 时，使用 `to_backtrader_ohlcv()` 输出 `date/open/high/low/close/volume` 列。
- `get_market_data()` 的返回形态会随 QMT 参数变化，网关会对 pandas 结构加 `type` 标签；消费端不要假设它总是 DataFrame。
- `subscribe_quote()` 暂不开放；实时订阅需要单独设计推送或轮询机制。

## 约定与注意事项

- 策略类在 `strategy` 包中动态发现，类命名格式为 `{Name}Strategy`，文件名格式为小写下划线方式 `name.py`，如果文件过多，需要创建小写下划线方式的同名文件夹作为包名来整理文件。
- `config/strategy.yaml` 控制参数 UI；保持名称与策略参数同步。
- Streamlit 缓存用于数据和回测；如果模式更改，需谨慎更新缓存键。
- QMT 数据服务为本机只读访问；默认使用 token 时不要在日志中打印 token。
- QMT `ContextInfo` 线程安全需要在真实 QMT 环境手动验证；如果发现线程调用不稳定，应改为队列化请求并在 QMT 安全的生命周期内处理。
