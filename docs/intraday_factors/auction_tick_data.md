# 集合竞价 Tick 日分区

## 输入与输出

日常数据存放在 `/data3/stock_data/stk_open_auction/YYYYMM/YYYYMMDD.csv`。新增 CSV 可由
`AuctionTickRepository` 直接读取。`scripts/refresh_intraday_factors.py` 默认从该目录计算新增日因子，
可用 `--auction-dir` 指定替代目录。日因子仍保存为 Parquet 和元信息 JSON，记录源 CSV 的 SHA-256。
缺少交易日、日期与文件名不一致或同一证券时间戳存在冲突报价时停止处理。

读取原有 19 列。`security_id` 为字符串；日期、时间和成交笔数为整数；价格、成交量、成交额和盘口数量为 float64，部分日期的数量字段确有小数。`md_time` 保留供应商的整数编码，例如 `91500000` 代表 09:15:00.000。字段 `min`、`max` 是当日价格上下限。成交量单位、价格与前收复权口径依供应商原始口径保留。

原始数据可能包含无效报价或仍未成交的行情；例如第一阶段盘口为零时 `last` 可能不是有效虚拟撮合价。此流程不填充、不剔除、不声称逐笔完整或因子可直接使用。计算阶段极值时应独立实施并记录报价质量规则，同时以日线核对正式开盘价；应保留未通过过滤的数据，避免把缺失视为零。

## 历史 Parquet 缓存

`data/tick_auction_parquet/YYYY/MM/YYYYMMDD.parquet` 是旧版逐日整理结果。同名 JSON 保留原始压缩包、包内成员、压缩包 SHA-256、记录行数、时间范围和整理版本。可用 `storage="parquet"` 读取这些分区，用于重现历史结果。

```bash
.venv/bin/python scripts/organize_auction_ticks.py --input-dir /path/to/original-rar-files
.venv/bin/python scripts/catalog_auction_ticks.py
```

整理时检验压缩包成员名、字段、行情日期、数据类型和解压退出码；每日报价完整写入后以原子替换形成输出。重复运行会对已输出文件核对来源 SHA-256、来源成员和 Parquet 行数，符合条件才跳过；早期由本脚本生成的整数数量列会升级为统一的浮点列；已有的不一致文件会报错停止，避免覆盖。意外中断时可能留下 `.partial` 文件或单边输出，需人工检查；脚本不会清理或覆盖这些文件。月份区间可用 `--start-month` 和 `--end-month` 缩小。

目录根部的 `daily_index.parquet` 与 `manifest.json` 汇总日文件，并比较 Tushare 上交所交易日历。日期清单匹配不能证明各证券、各阶段行情完整，也不能证明供应商采样无遗漏。

抽查发现 2026-04-21 的 `bid_size1` 或 `total_volume_trade` 含小数的记录涉及 1,279 只证券（例如 `000014.SZ` 的 `bid_size1=1687.2`）。这反映源文件实际内容，不能据此确认数量单位或数据质量；使用数量字段前应向供应商确认，不应取整。
