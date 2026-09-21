# 数据同步模块发布规划与实现记录

## 目标

将 Big QMT 的沪深京市场行情同步到可选的 DuckDB 和 KDB-X：DuckDB 保存日线，KDB-X 保存日线、分钟线和 tick，
覆盖股票、指数、基金、债券、回购、权证和 ETF。

## 当前实现

最近修复：QMT 服务端的 `get_sector_list` 默认不再返回硬编码板块列表，`list-sectors` 现会显式传入
`allow_fallback=True`，与当前 Big QMT RPC 合约兼容。

同步入口为：

```bash
uv run python -m scripts.duckdb.sync check
uv run python -m scripts.duckdb.sync list-sectors
uv run python -m scripts.duckdb.sync sync --targets duckdb --peroid 1d --start 20160101 --end 20260920 --allow-partial
```

模块职责如下：

```text
QMT RPC
  → universe.py：按 QMT 板块发现并分类标的
  → qmt.py：批量调用 get_market_data_ex
  → fetcher.py：标准化 OHLCV、盘口字段与批次失败记录
  → targets.py：选择 DuckDB/KDB-X 目标
  → DuckDBStore/KdbStore：事务或 keyed upsert
```

文件布局：

- `scripts/duckdb/config.py`：环境变量、数据库路径和同步参数。
- `scripts/duckdb/universe.py`：股票、指数、基金、债券、回购、权证和 ETF 标的发现。
- `qmt.py`：Big QMT RPC 的最小可测试封装。
- `scripts/duckdb/fetcher.py`：批量日线、分钟/tick 拉取、空数据识别和可选历史下载重试。
- `scripts/duckdb/store.py`：建表、事务、幂等写入和运行日志。
- `scripts/targets.py`：目标协议和 `--targets` 参数解析。
- `scripts/kdb/store.py`：KDB-X 连接、schema 初始化和 keyed upsert。
- `scripts/kdb/schema.q`：KDB-X 表结构。
- `scripts/duckdb/schema.sql`：`instrument_master`、`daily_bars`、`trading_calendar`、`sync_runs`、`sync_errors`。
- `scripts/duckdb/universe.yaml`：可按券商/QMT 版本调整的板块名称映射。
- `scripts/kdb/README.md`：KDB-X 分钟/tick 数据目标说明。

## 数据设计

`daily_bars` 使用长表结构，核心字段为：

`symbol、market、asset_type、trade_date、open、high、low、close、volume、amount、dividend_type`。

同一标的、交易日和复权方式重复同步时先删除旧行再写入新行，保证任务可重跑。首期默认保存不复权数据；前复权和后复权通过
`--dividend-type` 分开保存。

同步任务默认支持：

- 首次全量同步：`--start` 指定历史起点；
- 增量同步：`--incremental` 从数据库最新交易日向前重叠若干天；
- QMT 批量请求：`--batch-size` 控制单次代码数量；
- 失败可追踪：失败写入 `sync_errors`，每次任务写入 `sync_runs`；
- 冒烟测试：`--limit N` 和 `--dry-run`；
- QMT 历史数据缺失时：可选 `--download-missing` 调用 `download_history_data2` 后重试。
- 可选目标：`--targets duckdb`、`--targets kdb` 或 `--targets duckdb,kdb`；
- 可选周期：`--period 1d`、`1m`、`5m`、`15m`、`30m`、`60m`、`tick`。

## 运行前提与注意事项

1. `BIGQMT_ACCOUNT_ID`、Big QMT Redis 连接变量必须已经配置，QMT 桥接服务必须运行。
2. 标准 DuckDB 是嵌入式数据库，默认文件为 `data/market.duckdb`，可用 `DUCKDB_PATH` 或 `--duckdb-path` 覆盖。
3. QMT 板块名称可能因券商和版本不同而变化。先运行 `list-sectors`，再修改 `scripts/duckdb/universe.yaml`；生产同步建议不使用 `--allow-partial`。
4. KDB-X 默认连接 `127.0.0.1:5000`；分钟/tick 同步必须选择 `--targets kdb`。

## 后续发布步骤

1. 在实际 QMT 环境确认全部资产类别的板块名称，并更新 `universe.yaml`。
2. 使用 `--targets duckdb --period 1d --limit 5` 完成 DuckDB 冒烟同步。
3. 使用 `--targets kdb --period 1m --limit 5` 完成 KDB-X 冒烟同步。
4. 以不复权日线完成全量初始化，再启用每日 `--incremental` 调度。
5. 对 `sync_errors` 做重试队列和监控，并验证 KDB-X 分钟/tick 补数策略。
