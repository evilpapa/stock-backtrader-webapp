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
- `src/utils/`：数据处理、日志、schemas、QMT API 客户端等工具。
- `tests/`：测试用例，**仅使用模拟数据**。
- `examples/`：策略运行示例，策略运行结果文件按照策略名保存；**接入qmt真实数据**。
- `docs/`：策略调研与实现说明，按策略名分目录。
- `r/`：R 语言策略脚本。

## 关键约定

- 策略类命名为 `{Name}Strategy`，文件名使用小写下划线 `name.py`；文件较多时可整理为同名包目录。
- 使用 `src.utils.bigqmt_client.QmtDataClient` 统一访问原生 `xtquant.xtdata`；不要在业务模块重复创建行情客户端。
- 获取数据的方法参考 xtquant-xtdata skill。
- 不要使用 `bigqmt_signal_trader.xtquant_compat`、`bigqmt_signal_trader.redis_rpc`，也不要把 xtdata 方法封装为 `call(method, args)`。
- `utils.bigqmt_client` 是统一行情客户端入口；历史 `fetch_history_ohlcv` 等名称继续兼容。
- 接入 Backtrader 时使用 `to_backtrader_ohlcv()` 输出 `date/open/high/low/close/volume` 列。
- 修改 Streamlit 缓存相关逻辑时，注意缓存键和数据模式变更。

## 数据流

1. `src/frames/sidebar.py` 收集行情数据和 Backtrader 参数。
2. `src/utils/processing.gen_stock_df` 通过 QMT API 获取数据并返回精简 DataFrame。
3. 运行 Backtrader 前将列名转换为 Backtrader 友好格式。
4. `src/frames/form.py` 根据 `src/config/strategy.yaml` 渲染策略参数。
5. `src/utils/processing.run_backtrader` 执行回测并返回结果。
6. `src/charts/` 渲染 K 线和回测指标。
