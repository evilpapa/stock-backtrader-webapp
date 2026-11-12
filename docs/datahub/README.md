# DataHub 统一多数据源模块

`src.datahub` 是独立的数据访问层。策略、回测和 Streamlit 业务代码只依赖
`MarketDataService`，不直接导入 `tushare`、`xtquant` 或
`bigqmt_signal_trader`。

## 最小用法

```python
from src.datahub import DataRequest, create_service

service = create_service()
try:
    bars = service.get_daily(
        DataRequest(
            symbols=("000001.SZ", "600000.SH"),
            start="2024-01-01",
            end="2024-12-31",
            frequency="1d",
            adjust="qfq",
        ),
        persist=True,
    )
finally:
    service.close()
```

返回 DataFrame 的行情字段固定为：

`symbol, datetime, open, high, low, close, volume, amount, pre_close,
adj_factor, source, frequency, adjust`。

`datetime` 带 `Asia/Shanghai` 时区，默认语义是 K 线开始时间；结果的
`DataFrame.attrs["timestamp_semantics"]` 会显式记录这个语义，
`DataFrame.attrs["data_version"]` 是由请求口径、数据源和数据内容计算的版本指纹。
无时区的 datetime 和 `YYYYMMDDhhmmss` 字符串按上海本地时间解析；Unix epoch
按 UTC 解析后转换到上海时间。时间语义应针对具体数据源和桥接环境核验。

项目中的回测、同步和研究脚本使用的便捷入口是 `src.utils.datahub_client.DataHubClient`。
它只负责把旧脚本的 `history_ohlcv`、`market_bars` 和专用研究查询转换为
`MarketDataService` 请求；ETF/指数/资金流/热榜等扩展接口也通过 `DataKind` 路由，
不会在业务层调用 `pro.api()` 或导入第三方 SDK。

例如行业轮动所需的指数日线查询为：

```python
from src.utils.datahub_client import DataHubClient

client = DataHubClient()
index_daily = client.query(
    "index_daily",
    ts_code="000300.SH",
    start_date="20240101",
    end_date="20241231",
)
```

## 路由与切换

默认路由在 `src/datahub/config/datahub.yaml`：日线优先 Tushare，分钟/Tick/实时
优先 XtQuant；主源不可用或超时才按顺序尝试备用源。权限错误、参数错误和数据质量
错误不会被静默切换。每次尝试都记录在 `DataRouter.traces`，并包含 request_id、
provider、duration、record_count、status 和 error。

Token 通过环境变量设置：

```bash
export TUSHARE_TOKEN=...
export QMT_PATH=/path/to/userdata_mini
```

XtQuant Adapter 依次尝试 `bigqmt_signal_trader.xtquant_compat.xtdata` 和官方
`xtquant.xtdata`。桥接服务、MiniQmt、市场权限必须由部署环境提供；没有这些环境时，
Mock Provider 和 Tushare/SQLite 离线测试仍可运行。

## 实时订阅

```python
from src.datahub import RealtimeDataService
from src.datahub.factory import ProviderFactory

provider = ProviderFactory.create("xtquant")
realtime = RealtimeDataService(provider)
sub_id = realtime.subscribe_quote(["000001.SZ", "600000.SH"], on_quote)

# 不再需要时
realtime.unsubscribe(sub_id)
realtime.close()
```

服务会按 `(data_kind, symbol)` 共享底层订阅，多个策略订阅同一证券不会重复建立
XtQuant 订阅。断线后调用 `reconnect()` 重建仍有引用的底层订阅。

## 存储和复现

- `SQLiteRepository`：默认无额外驱动，保存 payload、source、version、request_key，适合测试和轻量研究。
- `ParquetRepository`：按 `data_kind/provider/symbol` 分区，要求 `pyarrow` 或 `fastparquet`。
- `MemoryCache`：历史请求缓存 Key 包含数据类型、symbol、时间范围、周期、复权和 Provider 口径；实时数据可设置短 TTL。

Tushare 的日线/复权行情单位按官方接口口径配置为 `vol=手 -> volume=股`
（乘以 100）、`amount=千元 -> amount=人民币元`（乘以 1000）。XtQuant 的单位
保持本地终端原生值，并在 YAML 显式配置为 1；如果券商桥接改变单位，只修改
`units.xtquant`，不要在业务层换算。

当前桥接实测股票 1 分钟线的 `volume` 为手、`amount` 为元，配置
`units.xtquant_minute` 将成交量乘 100 转为股；该设置只作用于分钟线，
其他终端需对照成交额核实并在 YAML 覆盖。更新单位配置后需重启服务以清空进程内缓存。

Tushare 股票历史分钟 `stk_mins` 的 `vol` 和 `amount` 分别为股和元，不沿用
日线的单位换算；`trade_time` 映射为 K 线结束时间。日期参数按时分秒传入，
只给结束日期时包含当日。接口只提供未复权行情，单次返回达到 8000 行时需要
缩短区间重新请求，以免截断；分钟接口的权限和频率限制独立于日线。

财务请求设置 `as_of` 后，Normalizer 会过滤公告日晚于该时间点的数据，避免回测
使用未来信息：

```python
service.get_financial(DataRequest(
    symbols=("000001.SZ",), table="income", as_of="2024-04-01"
))
```

### 全市场按报告期批量财务

不传 `symbols`、在 `options` 中给出 `period` 时，Tushare Adapter 改走
`{table}_vip`（income/cashflow/balancesheet 等）并在 Adapter 内按 3000 行分页；
同时丢弃 `833243!1.BJ` 之类无法映射的脏代码，并把更正记录（`update_flag=1`）排在
原始记录之后，使 Normalizer 去重保留更正口径：

```python
from src.utils.datahub_client import DataHubClient

client = DataHubClient()
cashflow = client.financial_period("cashflow", "20231231", fields=["ts_code", "ann_date", "f_ann_date", "end_date", "n_cashflow_act"])
```

批量结果不做 `as_of` 过滤，回测方需自行按 `f_ann_date` 做 point-in-time 截断
（参考 `src/strategy/free_cash_flow.py`）。

## 测试

```bash
uv run python -m pytest -q tests/datahub_test.py
```

该测试文件只使用 Fake Pro、Fake XtData、Mock Provider 和临时 SQLite，不要求真实
账号。真实 Tushare/QMT 集成测试应另行放到 `tests/integration/`，并通过 CI 标记或
环境变量显式启用。

## 本地集合竞价快照 Repository

`src.datahub.auction_tick_repository.AuctionTickRepository` 只读已整理的本地日分区，
通过 `DataRequest`（单日、`frequency="tick"`、`adjust="none"`）和
`DataKind.TICK` 查询。证券代码和盘口字段保持原始格式，结果记录数据源、
分区版本、源 RAR 哈希和原始价格口径未知；该仓库不注册默认路由，也不替代
常规 XtQuant Tick。版本由源归档哈希、日期和整理版本生成，不是 Parquet
逐字节校验和。


## 本地研究日数据缓存

`ResearchDailyRepository` 只读已有的 Tushare 研究 Parquet 缓存，支持证券基础信息、
单日全市场日线及历史 ST 数据。通过配置了该仓库的 `MarketDataService.get_cached()`
查询，缓存不存在返回 `None`，未配置仓库时报错。日文件必须非空且交易日期一致；
按证券过滤后为空是合法结果。返回数据的 `attrs` 含来源、文件 SHA-256 版本、
频率及复权口径。此接口直接读取仓库结果，不经过 Normalizer 自动转换为标准 bar；
字段和单位保持原缓存口径，调用方须确认其 schema。该仓库不注册默认路由。

`MinuteBatchRepository` 为 XtQuant 和 Tushare 分钟研究提供按完整请求精确匹配的 Parquet 批次缓存，
通过构造参数 `source` 显式绑定来源（默认 XtQuant）。
`MarketDataService.get_cached(DataKind.MINUTE, request, source=...)` 按相同证券顺序、
时间范围和选项读取；缓存元信息记录请求、数据版本及文件 SHA-256，损坏时拒绝读取。
空批次也是一次观测结果，不表示证券停牌或数据永久不可用；重新拉取时使用构建脚本的
`--refresh`。更改批量、证券顺序、日期或选项会生成不同缓存键。

XtQuant 历史行情读取会在 `get_market_data_ex` 显式支持 `subscribe` 参数时传入
`subscribe=False`，避免桥接版本在批量读取时积累常驻订阅。未提供此参数的官方 SDK
保持原有调用签名。历史数据不存在时仍会返回空结果，关闭订阅不会自动下载数据。

本地历史分钟 Parquet 可通过 `LocalMinuteRepository` 的只读 DataHub 请求访问：
支持按日和证券过滤逐年/逐日文件，记录源文件 SHA-256，并显式标注分钟末、
未复权和单位均为待进一步确认的假设。不得将该来源自动混同于 QMT 或 Tushare。
详细目录、验证和局限见 `docs/intraday_factors/README.md`。
