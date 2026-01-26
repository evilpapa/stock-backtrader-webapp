# 智能编程助手指南

本文档作为 AI 代理提供全面的使用说明。使用此文件，以了解当前基于 Streamlit 的股票回测 Web 应用，在哪里进行更改以及如何在本地运行程序。

## 快速开始

### 前置条件

- 环境要求 Python 3.12+。
- 安装 `uv` 用于依赖管理（`uv sync`）以及通过 `uv run` 运行 Python 命令。
- 在终端使用 `./.venv/Scripts/activate.ps1` 激活虚拟环境。

### 开发流程

- 安装依赖: `uv pip install -r requirements.txt`
- 若依赖有变更，运行: `uv sync`
- 运行程序: `uv run streamlit run backtrader_app.py`
- 运行测试（AkShare 数据需要网络）:
  - `uv python -m unittest tests.ma_test.MaStrategyTest`
  - `uv python -m unittest tests.macross_test.MaCrossStrategyTest`

### 测试与自动化检查

在提交改动前，确保相关检查通过，并在修改代码时扩展测试覆盖。

#### 单元测试与类型检查

- 运行完整测试套件：

  ```bash
  make tests
  ```

- 运行聚焦测试：

  ```bash
  uv run pytest -s -k <pattern>
  ```

- 类型检查：

  ```bash
  make mypy
  ```

## 关键文件

- 程序入口: `backtrader_app.py` (Streamlit UI + orchestration)
- 策略配置: `config/strategy.yaml`
- 策略实现: `strategy/ma.py`, `strategy/macross.py`, 共享基类在 `strategy/base.py`
- UI 组件: `frames/sidebar.py` (输入), `frames/form.py` (策略参数)
- 图表: `charts/stock.py` (K线), `charts/results.py` (结果条)
- 数据与回测运行时: `utils/processing.py`
- Schemas: `utils/schemas.py`
- 日志: `utils/logs.py` (每天写入日志到 `./logs/`)

## 数据流（高层次）

1. UI 在 `frames/sidebar.py` 收集 AkShare 和 Backtrader 参数。
2. `utils/processing.gen_stock_df` 获取 AkShare 数据并返回精简的 DataFrame。
3. `backtrader_app.py` 在运行前将列重命名为 Backtrader 友好的名称。
4. 策略参数通过 `frames/form.py` 选择，由 `config/strategy.yaml` 驱动。
5. `utils/processing.run_backtrader` 运行 Backtrader 和分析器，并返回结果 DataFrame。
6. `charts/` 中的图表渲染 K 线和回测指标。

## 约定与注意事项

- 策略类在 `strategy` 包中动态发现，命名格式为 `{Name}Strategy`，如果文件过多，需要创建同名的文件夹作为包名来整理文件。
- `config/strategy.yaml` 控制参数 UI；保持名称与策略参数同步。
- 测试从 AkShare 拉取数据，需要网络访问；失败可能与数据源相关。
- Streamlit 缓存用于数据和回测；如果模式更改，需谨慎更新缓存键。
