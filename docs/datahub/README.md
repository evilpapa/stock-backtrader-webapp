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
