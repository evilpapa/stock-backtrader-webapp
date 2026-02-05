# R语言到Python包映射详细对比

本文档详细说明了从R语言策略转换到Python时的包依赖映射关系。

## 📦 完整包映射表

| #  | R包                   | R版本   | Python包             | Python版本 | 功能说明   | 迁移难度    |
|----|----------------------|-------|---------------------|----------|--------|---------|
| 1  | quantmod             | ~0.4  | yfinance            | >=0.2.0  | 金融数据获取 | ⭐⭐ 简单   |
| 2  | PerformanceAnalytics | ~2.0  | empyrical-reloaded           | >=0.5.5  | 绩效分析   | ⭐⭐⭐ 中等  |
| 3  | ggplot2              | ~3.4  | matplotlib          | >=3.8.0  | 基础绘图   | ⭐⭐⭐⭐ 较难 |
| 4  | dplyr                | ~1.1  | pandas              | >=2.0.0  | 数据处理   | ⭐⭐ 简单   |
| 5  | tidyr                | ~1.3  | pandas              | >=2.0.0  | 数据整理   | ⭐⭐ 简单   |
| 6  | scales               | ~1.2  | matplotlib.ticker   | -        | 标度调整   | ⭐⭐⭐ 中等  |
| 7  | patchwork            | ~1.1  | matplotlib.gridspec | -        | 图形组合   | ⭐⭐⭐ 中等  |
| 8  | cowplot              | ~1.1  | matplotlib.pyplot   | -        | 图形组合   | ⭐⭐⭐ 中等  |
| 9  | xts                  | ~0.13 | pandas              | >=2.0.0  | 时间序列   | ⭐⭐ 简单   |
| 10 | zoo                  | ~1.8  | pandas              | >=2.0.0  | 时间序列   | ⭐⭐ 简单   |

## 🔍 详细功能对比

### 1. 数据获取：quantmod → yfinance

#### R (quantmod)
```r
library(quantmod)
getSymbols("513100.SS", from="2024-01-01", to="2024-12-31", src="yahoo")
prices <- Ad(get("513100.SS"))  # 获取调整后收盘价
```

#### Python (yfinance)
```python
import yfinance as yf
data = yf.download("513100.SS", start="2024-01-01", end="2024-12-31")
prices = data['Adj Close']  # 获取调整后收盘价
```

**迁移要点：**
- yfinance API更简洁
- 返回DataFrame格式，与pandas无缝集成
- 支持批量下载：`yf.download(["SPY", "QQQ"], ...)`

---

### 2. 绩效分析：PerformanceAnalytics → empyrical-reloaded

#### R (PerformanceAnalytics)
```r
library(PerformanceAnalytics)

# 计算年化收益率
ann_return <- Return.annualized(returns)

# 计算夏普比率
sharpe <- SharpeRatio.annualized(returns)

# 计算最大回撤
max_dd <- maxDrawdown(returns)

# 综合绩效表格
table.AnnualizedReturns(returns)
```

#### Python (empyrical-reloaded)
```python
import empyrical-reloaded as ep

# 计算年化收益率
ann_return = ep.annual_return(returns)

# 计算夏普比率
sharpe = ep.sharpe_ratio(returns)

# 计算最大回撤
max_dd = ep.max_drawdown(returns)

# 需要手动组合指标
metrics = {
    'Annual Return': ep.annual_return(returns),
    'Annual Volatility': ep.annual_volatility(returns),
    'Sharpe Ratio': ep.sharpe_ratio(returns),
    'Max Drawdown': ep.max_drawdown(returns),
}
```

**迁移要点：**
- empyrical-reloaded 函数更独立，没有综合表格函数
- 需要手动计算和组织结果
- 如果 empyrical-reloaded 未安装，可以手动实现（见 `examples/etf_momentum/backtest_etf_momentum.py` 中的 `PerformanceCalculator` 类）

**自定义实现示例：**
```python
class PerformanceCalculator:
    @staticmethod
    def annualized_return(returns):
        total_return = (1 + returns).prod() - 1
        years = len(returns) / 252.0
        return (1 + total_return) ** (1 / years) - 1
    
    @staticmethod
    def sharpe_ratio(returns, risk_free=0.0):
        excess_returns = returns - risk_free / 252
        return np.sqrt(252) * excess_returns.mean() / excess_returns.std()
```

---

### 3. 数据处理：dplyr/tidyr → pandas

#### R (dplyr/tidyr)
```r
library(dplyr)
library(tidyr)

# 数据过滤和选择
df %>%
  filter(momentum > 0) %>%
  select(date, etf, weight) %>%
  arrange(desc(weight))

# 数据透视
df %>%
  pivot_longer(cols = -Date, names_to = "ETF", values_to = "Weight")

# 分组聚合
df %>%
  group_by(ETF) %>%
  summarize(mean_weight = mean(Weight))
```

#### Python (pandas)
```python
import pandas as pd

# 数据过滤和选择
df_filtered = (df[df['momentum'] > 0]
               .loc[:, ['date', 'etf', 'weight']]
               .sort_values('weight', ascending=False))

# 数据透视
df_long = pd.melt(df, id_vars=['Date'], 
                  var_name='ETF', value_name='Weight')

# 分组聚合
df_grouped = df.groupby('ETF')['Weight'].mean()
```

**迁移要点：**
- pandas语法更接近SQL
- 管道操作可用但不如R优雅
- 方法链式调用是常见模式

---

### 4. 可视化：ggplot2 → matplotlib

#### R (ggplot2 + cowplot)
```r
library(ggplot2)
library(cowplot)

# 累计收益率图
p1 <- ggplot(data, aes(x=Date, y=Returns, color=Strategy)) +
  geom_line(size=1.2) +
  scale_y_continuous(labels=percent_format()) +
  theme_minimal() +
  theme(legend.position=c(0.02, 0.98))

# 回撤面积图
p2 <- ggplot(data, aes(x=Date, y=Drawdown, fill=Strategy)) +
  geom_area(position="identity", alpha=0.3) +
  scale_y_continuous(labels=percent_format())

# 组合图表
plot_grid(p1, p2, ncol=1, align="v", rel_heights=c(1, 0.9))
```

#### Python (matplotlib)
```python
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import matplotlib.dates as mdates

fig = plt.figure(figsize=(12, 8))
gs = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

# 累计收益率图
ax1 = fig.add_subplot(gs[0])
ax1.plot(dates, strategy_returns, label='Strategy', linewidth=2)
ax1.set_ylabel('Cumulative Returns')
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)

# 回撤面积图
ax2 = fig.add_subplot(gs[1])
ax2.fill_between(dates, drawdown, 0, alpha=0.3, label='Drawdown')
ax2.set_xlabel('Date')
ax2.set_ylabel('Drawdown')
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

plt.tight_layout()
plt.show()
```

**迁移要点：**
- matplotlib更底层，需要更多代码
- GridSpec替代patchwork/cowplot的图形组合
- 日期格式化需要使用matplotlib.dates
- 百分比格式需要自定义或使用FuncFormatter

---

### 5. 滚动窗口计算：rollapply → rolling/indicators

#### R
```r
# 滚动平均
momentum <- rollapply(returns, width=20, FUN=mean, align="right", fill=NA)

# 滚动标准差
volatility <- rollapply(returns, width=20, FUN=sd, align="right", fill=NA)
```

#### Python (pandas)
```python
# 滚动平均
momentum = returns.rolling(window=20).mean()

# 滚动标准差
volatility = returns.rolling(window=20).std()
```

#### Python (backtrader indicators)
```python
import backtrader as bt

# 在策略类中
momentum = bt.indicators.SimpleMovingAverage(returns, period=20)
volatility = bt.indicators.StandardDeviation(returns, period=20)
```

**迁移要点：**
- pandas.rolling() 是最直接的替代
- backtrader.indicators 提供了更丰富的技术指标
- 需要注意窗口对齐方式（默认right）

---

### 6. 时间序列：xts/zoo → pandas

#### R (xts)
```r
library(xts)

# 创建时间序列
ts_data <- xts(values, order.by=dates)

# 滞后操作
lagged <- lag(ts_data, 1)

# 合并时间序列
merged <- merge(ts1, ts2, ts3)

# 按日期索引
ts_data["2024-01-01/2024-12-31"]
```

#### Python (pandas)
```python
import pandas as pd

# 创建时间序列
ts_data = pd.Series(values, index=dates)

# 滞后操作
lagged = ts_data.shift(1)

# 合并时间序列
merged = pd.concat([ts1, ts2, ts3], axis=1)

# 按日期索引
ts_data.loc['2024-01-01':'2024-12-31']
```

**迁移要点：**
- pandas.Series/DataFrame 是xts的自然替代
- shift() 替代 lag()
- concat() 或 merge() 替代 merge()
- 日期索引方式类似

---

## 🎯 迁移策略建议

### 优先级1：核心功能（必须实现）
1. ✅ 数据获取（yfinance）
2. ✅ 数据处理（pandas）
3. ✅ 回测引擎（backtrader）
4. ✅ 基本性能指标（自定义或empyrical-reloaded）

### 优先级2：增强功能（建议实现）
1. ✅ 完整性能分析（empyrical-reloaded）
2. ✅ 基础可视化（matplotlib）
3. ✅ 结果导出（pandas.to_csv）

### 优先级3：高级功能（可选实现）
1. ⬜ 交互式图表（plotly）
2. ⬜ Web界面（streamlit）
3. ⬜ 实时监控（websocket）

---

## 🔧 实用工具函数

### R向量化操作 → NumPy
```python
import numpy as np

# R: ifelse(condition, true_val, false_val)
result = np.where(condition, true_val, false_val)

# R: which(condition)
indices = np.where(condition)[0]

# R: sum(x > 0)
count = np.sum(x > 0)
```

### 数据类型转换
```python
# R: as.numeric() → float()
# R: as.character() → str()
# R: as.Date() → pd.to_datetime()
# R: as.data.frame() → pd.DataFrame()
```

---

## 📊 性能对比

| 方面     | R语言             | Python                 |
|--------|-----------------|------------------------|
| 数据获取速度 | ⭐⭐⭐             | ⭐⭐⭐⭐ (yfinance更快)      |
| 数据处理速度 | ⭐⭐⭐⭐ (dplyr)    | ⭐⭐⭐⭐⭐ (pandas + NumPy) |
| 绘图质量   | ⭐⭐⭐⭐⭐ (ggplot2) | ⭐⭐⭐⭐ (matplotlib)      |
| 绘图速度   | ⭐⭐⭐             | ⭐⭐⭐⭐                   |
| 代码简洁性  | ⭐⭐⭐⭐⭐           | ⭐⭐⭐⭐                   |
| 生态系统   | ⭐⭐⭐             | ⭐⭐⭐⭐⭐                  |
| 学习曲线   | ⭐⭐⭐⭐            | ⭐⭐⭐                    |

---

## 📚 学习资源

### Python金融分析
- [Quantopian Lectures](https://github.com/quantopian/research_public)
- [Python for Finance](https://www.oreilly.com/library/view/python-for-finance/9781492024323/)
- [Backtrader Documentation](https://www.backtrader.com/docu/)

### R到Python迁移
- [R vs Python Cheat Sheet](https://www.datacamp.com/cheat-sheet/r-vs-python-for-data-science)
- [Pandas vs dplyr](https://pandas.pydata.org/docs/getting_started/comparison/comparison_with_r.html)

### 包文档
- [yfinance GitHub](https://github.com/ranaroussi/yfinance)
- [empyrical-reloaded GitHub](https://github.com/stefan-jansen/empyrical-reloaded)
- [matplotlib Gallery](https://matplotlib.org/stable/gallery/index.html)

---

## ⚡ 常见陷阱

### 1. 索引从0开始
```python
# R: array[1] 是第一个元素
# Python: array[0] 是第一个元素
```

### 2. 整数除法
```python
# Python 3: 5/2 = 2.5 (浮点除法)
# Python 2: 5/2 = 2 (整数除法)
# 整数除法使用: 5//2 = 2
```

### 3. NA vs NaN
```python
# R: NA
# Python: np.nan 或 pd.NA
# 检查: pd.isna() 而不是 == np.nan
```

### 4. 函数参数
```python
# R: 命名参数默认使用
# Python: 位置参数优先，命名参数需要显式指定
```

---

## 🎓 总结

| 转换难度    | R包                           | Python替代                     | 建议    |
|---------|------------------------------|------------------------------|-------|
| 简单 ⭐⭐   | quantmod, dplyr, tidyr, xts  | yfinance, pandas             | 直接替换  |
| 中等 ⭐⭐⭐  | PerformanceAnalytics, scales | empyrical-reloaded, matplotlib.ticker | 需要适配  |
| 较难 ⭐⭐⭐⭐ | ggplot2, patchwork           | matplotlib                   | 重写可视化 |

**总体评估：** 本项目的R到Python迁移难度为 **中等**，主要挑战在于可视化部分的重写。核心业务逻辑迁移相对简单。
