# 智能编程助手指南

## 快速开始

- Python 3.13+，使用 `uv sync` 同步依赖。
- 激活虚拟环境：`source .venv/bin/activate`
- 运行应用：`streamlit run app.py`
- 常用测试：
  - `.venv/bin/python -m unittest tests.xtdata_client_test`
  - `.venv/bin/python -m unittest tests.ma_test.MaStrategyTest`
  - `.venv/bin/python -m unittest tests.macross_test.MaCrossStrategyTest`
  - `.venv/bin/python -m pytest -s -k <pattern>`

## 项目结构

- `app.py`：Streamlit 主入口与协调逻辑。
- `strategy/`：策略实现；共享基类在 `strategy/base.py`。
- `config/strategy.yaml`：策略参数 UI 配置，需与策略参数保持同步。
- `frames/`：Streamlit UI 组件。
- `charts/`：图表渲染。
- `utils/`：数据处理、日志、schemas、AKShare 数据客户端等工具。
- `tests/`：测试用例。
- `examples/`：策略运行示例，按策略名分目录。
- `docs/`：策略调研与实现说明，按策略名分目录。
- `R/`：R 语言策略脚本。

## 关键约定

- 策略类命名为 `{Name}Strategy`，文件名使用小写下划线 `name.py`；文件较多时可整理为同名包目录。
- 通过 `utils.xtdata_client.fetch_history_ohlcv` 获取 A股/ETF 行情数据（基于 AKShare 新浪数据源，无需本地 QMT）。
- 接入 Backtrader 时使用 `to_title_case_ohlcv()` 输出 Open/High/Low/Close/Volume 列。
- 数据源的复权参数：`front`/`qfq` = 前复权，`back`/`hfq` = 后复权。

## 数据流

1. `frames/sidebar.py` 收集行情数据和 Backtrader 参数（使用 `DataParams` 替代原 `XtDataParams`）。
2. `utils/processing.gen_stock_df` 通过 AKShare 获取数据并返回精简 DataFrame。
3. 运行 Backtrader 前将列名转换为 Backtrader 友好格式。
4. `frames/form.py` 根据 `config/strategy.yaml` 渲染策略参数。
5. `utils/processing.run_backtrader` 执行回测并返回结果。
6. `charts/` 渲染 K 线和回测指标。

## 数据源说明

原项目使用 xtquant/miniQMT（需 Windows + 国金证券 QMT 终端），现已改为 **AKShare（新浪数据源）**：
- **股票数据**：`ak.stock_zh_a_daily` — 支持前复权/后复权
- **ETF 数据**：`ak.fund_etf_hist_sina` — 原生数据
- 代码格式：支持 `000001`、`000001.SZ`、`sh000001` 等多种格式
- Linux 和 macOS 均可直接使用，无需 QMT/xtquant 环境
