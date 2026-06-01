# ETF 动量策略再平衡频率优化

## 背景

ETF 动量策略在低费率下可以通过高频再平衡及时响应趋势变化；但当交易费率较高时，日级别调仓会产生非常大的交易成本。

当前观察到的现象：

- 费率 `COMMISSION = 0.001` 时，策略收益约为 `30%`。
- 费率 `COMMISSION = 0.025` 时，策略收益约为 `-15%`。

这说明策略的毛收益可能仍然存在，但被换手成本吞掉了。

可以粗略理解为：

```text
净收益 = 毛收益 - 换手率 × 交易费率
```

当费率从 `0.001` 提高到 `0.025`，如果仍然每天调仓，累计手续费会快速侵蚀收益。

## 为什么需要调整 rebalance_days

原先日级别调仓的问题是：

1. 20 日动量窗口每天只新增 1 天数据，信号高度重叠。
2. 权重每天小幅变化，但每次交易都会产生真实成本。
3. 高费率下，小幅调仓贡献的收益不足以覆盖手续费。
4. 趋势类策略通常不需要每天追踪微小权重变化。

提高 `rebalance_days` 的目标是：

- 减少交易次数。
- 降低总换手率。
- 过滤短期噪声。
- 用少量信号滞后换取显著交易成本下降。

## 建议测试区间

建议先针对 `COMMISSION = 0.025` 测试以下再平衡频率：

| `rebalance_days` | 含义 | 建议 |
| ---: | --- | --- |
| 1 | 每日调仓 | 作为对照组，高费率下通常不推荐 |
| 3 | 每 3 个交易日 | 仍偏高频，可观察成本下降幅度 |
| 5 | 约每周调仓 | 第一个重点测试档 |
| 10 | 约双周调仓 | 高费率下值得重点测试 |
| 15 | 约三周调仓 | 介于双周和月度之间 |
| 20 | 约月度调仓 | 推荐主候选 |
| 30 | 约 1.5 个月调仓 | 低换手候选 |
| 40 | 约双月调仓 | 用于检查更低频是否更优 |
| 60 | 约季度调仓 | 低频边界测试 |

如果只能先选一个参数，建议从：

```python
REBALANCE_DAYS = 20
```

开始，也就是约每月调仓一次。

## 与 momentum_window 的关系

当前默认动量窗口为：

```python
MOMENTUM_WINDOW = 20
```

如果每天调仓，相当于每天用高度重叠的 20 日窗口反复交易，信号变化通常不大，但手续费持续发生。

建议搭配：

| `momentum_window` | 推荐 `rebalance_days` |
| ---: | --- |
| 20 | 5 / 10 / 20 / 30 |
| 40 | 10 / 20 / 40 |
| 60 | 20 / 30 / 60 |

对于当前策略，优先测试：

```python
MOMENTUM_WINDOW = 20
REBALANCE_DAYS = 10
REBALANCE_DAYS = 20
REBALANCE_DAYS = 30
```

## 进一步降低交易成本：最小调仓阈值

除了调大 `rebalance_days`，还可以通过最小调仓阈值减少小额交易。

当前策略中已有类似逻辑：

```python
threshold = total_value * 0.01
```

含义是：当某个 ETF 的目标持仓价值与当前持仓价值差异超过账户总资产的 1% 时，才执行交易。

在 `COMMISSION = 0.025` 这种高费率下，1% 阈值可能偏低。后续可以测试：

```python
threshold = total_value * 0.03
threshold = total_value * 0.05
threshold = total_value * 0.10
```

也就是目标权重变化至少达到 3%、5%、10% 时才交易。

## 推荐参数组合

### 保守方案：优先减少交易成本

```python
MOMENTUM_WINDOW = 20
REBALANCE_DAYS = 20
min_trade_threshold = 0.05
```

特点：

- 约月度调仓。
- 小于 5% 的资产变化不交易。
- 交易次数明显下降。
- 更适合高费率环境。

### 稍积极方案：兼顾趋势响应

```python
MOMENTUM_WINDOW = 20
REBALANCE_DAYS = 10
min_trade_threshold = 0.05
```

特点：

- 约双周调仓。
- 比月度更灵敏。
- 交易成本仍明显低于每日调仓。

### 更低频方案：适合极高费率

```python
MOMENTUM_WINDOW = 40
REBALANCE_DAYS = 20
min_trade_threshold = 0.05
```

特点：

- 信号更平滑。
- 调仓更少。
- 对短期噪声不敏感。

## 建议的参数扫描

建议不要只凭直觉选择单一参数，而是做网格测试：

```python
commission = 0.025
momentum_window = 20
rebalance_days_list = [1, 3, 5, 10, 15, 20, 30, 40, 60]
threshold_list = [0.01, 0.03, 0.05]
```

重点观察：

- 年化收益率
- 最大回撤
- 夏普比率
- 总交易次数
- 总换手率
- 手续费总额
- 期末净值

最终选择标准不应只看收益最高，而应选择：

```text
收益明显改善 + 回撤可接受 + 交易次数显著下降 + 参数不过度敏感
```

## 当前代码调整

独立回测脚本已支持：

```python
REBALANCE_DAYS = 20
```

并在添加策略时传入：

```python
cerebro.addstrategy(
    EtfMomentumStrategy,
    momentum_window=MOMENTUM_WINDOW,
    rebalance_days=REBALANCE_DAYS,
)
```

策略内部根据 `rebalance_days` 控制再平衡：

```python
self.rebalance_counter += 1
if self.rebalance_counter < self.params.rebalance_days:
    return

self.rebalance_counter = 0
```

`config/strategy.yaml` 中 `EtfMomentum.rebalance_days` 的 UI 范围也已扩展到 `1 ~ 60`，方便在 Streamlit 中测试低频调仓。

## 初始建议

在当前 `COMMISSION = 0.025` 的情况下，建议第一轮测试从以下组合开始：

```python
MOMENTUM_WINDOW = 20
REBALANCE_DAYS = 20
```

如果收益仍然被手续费明显侵蚀，再测试：

```python
REBALANCE_DAYS = 30
REBALANCE_DAYS = 40
REBALANCE_DAYS = 60
```

如果收益改善但回撤或趋势滞后明显，再回到：

```python
REBALANCE_DAYS = 10
REBALANCE_DAYS = 15
```
