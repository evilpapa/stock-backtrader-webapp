# 智能编程助手指南

本文档作为 AI 代理提供全面的使用说明。使用此文件，以了解当前基于 Streamlit 的股票回测 Web 应用，在哪里进行更改以及如何在本地运行程序。

## 快速开始

### 前置条件

- 环境要求 Python 3.12+。
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
- `strategy/`: 策略实现。
- `config/strategy.yaml`: 策略参数配置。
- `frames/`: Streamlit UI 组件。
- `charts/`: 图表渲染。
- `utils/`: 辅助函数和工具。
- `tests/`: 测试用例。
- `logs/`: 日志文件夹。
- `datas/`: 本地数据缓存（可选），按照 `{策略名}` 目录组织。
- `examples/`: 示例脚本。
- `R/`: R 语言策略脚本。

注意：

- 策略的运行示例在 `examples/{策略名}` 目录下有对应的运行文件。
- R 语言策略脚本在 `R/{策略名}` 目录下。
- 测试文件在 `tests/` 目录下，按策略分类。
- 实现调研在 `docs/{策略名}` 目录下，包括 `RESEARCH.md` 实现说明、`README_PYTHON.md` python 说明等。

### 测试与自动化检查

在提交改动前，确保相关检查通过，并在修改代码时扩展测试覆盖。

#### 单元测试与类型检查

- 运行聚焦测试：

  ```bash
  uv run pytest -s -k <pattern>
  ```

## 关键文件

- 程序入口: `app.py` (Streamlit UI + orchestration)
- 策略配置: `config/strategy.yaml`
- 策略实现: `strategy/ma.py`, `strategy/macross.py`, `strategy/just_buy_hold.py`, `strategy/equal_weight.py` 等, 共享基类在 `strategy/base.py`
- UI 组件: `frames/sidebar.py` (输入), `frames/form.py` (策略参数)
- 图表: `charts/stock.py` (K线), `charts/results.py` (结果条)
- 数据与回测运行时: `utils/processing.py`
- Schemas: `utils/schemas.py`
- 日志: `utils/logs.py` (每天写入日志到 `./logs/`)

## 数据流（高层次）

1. UI 在 `frames/sidebar.py` 收集 AkShare 和 Backtrader 参数。
2. `utils/processing.gen_stock_df` 获取 AkShare 数据并返回精简的 DataFrame。
3. `backtrader.py` 在运行前将列重命名为 Backtrader 友好的名称。
4. 策略参数通过 `frames/form.py` 选择，由 `config/strategy.yaml` 驱动。
5. `utils/processing.run_backtrader` 运行 Backtrader 和分析器，并返回结果 DataFrame。
6. `charts/` 中的图表渲染 K 线和回测指标。

## 约定与注意事项

- 策略类在 `strategy` 包中动态发现，类命名格式为 `{Name}Strategy`，文件名格式为小写下划线方式 `name.py`，如果文件过多，需要创建小写下划线方式的同名文件夹作为包名来整理文件。
- `config/strategy.yaml` 控制参数 UI；保持名称与策略参数同步。
- 测试从 AkShare 拉取数据，需要网络访问；失败可能与数据源相关。
- Streamlit 缓存用于数据和回测；如果模式更改，需谨慎更新缓存键。
