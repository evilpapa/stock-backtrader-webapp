# Turtle Trading - Python版本

`TurtleTrading` 是对 `R/turtle_trading/turtle_trading.r` 的 Python 落地版本，分为两部分：

- 应用内策略：`strategy/turtle_trading.py`
- 独立脚本：`examples/turtle_trading/backtest_turtle_trading.py`

## 策略规则

- 入场：突破前 `entry_period` 日高点做多，跌破前 `entry_period` 日低点做空。
- 风险定仓：每次按 `账户权益 * risk_pct / ATR` 计算单位仓位。
- 加仓：价格朝有利方向移动 `0.5N` 时加一单位，最多 `max_units` 个单位。
- 止损：最新一笔建仓价的 `2N` 保护止损。
- 离场：多头跌破前 `exit_period` 日低点，空头突破前 `exit_period` 日高点。

其中 `N` 使用 `ATR(atr_period)` 近似。

## 与 R 版的差异

- R 版是简化海龟脚本，Python 版补齐了经典海龟核心规则。
- Python 版保留双向交易。
- Streamlit 集成版只暴露整数参数；`risk_pct`、`lot_size` 等由类默认值控制。
- 独立脚本支持 `yfinance` 和 `AkShare` 双数据源。

## 在应用中使用

运行：

```bash
uv run streamlit run app.py
```

在策略下拉框中选择 `TurtleTrading`。

可配置参数：

- `entry_period`
- `exit_period`
- `atr_period`
- `max_units`

## 运行独立脚本

`yfinance` 示例：

```bash
uv run python examples/turtle_trading/backtest_turtle_trading.py --symbol SPY --data-source yfinance --lot-size 1
```

`AkShare` 示例：

```bash
uv run python examples/turtle_trading/backtest_turtle_trading.py --symbol 600519 --data-source akshare --lot-size 100
```

输出目录：

- `datas/turtle_trading/backtest_results/equity_curve.csv`
- `datas/turtle_trading/backtest_results/trade_log.csv`
- `datas/turtle_trading/backtest_results/price_with_signals.png`
- `datas/turtle_trading/backtest_results/equity_curve.png`
- `datas/turtle_trading/backtest_results/position_state.png`

## 测试

```bash
uv run python -m unittest tests.turtle_trading_test
```
