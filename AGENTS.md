# 智能编程助手指南

## 快速开始

- Python 3.13+，使用 `uv sync` 同步依赖。
- Windows 激活虚拟环境：`./.venv/Scripts/activate.ps1`；macOS/Linux：`source .venv/bin/activate`。
- 运行应用：`.venv/Scripts/python.exe -m streamlit run app.py`
- 常用测试：
  - `.venv/Scripts/python.exe -m unittest tests.ma_test.MaStrategyTest`
  - `.venv/Scripts/python.exe -m unittest tests.macross_test.MaCrossStrategyTest`
  - `.venv/Scripts/python.exe -m pytest -s -k <pattern>`

## 项目结构

- `app.py`：Streamlit 主入口与协调逻辑。
- `strategy/`：策略实现；共享基类在 `strategy/base.py`。
- `config/strategy.yaml`：策略参数 UI 配置，需与策略参数保持同步。
- `frames/`：Streamlit UI 组件。
- `charts/`：图表渲染。
- `utils/`：数据处理、日志、schemas、xtdata 客户端等工具。
- `tests/`：测试用例。
- `examples/`：策略运行示例，按策略名分目录。
- `docs/`：策略调研与实现说明，按策略名分目录。
- `R/`：R 语言策略脚本。

## 关键约定

- 策略类命名为 `{Name}Strategy`，文件名使用小写下划线 `name.py`；文件较多时可整理为同名包目录。
- 普通 Python 代码通过 `utils.xtdata_client.fetch_history_ohlcv` 访问本机 miniQMT 数据服务。
- 接入 Backtrader 时使用 `to_backtrader_ohlcv()` 输出 `date/open/high/low/close/volume` 列。
- qmt 策略脚本依赖 `qmt-api` skill；miniQMT 数据服务依赖 `xtquant-xtdata` skill。
- 修改 Streamlit 缓存相关逻辑时，注意缓存键和数据模式变更。

## 数据流

1. `frames/sidebar.py` 收集行情数据和 Backtrader 参数。
2. `utils/processing.gen_stock_df` 获取 xtdata 数据并返回精简 DataFrame。
3. 运行 Backtrader 前将列名转换为 Backtrader 友好格式。
4. `frames/form.py` 根据 `config/strategy.yaml` 渲染策略参数。
5. `utils/processing.run_backtrader` 执行回测并返回结果。
6. `charts/` 渲染 K 线和回测指标。
