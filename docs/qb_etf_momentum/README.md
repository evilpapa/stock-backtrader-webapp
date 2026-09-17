# QB ETF 短周期动量策略

`QbEtfMomentumStrategy` 是对 `qb/etf_mom/etf_mom.py` 的 Backtrader 适配，不替换现有的 `EtfMomentumStrategy`。

## 已迁移逻辑

- 以 `period` 个交易日的收盘价 ROC 对 ETF 排名；
- 在指定星期（`rebalance_weekday`，1 为周一、5 为周五）调仓；
- 等权配置 ROC 前 `top_n` 个 ETF；
- 使用绝对动量门控和防御资产领导力门控控制总仓位；
- 输出每次调仓的候选、ROC、权重与最终仓位到 `rebalance_history`。

## 未迁移依赖

原 qb 策略的 NHNL 风险门控依赖 `runtime_data` CSV、`ind.gates` 以及 qb 的全市场运行时数据。当前项目的 Backtrader 数据流只提供传入标的的 OHLCV，故未迁移该部分；该策略不会读取或产生 NHNL 数据。

同一 qb 快照内的 `Small2Strategy` 依赖全市场股票池、上市状态、ST/停牌/退市、流通市值和成交额等数据接口，无法等价映射到当前单标的/ETF 的 Backtrader 数据流，未纳入本策略。

## 使用

通过 `src/config/strategy.yaml` 中的 `QbEtfMomentum` 参数组调用，或直接在 Backtrader 中添加 `QbEtfMomentumStrategy`。多标的回测时，数据源名称建议使用证券代码（例如 `518880.SH`），以启用防御 ETF 门控识别。
