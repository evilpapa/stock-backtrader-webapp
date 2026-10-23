# 统一风控层（Risk Control）

本文说明项目中的风控设计、实现位置、参数含义、接入方式与实测效果。

## 1. 设计目标

项目原有风控分散在各策略内部：海龟策略自带 `2N` 止损与 `risk_pct` 定仓，
小市值策略自带市场门控，其余轮动策略（ETF 动量、龙头/行业轮动、神秘螺旋）
没有任何回撤保护。本次实现把这些能力收敛为一层**与策略逻辑正交**的风控层：

- **可复用**：所有 Backtrader 策略继承 `BaseStrategy` 即自动获得风控，不需要改策略代码。
- **可组合**：组合级、仓位级、标的级三类规则独立开关，关闭时零开销、行为与改造前完全一致。
- **可解释**：每条规则触发都会写入结构化事件（日期、规则、标的、动作、说明），
  可导出 `risk_events.csv` 审计，并汇总为 `risk_summary.csv`。
- **可测试**：规则引擎不导入 Backtrader，纯状态机实现，单元测试覆盖全部分支。

## 2. 代码结构

| 文件 | 职责 |
| --- | --- |
| `src/risk/config.py` | `RiskConfig` 参数模型（构造即校验）、内置预设、`load_preset` |
| `src/risk/manager.py` | `RiskManager` 规则引擎：`evaluate()` 产出当日指令，`clamp_weights()` 裁剪目标权重，`summary()` 汇总统计 |
| `src/risk/mixin.py` | `RiskControlMixin`：在子类定义时包装 `next` / `next_open`，把指令落地为订单 |
| `src/risk/report.py` | 事件表 / 统计表 / 单行摘要的格式化 |
| `src/risk/cli.py` | 示例脚本统一的 `--risk-*` 命令行参数 |
| `src/frames/risk.py` | Streamlit 侧边栏风控面板 |
| `tests/risk_control_test.py` | 规则、混入、回测流水线的测试（24 例） |

`src/strategy/_base.py` 中 `BaseStrategy` 改为继承 `RiskControlMixin`，并新增
`risk_config` 参数（缺省 `None`，即关闭）。

## 3. 规则矩阵

规则按下列顺序在**每个交易日、策略逻辑之前**评估，前一条命中后不再执行后续清仓类规则：

| 层级 | 规则 | 参数 | 触发条件 | 动作 |
| --- | --- | --- | --- | --- |
| 组合 | 回撤熔断 | `max_drawdown`、`drawdown_cooldown_days` | 权益相对历史峰值回撤 ≥ 阈值 | 全部平仓，冷却期内禁止开仓，默认以当前权益重置峰值 |
| 组合 | 单日亏损限制 | `daily_loss_limit` | 当日权益跌幅 ≥ 阈值 | 当日禁止开新仓（已有持仓不动） |
| 组合 | 波动率目标 | `target_volatility`、`volatility_window`、`min_vol_scale` | 实现年化波动率 ≠ 目标 | 目标权重乘以 `clamp(target/realized, min_vol_scale, 1)`，只降不升 |
| 仓位 | 总仓位上限 | `max_gross_exposure` | Σ\|w\| > 上限 | 按比例压缩目标权重 |
| 仓位 | 单标的上限 | `max_asset_weight` | 单标的权重 > 上限 | 截断该标的权重，不重新分配 |
| 标的 | 固定止损 | `stop_loss` | 价格相对持仓成本下跌 ≥ 阈值 | 平掉该标的，进入 `asset_cooldown_days` 回补冷静期 |
| 标的 | 移动止损 | `trailing_stop` | 价格相对持仓期最高价（空头为最低价）回撤 ≥ 阈值 | 同上 |
| 标的 | 止盈 | `take_profit` | 价格相对成本上涨 ≥ 阈值 | 平掉该标的 |

补充约定：

- 空头持仓的止损/止盈方向自动反向（按持仓数量正负判断）。
- 止损当根 K 线不再执行策略调仓，避免"平仓 + 回补"在同一根 K 线对冲。
- 冷静期内该标的的目标权重会被清零，同时 `buy()` 调用被拦截并计数
  （`risk_summary()["blocked_buy_count"]`）。
- 熔断冷却期结束后允许重新建仓；因此熔断只降低单次回撤，不保证全程空仓。
- 单一风控事件在同期只记录一次（波动率缩放系数变化 ≥ 5% 才留痕），避免日志被刷屏。

## 4. 参数与预设

`RiskConfig` 全部字段（比例均为小数，`0` 表示关闭）：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `False` | 总开关；关闭时策略行为与改造前完全一致 |
| `max_drawdown` | `0.25` | 组合回撤熔断阈值 |
| `drawdown_cooldown_days` | `10` | 熔断后禁止开仓的交易日数 |
| `reset_peak_after_halt` | `True` | 熔断后是否以当前权益重置峰值 |
| `daily_loss_limit` | `0.0` | 单日亏损禁开仓阈值 |
| `target_volatility` | `0.0` | 年化目标波动率 |
| `volatility_window` | `20` | 波动率估计窗口（≥ 2） |
| `min_vol_scale` | `0.2` | 仓位系数下限 |
| `max_gross_exposure` | `1.0` | 组合总仓位上限（不可为 0） |
| `max_asset_weight` | `1.0` | 单一标的最大权重（不可为 0） |
| `stop_loss` | `0.0` | 固定止损 |
| `trailing_stop` | `0.0` | 移动止损 |
| `take_profit` | `0.0` | 止盈 |
| `asset_cooldown_days` | `5` | 止损/止盈后禁止回补的交易日数 |

内置预设 `RISK_PRESETS`（`none` / `conservative` / `balanced` / `aggressive`）：

| 参数 | conservative | balanced | aggressive |
| --- | --- | --- | --- |
| 回撤熔断 | 15% | 20% | 30% |
| 熔断冷却 | 15 日 | 10 日 | 5 日 |
| 单日亏损限制 | 3% | 5% | 关闭 |
| 目标波动率 | 15% | 20% | 关闭 |
| 总仓位上限 | 95% | 100% | 100% |
| 单标的上限 | 35% | 50% | 100% |
| 固定止损 | 8% | 12% | 18% |
| 移动止损 | 12% | 18% | 25% |
| 回补冷静期 | 10 日 | 5 日 | 3 日 |

## 5. 接入方式

### 5.1 策略侧：自动生效

```python
from src.risk import load_preset
from src.strategy import EtfMomentumStrategy

cerebro.addstrategy(EtfMomentumStrategy, risk_config=load_preset("balanced"))
```

`RiskControlMixin` 在类定义时包装子类的 `next` / `next_open`（每个钩子只包装一次），
因此**不要**再在策略里手写止损/熔断逻辑，也不要覆盖包装后的方法。cheat-on-open
策略（如 `MysteriousSpiralStrategy`）在 `next_open` 阶段使用开盘价评估，避免引用当日收盘价。

轮动类策略（`RotationStrategyBase`、`EtfMomentumStrategy`、`QbEtfMomentumStrategy`、
`SmallCapStrategy`、`MysteriousSpiralStrategy`）已在计算目标权重后调用
`self.apply_risk_weights(...)`，因此波动率目标、总仓位与单标的上限对这些策略直接生效。
自定义策略只需在生成目标权重后加一行：

```python
weights = self.apply_risk_weights(weights)   # 风控关闭时原样返回
# 或者数组形式：weights = self.apply_risk_weights_to_array(weights)
```

### 5.2 示例脚本

```bash
# 预设
uv run python examples/etf_momentum.py --data-source cache --dividend-type none --risk-preset balanced
# 预设 + 单项覆盖（只给覆盖项时自动启用风控）
uv run python examples/etf_momentum.py --data-source cache --dividend-type none \
    --risk-max-drawdown 0.15 --risk-stop-loss 0.08 --risk-asset-cooldown 10
# 轮动示例同样支持
uv run python examples/sector_rotation.py --risk-preset conservative
```

### 5.3 Streamlit 页面

ETF Momentum / QB ETF Momentum / Leading Rotation / Sector Rotation 页面侧边栏提供
「🛡️ 风控」面板：启用开关、预设选择，以及对回撤熔断、冷却天数、固定止损、
移动止损、单标的上限、目标波动率的覆盖。勾选启用后重跑回测，结果区会多出
「风控统计」「风控事件」两个标签页。

### 5.4 输出文件

启用风控后，结果目录额外生成：

- `risk_events.csv`：`日期 / 规则 / 标的 / 动作 / 说明`
- `risk_summary.csv`：`指标 / 数值`，含生效规则、各规则触发次数、禁开仓天数、观测最大回撤等

控制台同时打印一行摘要与统计表。

## 6. 实测效果

命令（本地 QMT 日线缓存，`none` 口径，2025-01-02 ~ 2026-09-23，421 个交易日，
ETF 池：纳指ETF / 沪深300ETF / 黄金ETF / 科技ETF华宝）：

```bash
uv run python examples/etf_momentum.py --data-source cache --dividend-type none --start 2025-01-01
uv run python examples/etf_momentum.py --data-source cache --dividend-type none --start 2025-01-01 --risk-preset balanced
```

| 指标 | 无风控 | balanced |
| --- | --- | --- |
| 年化收益率 | 2.48% | 8.41% |
| 年化波动率 | 19.51% | 17.41% |
| 夏普比率 | 0.228 | 0.553 |
| 最大回撤 | -17.87% | -17.69% |
| 卡尔马比率 | 0.139 | 0.476 |

`balanced` 一共触发 37 条事件：波动率缩放 18 次、移动止损 14 次、固定止损 2 次、
单日亏损禁开仓 3 天；回撤未触及 20% 熔断线，因此熔断次数为 0。
收益提升主要来自高波动阶段自动降仓（实现波动率一度达 49.9%，仓位压到 0.40），
最大回撤基本持平——风控在这里主要改善的是风险调整后收益，而不是绝对回撤。

> 这是单一样本路径的结果，只用于验证机制有效性，不构成对参数优劣的结论。

### 数据口径注意

`data/etf.duckdb` 保存的是 `none`（不复权）口径，除权日会出现价格断层
（例：515000 在 2025-09-07 由 1.835 直接跳到 0.908）。这种断层会被风控当成真实暴跌，
从而错误触发止损/熔断。**做风控回测请使用 `front` / `back` 复权口径**（Tushare 或 QMT 源），
`none` 口径只适合验证代码路径。

## 7. 已知限制

- 单标页面（`app.py` 的 MA / MA Cross 参数扫描）走 `cerebro.optstrategy`，暂未暴露风控参数；
  需要时可在 `src/utils/processing.py` 的 `run_backtrader` 里同样注入 `risk_config`。
- 海龟策略自带 `2N` 止损与 `risk_pct` 定仓，风险层只补充组合级规则（熔断、单日亏损、
  波动率目标）；不叠加单标的止损，避免两套止损互相打架。
- 使用 `order_target_percent` 的策略（神秘螺旋）不能通过拦截 `buy()` 阻止加仓，
  因此其回补控制依赖目标权重裁剪（已接入）。
- 熔断是"事后止损"而非预测：触发点取决于日线收盘价，实际滑点与 A 股跌停无法成交的
  情况未在回测中建模。
- 波动率目标只降不升（系数上限 1.0），不引入杠杆。

## 8. 扩展新规则

1. 在 `src/risk/config.py` 增加字段与校验（`__post_init__`）。
2. 在 `src/risk/manager.py` 的 `RiskDecision` / `evaluate()` 中加入判定，事件用
   `RiskEvent(rule=..., action=...)` 记录，并补充 `RULE_LABELS` / `ACTION_LABELS`。
3. 若规则作用在仓位上，在 `clamp_weights()` 中落地；若需要下单，由
   `src/risk/mixin.py` 的 `_risk_before_bar()` 执行。
4. 在 `tests/risk_control_test.py` 增加对应单元测试，并在本文第 3 节补一行。

## 9. 测试

```bash
uv run python -m pytest tests/risk_control_test.py -q        # 24 passed
uv run python -m pytest -q                                   # 全量回归
```
