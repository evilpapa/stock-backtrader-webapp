# ETF 动量策略 - 安装和使用指南

本文档说明 Python 版 ETF 动量策略的运行方式。当前版本使用 `xtdata`/miniQMT 本地数据服务获取行情。

## 前置条件

- Python 3.13+
- 使用 `uv` 管理依赖
- 本机 miniQMT/xtdata 数据服务可用
- 已准备好策略标的的历史行情数据

## 安装依赖

```bash
uv sync
```

项目依赖已在 `pyproject.toml` 中维护，ETF 动量回测主要使用：

- `backtrader`：回测引擎
- `pandas` / `numpy`：数据处理
- `empyrical-reloaded`：绩效指标
- `matplotlib`：图表输出
- `utils.xtdata_client`：本项目封装的 xtdata 客户端

## 运行独立回测脚本

```bash
uv run python examples/etf_momentum/backtest_etf_momentum.py
```

脚本会：

1. 调用 `fetch_history_ohlcv()` 从 xtdata 获取 ETF 历史行情。
2. 转换为 Backtrader 需要的 OHLCV 格式。
3. 运行动量策略、沪深 300 ETF 买入持有基准、等权组合基准。
4. 生成绩效指标、每日收益、每日权重和图表。

输出目录：`examples/etf_momentum/backtest_results/`

## 在 Streamlit 中使用

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

在侧边栏选择 `EtfMomentum`，配置参数后运行回测。

## 配置标的与参数

默认标的定义在 `examples/etf_momentum/backtest_etf_momentum.py`：

```python
ETF_SYMBOLS = ["513100", "510300", "518880"]
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]
```

通用参数定义在 `examples/backtest_constants.py`：

```python
INITIAL_CASH = 100000.0
COMMISSION = 0.025
MOMENTUM_WINDOW = 20
```

修改标的时，请使用 xtdata/miniQMT 可识别的证券代码格式，并确认本地数据服务能返回对应历史行情。

## 运行测试

```bash
.venv/Scripts/python.exe -m unittest tests.etf_momentum_test.EtfMomentumTest
```

也可以运行聚焦 pytest：

```bash
.venv/Scripts/python.exe -m pytest -s -k etf_momentum
```

## 常见问题

### xtdata 数据获取失败

检查以下项目：

1. miniQMT 是否已启动并可提供本地数据服务。
2. ETF 代码是否为 xtdata 可识别格式。
3. 本地是否已下载对应时间段的历史行情。
4. `BACKTEST_START` / `BACKTEST_END` 是否覆盖了可用数据范围。

### 回测结果为空或图表缺失

通常是数据为空或可用交易日不足导致。先确认 `fetch_history_ohlcv()` 能返回包含 `open/high/low/close/volume` 的非空数据，再运行完整回测。

### 字体或中文显示异常

脚本已调用 `charts.configure_matplotlib_chinese_font()`。如果仍异常，请确认项目字体文件和 matplotlib 字体缓存状态。