# ETF动量轮动策略 - Python版本

这是原始R语言策略（`R/etf_memountum/etf_momentum.r`）的Python完整实现。

## 📋 R包到Python包的映射

| R包 | Python包 | 用途 |
|-----|---------|------|
| `quantmod` | `yfinance` | 金融数据获取 |
| `PerformanceAnalytics` | `empyrical` + 自定义计算 | 投资组合绩效分析 |
| `dplyr`, `tidyr` | `pandas` | 数据处理和整理 |
| `ggplot2`, `cowplot`, `patchwork` | `matplotlib` | 数据可视化和图形组合 |
| `scales` | `matplotlib.ticker` | 图形标度调整 |

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装新增的Python包
pip install yfinance empyrical matplotlib

# 或者安装所有依赖
pip install -r requirements.txt
```

### 2. 运行独立回测脚本

这个脚本完全复制了R版本的功能，包括数据获取、回测、性能分析和可视化：

```bash
python strategy/etf_momentum/backtest_etf_momentum.py
```

**输出结果：**
- `datas/etf_momentum/backtest_results/` 目录包含：
  - `performance_metrics.csv` - 性能指标汇总
  - `daily_weights.csv` - 每日权重分配
  - `daily_returns.csv` - 每日收益率
  - `momentum_vs_benchmark.png` - 与基准对比图
  - `momentum_vs_equal_weight.png` - 与等权重组合对比图
  - `daily_weights_plot.png` - 权重分配图

### 3. 在Streamlit应用中使用

该策略已集成到主应用中，可以通过Streamlit界面使用：

```bash
streamlit run app.py
```

然后在界面中选择 "EtfMomentum" 策略。

### 4. 运行单元测试

```bash
python -m unittest tests.etf_momentum_test.EtfMomentumTest
```

## 📊 策略说明

### 策略逻辑

1. **计算动量指标**
   - 对每个ETF计算过去N天（默认20天）的平均日收益率作为动量值
   - 计算过去N天的收益率标准差作为波动率

2. **风险调整动量**
   - 调整动量 = 动量 / 波动率
   - 这个指标类似于短期夏普比率，衡量单位风险带来的收益

3. **筛选和权重分配**
   - 只选择风险调整动量 > 0 的ETF
   - 按风险调整动量大小归一化分配权重
   - 风险调整动量越高，权重越大

4. **再平衡**
   - 根据设定的频率（默认每日）重新计算权重并调整持仓

### 参数配置

| 参数 | 默认值 | 说明 |
|-----|-------|------|
| `momentum_window` | 20 | 动量计算窗口（天） |
| `rebalance_days` | 1 | 再平衡频率（天） |

## 📈 回测配置

在 `examples/etf_momentum/backtest_etf_momentum.py` 中可以修改以下配置：

```python
# 回测时间段
BACKTEST_START = "2024-01-01"
BACKTEST_END = datetime.now().strftime("%Y-%m-%d")

# ETF代码 (Yahoo Finance格式)
ETF_SYMBOLS = ["513100.SS", "510300.SS", "518880.SS"]
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]

# 策略参数
MOMENTUM_WINDOW = 20
INITIAL_CASH = 100000.0
COMMISSION = 0.001  # 0.1%手续费
```

## 🎯 策略特点

### 优势

1. **风险调整** - 不仅考虑收益率，还考虑波动性
2. **动态配置** - 根据市场情况自动调整权重
3. **多资产分散** - 跨市场、跨资产类别配置
4. **避险能力** - 在市场下跌时可能转向黄金等避险资产

### 适用场景

- 多ETF资产配置
- 动量轮动策略
- 风险平价策略
- 多市场分散投资

## 📝 代码结构

```
docs/etf_momentum/
├── README_PYTHON.md              # 本文档
├── RESEARCH.md                   # 策略实现详细说明文档
└── README.md                     # 原始策略说明
examples/etf_momentum/
└── backtest_etf_momentum.py      # 独立回测脚本（完整功能）
R/etf_momentum/
└── etf_momentum.r                 # 原始R语言策略
strategy/
├── etf_momentum.py              # 策略类（用于Backtrader集成）
tests/
└── etf_momentum_test.py         # 单元测试
config/
└── strategy.yaml                # 策略参数配置（已更新）
```

## 🔧 技术细节

### 关键实现差异

| 方面 | R版本 | Python版本 |
|-----|------|-----------|
| 数据获取 | `getSymbols()` from quantmod | `yf.download()` from yfinance |
| 动量计算 | `rollapply()` | `bt.indicators.SimpleMovingAverage()` |
| 波动率计算 | `rollapply(FUN=var)` | `bt.indicators.StandardDeviation()` |
| 性能指标 | `table.AnnualizedReturns()` | `empyrical` 或自定义函数 |
| 可视化 | `ggplot2` + `cowplot` | `matplotlib` |
| 回测引擎 | 自定义实现 | `backtrader` |

### 数据格式

Python版本使用Backtrader框架，需要以下数据列：
- `Open`, `High`, `Low`, `Close`, `Volume`

## ⚠️ 注意事项

1. **数据源** - Yahoo Finance数据可能存在延迟或缺失，建议在实盘前验证数据质量
2. **手续费** - 默认手续费0.1%，实际交易时请根据券商费率调整
3. **滑点** - 策略未考虑滑点，实盘收益可能低于回测
4. **再平衡成本** - 频繁再平衡会增加交易成本，可适当调整`rebalance_days`参数

## 📚 进一步学习

- [Backtrader文档](https://www.backtrader.com/docu/)
- [yfinance文档](https://pypi.org/project/yfinance/)
- [empyrical文档](https://github.com/quantopian/empyrical)
- [动量策略研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=299107)

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个策略！

## 📄 许可证

与主项目保持一致
