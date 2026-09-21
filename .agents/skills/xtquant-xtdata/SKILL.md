---
name: xtquant-xtdata
description: Retrieve and use the official XtQuant xtdata documentation from dict.thinktrader.net for questions about xtquant.xtdata market data access, historical downloads, quote subscriptions, local cache reads, financial data, instrument metadata, sector membership, trading calendars, ETF subscription/redemption lists, convertible bond info, and xtdata formula APIs. Use when the user asks about xtdata function signatures, return structures, parameters, field dictionaries, or wants example code aligned with the official docs.
---

# xtquant-xtdata

Use this skill as the authoritative reference for the official XtQuant xtdata market-data manual.

## Primary reference

Read in this order:

1. `references/00-index.md` (entrypoint + function index)
2. The matching split volume:
    - `references/概述.md`
    - `references/1-行情接口.md`
    - `references/2-财务数据接口.md`
    - `references/3-基础行情信息.md`
    - `references/4-附录-行情字段与字典.md`
    - `references/5-附录-财务字段与合约字段.md`

Source:

- https://dict.thinktrader.net/nativeApi/xtdata.html?id=olYCD5

Read this page when the user asks about:

- `xtquant.xtdata` function signatures or parameters
- return structures of行情、财务、板块、基础信息接口
- period、复权、时间范围、字段字典、数据字典
- MiniQmt 数据下载、缓存读取、订阅回调
- VBA/公式模型接口，如 `subscribe_formula`、`call_formula`

Do not use this skill for:

- `xtquant.xttrader` 交易下单接口
- QMT `ContextInfo` 生命周期问题
- 非 `xtdata` 模块的通达信/其他数据源 API

## Core operating model

- `xtdata` 本质上是连接 `MiniQmt` 获取和缓存数据，行情权限、服务器和本地终端保持一致。
- 主动获取接口依赖本地已有数据；如果数据不足，先调用 `download_*` 接口补充，再调用 `get_*` 接口读取。
- 订阅接口通过回调返回实时数据；同类实时数据通常会进入缓存，后续可再通过 `get_*` 获取。
- `level2` 实时数据依赖终端权限，且 level2 函数通常不保留跨交易日历史。
- 单股订阅数量不宜过多；文档建议单股订阅尽量不要超过 50，数量较多时优先考虑全推接口。

## Workflow

1. 先在官方文档中定位精确函数名，按原名回答，不要臆造参数。
2. 明确用户要的是哪一类能力：订阅、主动获取、下载补数、财务、基础信息、板块、日历、模型。
3. 回答时优先说明前置条件：
   - 是否需要先下载数据
   - 是否依赖 `MiniQmt`
   - 是否要求 level2 权限
   - 是否仅支持投研端
4. 返回值说明必须保留原始结构差异，例如：
   - `get_market_data` 的 K 线返回 `dict[field] -> DataFrame`
   - `tick` 返回 `dict[stock] -> np.ndarray`
   - `get_financial_data` 返回 `dict[stock] -> dict[table] -> DataFrame`
5. 如果给代码示例，保持最小可运行，优先展示：
   - 先 `download_*` 再 `get_*`
   - 订阅后传入 `callback`
   - 需要持续接收回调时调用 `run()`
6. 如果文档页面中的表格或字段在抓取后出现排版错乱，要明确说明“字段名以官方页面为准”。

## Common routing

- 历史行情补数 → `download_history_data`, `download_history_data2`
- 主动获取行情 → `get_market_data`, `get_local_data`, `get_full_tick`, `get_full_kline`
- 实时订阅 → `subscribe_quote`, `subscribe_whole_quote`, `unsubscribe_quote`, `run`
- 复权/除权 → `get_divid_factors`, `dividend_type`
- 公式/模型 → `subscribe_formula`, `unsubscribe_formula`, `call_formula`, `call_formula_batch`, `generate_index_data`
- 财务数据 → `get_financial_data`, `download_financial_data`, `download_financial_data2`
- 合约基础信息 → `get_instrument_detail`, `get_instrument_type`
- 交易日/节假日 → `get_trading_dates`, `get_holidays`, `download_holiday_data`, `get_trading_calendar`, `get_trading_time`
- 板块与成分股 → `get_sector_list`, `get_stock_list_in_sector`, `download_sector_data`
- 自定义板块维护 → `create_sector_folder`, `create_sector`, `add_sector`, `remove_stock_from_sector`, `remove_sector`, `reset_sector`
- 指数权重 → `get_index_weight`, `download_index_weight`
- 可转债/ETF/IPO → `download_cb_data`, `get_cb_info`, `download_etf_info`, `get_etf_info`, `get_ipo_info`
- 周期与能力枚举 → `get_period_list`

## Important distinctions

### `get_market_data` vs `get_local_data`

- `get_market_data` 从缓存获取数据，是主动获取行情的主要接口。
- `get_local_data` 直接从本地数据文件读取，适合快速批量读取历史 level1 数据。
- 两者在 K 线和 `tick` 周期下的返回结构相似，但 `get_local_data` 文档注明“仅用于获取 level1 数据”。

### 下载接口 vs 获取接口

- `download_*` 负责把数据补到本地。
- `get_*` 负责从缓存或本地文件读取数据。
- 用户问“为什么拿不到历史数据”时，优先检查是否遗漏下载步骤、时间范围是否过大、权限是否不足。

### 单股订阅 vs 全推订阅

- `subscribe_quote` 适合少量标的。
- `subscribe_whole_quote` 适合较多标的或全市场场景，回调数据类型为分笔数据。
- 若用户要订阅几十只以上股票，优先提醒使用全推方案。

### 普通行情 vs level2

- `tick`, `1m`, `5m`, `1d`, `1w`, `1mon`, `1q`, `1hy`, `1y` 属于常用行情周期。
- `l2quote`, `l2order`, `l2transaction`, `l2quoteaux`, `l2orderqueue` 等 level2 数据依赖权限。
- level2 历史保留能力与 level1 不同，不要默认它能像 K 线一样直接回溯很长历史。

### 模型/公式接口

- `subscribe_formula` 和 `generate_index_data` 需要投研端支持。
- 使用公式接口前，通常也要先准备本地 K 线或分笔数据。
- `call_formula` 返回的是包含 `timelist` 和 `outputs` 的结果字典，不是普通行情表结构。

## Answering rules

- 优先给出文档中的精确函数签名。
- 明确时间参数一般是字符串，常见格式如 `YYYYMMDD` 或 `YYYYMMDDhhmmss`，具体以对应接口说明为准。
- 明确 `stock_code` 格式通常为 `code.market`，例如 `000001.SZ`、`600000.SH`。
- 说明 `period` 时，优先使用文档原始枚举值，不要自行翻译为其他别名。
- 当用户问字段含义时，优先引用文档附录中的字段字典和数据字典。
- 当用户问财务表字段、证券状态、成交标志、现金替代标志等枚举时，提醒“以官方附录枚举为准”。
- 不把 `xtdata` 的文档问题扩展成真实交易执行建议。

## Minimal example patterns

### 下载后读取 K 线

```python
from xtquant import xtdata

xtdata.download_history_data('000001.SZ', '1d', '20240101', '20241231')
data = xtdata.get_market_data(
    field_list=['open', 'high', 'low', 'close', 'volume'],
    stock_list=['000001.SZ'],
    period='1d',
    start_time='20240101',
    end_time='20241231',
    count=-1,
    dividend_type='none',
)
```

### 订阅单股行情

```python
from xtquant import xtdata

def on_data(datas):
    print(datas)

seq = xtdata.subscribe_quote('000001.SZ', period='tick', count=0, callback=on_data)
xtdata.run()
```

### 获取财务数据

```python
from xtquant import xtdata

xtdata.download_financial_data(['000001.SZ'], ['Income', 'Balance'])
data = xtdata.get_financial_data(
    ['000001.SZ'],
    table_list=['Income', 'Balance'],
    start_time='20230101',
    end_time='20241231',
    report_type='report_time',
)
```

## When to be cautious

- 用户要求“最新数据但没返回”时，检查 `MiniQmt` 是否在线、是否已连接正确端口、是否已有权限。
- 用户要求“未来交易日”时，优先看 `get_trading_calendar`，并提醒可能需要先下载节假日数据。
- 用户要求“全部字段”时，`get_instrument_detail(stock_code, iscomplete=True)` 才会返回更完整的合约字段。
- 用户要求 ETF 申赎清单、可转债信息、指数权重等专题数据时，先确认是否需要先执行对应 `download_*`。
- 用户问 `get_trade_times` 时，提醒文档已说明后续使用 `get_trading_time`。
