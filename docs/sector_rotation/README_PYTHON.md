# 行业动量轮动策略 - Python 版本

`SectorRotation` 是 `R/sector_rotation/sector_rotation.r` 的 Python 落地版本，分为两部分：

- 应用内策略：`strategy/sector_rotation.py`
- 独立脚本：`examples/sector_rotation/backtest_sector_rotation.py`

## 策略规则

- 标的池：13 只行业 ETF，其中 `588000` 作为科创 50ETF 基准。
- 动量：使用过去 `momentum_window` 日平均收益率。
- 风险调整：用 `动量 / 波动率` 作为排序分数。
- 选股：只保留原始动量大于 0 的行业 ETF，再取前 `top_l` 只。
- 权重：按风险调整动量归一化分配。
- 调仓：每 `rebalance_days` 个交易日调仓一次。

## 在应用中使用

```bash
uv run streamlit run app.py
```

在策略下拉框中选择 `SectorRotation`。

可配置参数：

- `momentum_window`
- `rebalance_days`
- `top_l`

## 运行独立脚本

```bash
uv run python examples/sector_rotation/backtest_sector_rotation.py
```

输出目录 `datas/sector_rotation/backtest_results` 包含：

- `performance_metrics.csv`
- `daily_returns.csv`
- `cumulative_returns.csv`
- `drawdowns.csv`
- `daily_weights.csv`
- `selection_frequency.csv`
- `rebalance_details.csv`
- `sector_vs_benchmark.png`
- `sector_vs_equal_weight.png`
- `daily_weights_plot.png`

## 测试

```bash
uv run python -m unittest tests.sector_rotation_test
```
