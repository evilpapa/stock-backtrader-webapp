# 智能编程助手指南

本文档作为 AI 代理提供全面的使用说明。使用此文件，以了解当前基于 Streamlit 的股票回测 Web 应用，在哪里进行更改以及如何在本地运行程序。

## 快速开始

### 前置条件

- 环境要求 Python 3.13+。
- 安装 `uv` 用于依赖管理（`uv sync`）。
- 在 windows 终端使用 `./.venv/Scripts/activate.ps1`，或 macOS 终端使用 `source .venv/bin/activate` 激活虚拟环境。

### 开发流程

- 同步依赖: `uv sync`
- 若需添加依赖，运行: `uv sync`
- 运行程序: `.venv/Scripts/python.exe -m streamlit run app.py`
- 运行测试:
  - `.venv/Scripts/python.exe -m unittest tests.ma_test.MaStrategyTest`
  - `.venv/Scripts/python.exe -m unittest tests.macross_test.MaCrossStrategyTest`

### 项目结构

- `app.py`: 主入口，Streamlit UI 和协调逻辑。
- `strategy/`: 策略实现 python 代码。
- `config/strategy.yaml`: 策略参数配置。
- `frames/`: Streamlit UI 组件。
- `charts/`: 图表渲染。
- `utils/`: 辅助函数和工具。
- `tests/`: 测试用例。
- `logs/`: 日志文件夹。
- `examples/`: 示例脚本。
- `R/`: R 语言策略脚本。
- `utils/xtdata_client.py`: 普通 Python 策略/回测代码访问 miniQMT 本地数据服务的客户端。

注意：

- 策略的运行示例在 `examples/{策略名}` 目录下有对应的运行文件。
- R 语言策略脚本在 `R/{策略名}` 目录下。
- 测试文件在 `tests/` 目录下，按策略分类。
- 实现调研在 `docs/{策略名}` 目录下，包括 `中文策略名.txt`（包含策略参考网页地址）、`RESEARCH.md` 实现说明、`README_PYTHON.md` python 说明等。
- qmt 策略脚本，严格依赖 `qmt-api` skill。
- miniQMT 数据服务，严格依赖 `xtquant-xtdata` skill。

### 测试与自动化检查

在提交改动前，确保相关检查通过，并在修改代码时扩展测试覆盖。

#### 单元测试与类型检查

- 运行聚焦测试：

  ```bash
  .venv/Scripts/python.exe -m pytest -s -k <pattern>
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
- xtdata 数据客户端: `utils/xtdata_client.py`
- xtdata 数据服务文档位于: `.agents/skills/xtquant-xtdata/reference` 下
- Schemas: `utils/schemas.py`
- 日志: `utils/logs.py` (每天写入日志到 `./logs/`)

## 数据流（高层次）

1. UI 在 `frames/sidebar.py` 收集 行情数据 和 Backtrader 参数。
2. `utils/processing.gen_stock_df` 获取 xtdata 数据并返回精简的 DataFrame。
3. `backtrader.py` 在运行前将列重命名为 Backtrader 友好的名称。
4. 策略参数通过 `frames/form.py` 选择，由 `config/strategy.yaml` 驱动。
5. `utils/processing.run_backtrader` 运行 Backtrader 和分析器，并返回结果 DataFrame。
6. `charts/` 中的图表渲染 K 线和回测指标。

## xtdata (miniQMT) 数据服务

xtdata 通过 miniQMT 获取数据。

### 客户端约定

- 普通 Python 代码使用 `utils.xtdata_client.fetch_history_ohlcv` 请求 miniQMT 本地数据服务。
- 需要接入 Backtrader 时，使用 `to_backtrader_ohlcv()` 输出 `date/open/high/low/close/volume` 列。

## 约定与注意事项

- 策略类在 `strategy` 包中动态发现，类命名格式为 `{Name}Strategy`，文件名格式为小写下划线方式 `name.py`，如果文件过多，需要创建小写下划线方式的同名文件夹作为包名来整理文件。
- `config/strategy.yaml` 控制参数 UI；保持名称与策略参数同步。
- Streamlit 缓存用于数据和回测；如果模式更改，需谨慎更新缓存键。
- xtdata 数据服务为读取本机 miniQMT 服务。
