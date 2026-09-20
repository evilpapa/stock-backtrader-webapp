# KDB-X 分钟级与 tick 数据

本目录实现 KDB-X 数据目标。通过统一入口选择：

```bash
uv run python -m scripts.duckdb.sync sync --targets kdb --period 1m
uv run python -m scripts.duckdb.sync sync --targets kdb --period tick
uv run python -m scripts.duckdb.sync sync --targets duckdb,kdb --period 1d
```

默认连接 `127.0.0.1:5000`，可通过 `KDB_HOST`、`KDB_PORT`、`KDB_USERNAME` 和 `KDB_PASSWORD` 覆盖。

KDB-X 使用 [schema.q](schema.q) 创建两个 keyed table：

- `instrument_master`：与 DuckDB 共用的标的元数据；
- `market_bars`：日线、分钟线和 tick 的统一行情表，主键为 `symbol、period、bar_time、dividend_type`。

首期约定：

- DuckDB 只接收 `1d`；
- KDB-X 接收 `1d`、分钟周期和 `tick`；
- 两个目标可通过 `--targets duckdb,kdb` 同时写入；
- 重复同步通过 keyed table upsert 覆盖相同主键记录。
