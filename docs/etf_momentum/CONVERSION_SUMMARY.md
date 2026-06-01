# ETF 动量策略 `R/etf_momentum/etf_momentum.r` 到 Python 转换总结

ETF 动量策略的 Python 版本已完成，并已将行情数据源切换为本项目的 xtdata/miniQMT 本地数据服务。

## 当前状态

- ✅ Python 策略类：`strategy/etf_momentum.py`
- ✅ 独立回测脚本：`examples/etf_momentum/backtest_etf_momentum.py`
- ✅ 单元测试：`tests/etf_momentum_test.py`
- ✅ 策略配置：`config/strategy.yaml`
- ✅ xtdata 数据接入：`utils.xtdata_client.fetch_history_ohlcv`
- ✅ 回测结果输出：`examples/etf_momentum/backtest_results/`

## 主要变化

### 数据源

数据链路为：

```text
miniQMT / xtdata 本地数据服务
  -> utils.xtdata_client.fetch_history_ohlcv()
  -> to_title_case_ohlcv()
  -> Backtrader PandasData
```

默认标的代码也改为 xtdata/miniQMT 代码格式：

```python
ETF_SYMBOLS = ["513100", "510300", "518880"]
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]
```

### 回测框架

Python 版本使用 Backtrader 运行策略、基准和等权组合：

- 动量策略：风险调整动量择优配置。
- 基准策略：沪深 300 ETF 买入持有。
- 等权组合：三只 ETF 等权配置。

### 绩效与输出

保留原 R 版本关注的核心指标，并输出为 CSV 和图片：

- 年化收益率
- 年化波动率
- 夏普比率
- 最大回撤
- 卡尔马比率
- 索提诺比率
- 胜率
- 每日权重
- 每日收益

## R 到 Python 功能映射

| 功能 | R 版本 | 当前 Python 版本 |
| --- | --- | --- |
| 行情数据 | `quantmod` / Yahoo | `utils.xtdata_client` / miniQMT |
| 时间序列处理 | `xts` / `zoo` | `pandas` |
| 数据整理 | `dplyr` / `tidyr` | `pandas` |
| 回测逻辑 | R 自定义 | `backtrader` |
| 绩效分析 | `PerformanceAnalytics` | `PerformanceCalculator` / `empyrical-reloaded` |
| 图表 | `ggplot2` / `cowplot` | `matplotlib` |

## 运行方式

```bash
uv sync
uv run python examples/etf_momentum/backtest_etf_momentum.py
```

Web 应用：

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

测试：

```bash
.venv/Scripts/python.exe -m unittest tests.etf_momentum_test.EtfMomentumTest
```

## 注意事项

- 运行回测前需确保 miniQMT/xtdata 本地数据服务可用。
- ETF 代码使用本地 xtdata 格式，不使用 `.SS` 后缀。
- 数据完整性依赖本机历史数据下载情况。
- 当前回测未单独建模滑点，实盘结果可能低于回测。

## 后续可改进项

- 增加更多 ETF 标的池。
- 增加参数优化与敏感性分析。
- 增加数据可用性检查和更明确的错误提示。
- 调整交易分率、调整交易频次。
- 输出更完整的 HTML/PDF 回测报告。

**最后更新：** 2026-06-01
**状态：** ✅ Python 版本已切换到 xtdata 数据源