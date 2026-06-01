# ETF 动量轮动策略 - Python 版本

Python 版本已使用本项目的 `xtdata` 客户端获取本机 miniQMT 历史行情。

## 快速开始

```bash
uv sync
uv run python examples/etf_momentum/backtest_etf_momentum.py
```

如需在 Web 应用中运行：

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

然后在界面中选择 `EtfMomentum` 策略。

## 数据源

- 数据来自 `utils.xtdata_client.fetch_history_ohlcv`。
- 脚本通过 `to_title_case_ohlcv()` 转换为 Backtrader 需要的 `Open/High/Low/Close/Volume` 列。
- 运行前需确保本机 miniQMT/xtdata 数据服务可用，且对应 ETF 历史数据已能读取。

默认标的位于 `examples/etf_momentum/backtest_etf_momentum.py`：

```python
ETF_SYMBOLS = ["513100", "510300", "518880"]  # 纳指、沪深300、黄金
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]
```

## 策略逻辑

1. 对每只 ETF 计算过去 `momentum_window` 天的日收益率均值作为动量。
2. 计算同窗口收益率标准差作为波动率。
3. 使用 `动量 / 波动率` 得到风险调整动量。
4. 只持有风险调整动量为正的 ETF，并按风险调整动量归一化分配权重。
5. 默认每日重新计算权重并调仓。

## 主要参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `MOMENTUM_WINDOW` | 20 | 动量与波动率计算窗口 |
| `INITIAL_CASH` | 100000.0 | 初始资金 |
| `COMMISSION` | 0.025 | 手续费率，定义在 `examples/backtest_constants.py` |

## 输出结果

脚本输出到 `examples/etf_momentum/backtest_results/`：

- `performance_metrics.csv`：绩效指标汇总
- `daily_weights.csv`：每日权重分配
- `daily_returns.csv`：每日收益率
- `momentum_vs_benchmark.png`：策略与沪深 300 ETF 对比
- `momentum_vs_equal_weight.png`：策略与等权组合对比
- `daily_weights_plot.png`：权重分配图

## 相关文件

- `examples/etf_momentum/backtest_etf_momentum.py`：独立回测脚本。
- `strategy/etf_momentum.py`：集成到 Backtrader/Streamlit 的策略类。
- `utils/xtdata_client.py`：miniQMT xtdata 客户端。
- `tests/etf_momentum_test.py`：单元测试。
- `config/strategy.yaml`：策略参数 UI 配置。

## 注意事项

- ETF 代码使用 xtdata/miniQMT 可识别的本地代码格式，例如 `510300`。
- xtdata 读取的是本机 miniQMT 数据服务，数据完整性取决于本地数据下载与服务状态。
- 当前回测未单独建模滑点；实盘收益可能低于回测。