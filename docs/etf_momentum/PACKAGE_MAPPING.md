# ETF 动量策略 R 到 Python 依赖映射

本文档说明 ETF 动量策略从 R 版本迁移到当前 Python 版本时，各功能模块的替代关系。当前 Python 版本的数据源为项目内 xtdata 客户端。

## 包/模块映射

| R 包/功能 | Python 对应 | 用途 |
| --- | --- | --- |
| `quantmod::getSymbols()` | `utils.xtdata_client.fetch_history_ohlcv()` | 从本机 miniQMT/xtdata 获取历史行情 |
| `Ad()` / OHLC 提取 | `to_title_case_ohlcv()` + pandas 列选择 | 转换为 Backtrader OHLCV 数据 |
| `PerformanceAnalytics` | `empyrical-reloaded` + `strategy.performance_calculator.PerformanceCalculator` | 绩效指标 |
| `dplyr` / `tidyr` | `pandas` | 数据清洗、合并、透视、导出 |
| `xts` / `zoo` | `pandas.Series` / `pandas.DataFrame` | 时间序列处理 |
| `ggplot2` / `cowplot` / `patchwork` | `matplotlib` / `GridSpec` | 图表绘制与组合 |
| R 自定义回测逻辑 | `backtrader` | 策略执行、账户、交易与分析器 |

## 数据获取对比

### R 版本

```r
library(quantmod)
getSymbols("510300.SS", from = "2024-01-01", to = "2024-12-31", src = "yahoo")
prices <- Ad(get("510300.SS"))
```

### 当前 Python 版本

```python
from utils.xtdata_client import fetch_history_ohlcv, to_title_case_ohlcv

df = fetch_history_ohlcv("510300", "2025-01-01", "2026-01-01")
df = to_title_case_ohlcv(df)
df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
```

迁移要点：

- ETF 代码使用 xtdata/miniQMT 本地代码格式，例如 `510300`。
- 数据可用性取决于本机 miniQMT 数据服务和本地历史数据。
- Python 脚本统一使用 Backtrader 友好的 OHLCV 列名。

## 滚动指标对比

### R

```r
momentum <- rollapply(returns, width = 20, FUN = mean, align = "right", fill = NA)
volatility <- rollapply(returns, width = 20, FUN = sd, align = "right", fill = NA)
```

### Python / Backtrader

```python
ret = bt.indicators.PctChange(data.close, period=1)
momentum = bt.indicators.SimpleMovingAverage(ret, period=20)
volatility = bt.indicators.StandardDeviation(ret, period=20)
adj_momentum = momentum / volatility
```

## 绩效分析对比

### R

```r
library(PerformanceAnalytics)
Return.annualized(returns)
SharpeRatio.annualized(returns)
maxDrawdown(returns)
```

### Python

```python
from strategy.performance_calculator import PerformanceCalculator

calc = PerformanceCalculator()
calc.annualized_return(returns)
calc.sharpe_ratio(returns)
calc.max_drawdown(returns)
```

## 可视化对比

R 版本使用 `ggplot2` 组织图层；Python 版本使用 `matplotlib` 和 `GridSpec` 输出：

- 累计收益对比图
- 回撤图
- 每日权重堆叠面积图

图表保存到 `examples/etf_momentum/backtest_results/`。

## 当前 Python 实现的核心文件

- `examples/etf_momentum/backtest_etf_momentum.py`：独立回测脚本。
- `utils/xtdata_client.py`：xtdata 数据客户端。
- `strategy/performance_calculator.py`：绩效指标计算。
- `strategy/etf_momentum.py`：项目内策略类。
- `tests/etf_momentum_test.py`：测试用例。

## 总结

当前迁移重点不是“R 包到第三方 Python 数据包”的一一替换，而是将数据接入统一到项目的 miniQMT/xtdata 数据服务。这样独立脚本、Web 应用和后续 QMT 相关能力可以共享同一套本地行情入口。