# Small2 小市值策略迁移

`src/strategy/small_cap.py` 将 `qb/small2/small2.py` 迁移为 Backtrader 策略；QMT 查询与策略逻辑分离，策略不会执行网络请求或实盘下单。

## QMT 数据映射

| qb 数据接口         | 当前封装                          | QMT API                               |
|---------------------|-----------------------------------|---------------------------------------|
| A 股股票池          | `QmtUniverseClient.stock_codes()` | `get_stock_list_in_sector("沪深A股")` |
| 名称、上市/退市日期 | `instrument_details()`            | `get_instrument_detail`               |
| ST 状态             | `historical_st_codes()`           | `get_his_st_data`                     |
| 停牌状态            | `snapshot()`                      | 目标日无有效日线，或 `volume <= 0`    |
| 流通股本            | `float_shares()`                  | `get_financial_data(Capital.CAPITAL)` |
| 流通市值            | `snapshot()`                      | 目标收盘价 × 流通股本，单位亿元       |
| OHLCV、成交额       | `daily_bars()`                    | `get_market_data_ex`                  |

合约详情和财务表在不同 QMT 版本可能使用不同字段名。当前实现识别常见的 `OpenDate` / `ExpireDate` 与 `float_share` 等字段；未知或缺失的流通股本会生成 NaN 并在股票池过滤阶段剔除，不会伪造市值。

## 迁移策略逻辑

保留 qb 版本的：

- 新股、ST、停牌、退市、非主板、小/大流通市值过滤；
- 小市值、波动、短期反转、流动性与 K 线形态 (`UBL`) 的组合评分；
- ATR、异常成交额、涨跌停和价格过滤；
- 定期等权调仓及 `avoid_months` 清仓；
- NHNL、相对强弱、涨停数同时恶化时的市场降仓。

市场门控中的 `nhnl`、`limit_up_count` 需要通过 `market_factors` 按日期传入。原 qb 快照使用本地运行时 CSV；本项目不以不完整的 QMT 数据推测 NHNL，因此没有提供隐式计算。

## 回测防前视

使用 `build_small_cap_snapshots()` 在每个调仓日构建 `StockUniverseSnapshot`；将这些快照传给 `run_small_cap_backtest()`。`Small2Strategy` 只会选择当前日期或更早的最近快照，避免使用未来的 ST、上市状态、流通股本和市值。

`prepare_small_cap_price_data()` 需要拉取快照覆盖股票与中证 1000 (`000852.SH`)、沪深 300 (`000300.SH`) 的日线，并保留 QMT 的 `amount` 字段。

## 重要限制

- 全市场每日请求量较大。应将 `build_small_cap_snapshots()` 的产物在本地缓存为 Parquet/CSV，而非对每次页面刷新重抓。
- `get_his_st_data` 逐股票 RPC 成本高；生产使用建议在 QMT 端增加批量 ST 查询白名单后替换该调用。
- 策略仅用于回测研究；没有接入实盘委托路径。
