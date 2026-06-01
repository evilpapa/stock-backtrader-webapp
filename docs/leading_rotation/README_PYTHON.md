# 龙头动量轮动策略 - Python版本

`LeadingRotation` 是 `R/leading_rotation/leading_rotation.r` 的 Python 落地版本，分为两部分：

- 应用内策略：`strategy/leading_rotation.py`
- 独立脚本：`examples/leading_rotation/backtest_leading_rotation.py`

## 策略规则

- 标的池：22 只龙头股票，另加 `588000` 作为科创 50ETF 基准。
- 动量：使用过去 `momentum_window` 日平均收益率。
- 风险调整：用 `动量 / 波动率` 作为排序分数。
- 选股：只保留原始动量大于 0 的股票，再取前 `top_l` 只。
- 权重：按风险调整动量归一化分配。
- 调仓：每 `rebalance_days` 个交易日调仓一次。

## 在应用中使用

运行：

```bash
uv run streamlit run app.py
```

在策略下拉框中选择 `LeadingRotation`。

可配置参数：

- `momentum_window`
- `rebalance_days`
- `top_l`

## 运行独立脚本

```bash
uv run python examples/leading_rotation/backtest_leading_rotation.py
```

脚本默认使用 `xtdata` 下载数据，并在 `examples/leading_rotation/backtest_results` 输出：

- `performance_metrics.csv`
- `daily_weights.csv`
- `daily_returns.csv`
- `cumulative_returns.csv`
- `drawdowns.csv`
- `selection_frequency.csv`
- `rebalance_details.csv`
- `leading_vs_benchmark.png`
- `leading_vs_equal_weight.png`
- `daily_weights_plot.png`

## 测试

```bash
uv run python -m unittest tests.leading_rotation_test
```

## 说明

- Python 版保留了 R 版的核心 N/K/L 思路，对应为 `momentum_window` / `rebalance_days` / `top_l`。
- 回测脚本额外提供了基准买入持有和龙头股等权组合对照。
- 应用内策略只暴露整数参数；基准索引排除和最小调仓阈值使用类默认值。
