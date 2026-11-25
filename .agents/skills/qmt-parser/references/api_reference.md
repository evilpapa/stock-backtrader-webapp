# qmt-parser Python API 参考

包名 `qmt_parser`，常用接口在根模块重导出，`import qmt_parser as qp` 后直接使用。
包源码位置：`/data1/qmt-parser/python/qmt_parser/`。

## 顶层解析函数

| 函数 | 返回 | 说明 |
|------|------|------|
| `parse_ticks_to_structs(path)` | `list[TickData]` | 解析 tick 分笔文件 |
| `parse_ticks_to_dataframe(path)` | `pandas.DataFrame` | 需 pandas |
| `parse_min_to_structs(path)` | `list[MinKlineData]` | 解析 1 分钟线 |
| `parse_min_to_dataframe(path)` | `pandas.DataFrame` | 需 pandas |
| `parse_daily_to_structs(path, start, end)` | `list[DailyKlineData]` | 字符串日期范围 `YYYYMMDD` |
| `parse_daily_file_to_structs(path)` | `list[DailyKlineData]` | 整文件 |
| `parse_daily_to_structs_in_range(path, start, end)` | `list[DailyKlineData]` | `datetime.date` 范围 |
| `parse_daily_to_dataframe(path, start, end)` | `pandas.DataFrame` | 含 preClose/suspendFlag 派生列 |
| `parse_daily_file_to_dataframe(path)` | `pandas.DataFrame` | 整文件 |
| `parse_daily_to_dataframe_in_range(path, start, end)` | `pandas.DataFrame` | date 范围 |

## TickData 字段

`market`（str|None）、`symbol`、`date`、`raw_qmt_timestamp`、`market_phase_status`
（12=集合竞价，其余=连续竞价）、`last_price`、`last_close`、`amount`、`volume`、
`ask_prices`/`ask_vols`/`bid_prices`/`bid_vols`（各 5 档 list）、
`qmt_status_field_1_raw`、`qmt_status_field_2_raw`。

## MinKlineData / DailyKlineData 字段

`timestamp_ms`（北京时间毫秒）、`open`、`high`、`low`、`close`、`volume`、
`amount`、`open_interest`、`pre_close`（分钟线）/ `file_pre_close`（日线文件原值）。

## 财务（finance）

- `qp.FinanceReader.read_file(path)` → `list[FinanceRecord]`，按文件名 type id（7001-7008）自动识别。
- `qp.FileType`：`BalanceSheet`=7001、`Income`=7002、`CashFlow`=7003、`Capital`=7004、
  `HolderCount`=7005、`TopFlowHolder`=7006、`TopHolder`=7007、`Ratios`=7008。
- `FinanceRecord`：`file_type`、`report_date`、`announce_date`（带北京时区 datetime）、`data`。
- `FinanceRecord.column_names()` → 报表类/比率类列名 list；`named_values()` → `[(列名, 数值)]`。
- `data` 载荷类型：
  - `ReportData(columns)` — 7001/7002/7003（156/80/111 列）
  - `CapitalData(total_share, flow_share, restricted, free_float_share)` — 7004
  - `HolderCountData(total/a/b/h/float/other_holders)` — 7005
  - `TopHolderData(holders: list[Shareholder])` — 7006/7007
  - `RatiosData(ratios)` — 7008（41 列）
- `Shareholder`：`name`、`holder_type`、`hold_amount`、`change_reason`、`hold_ratio`、`share_type`、`rank`。

## 分红（dividend）

- `qp.DividendDb(path)` / `db.query(market, code)` → `list[DividendRecord]`；需 `plyvel`。
- `qp.parse_dividend_value(hex_bytes)` → `DividendRecord`（纯函数，无需 plyvel）。
- `DividendRecord`：`ex_dividend_date`、`record_date`、`interest`、`stock_bonus`、`stock_gift`、
  `allot_num`、`allot_price`、`gugai`、`unknown64_raw`、`adjust_factor`、`timestamp_raw`。

## metadata（xtquant 本地资料文件）

- `parse_holiday_file(path)` → `list[int]`（`YYYYMMDD`）
- `parse_industry_file(path)` → `dict[industry, list[code]]`
- `parse_sector_name_file(path)` → `list[str]`
- `parse_sectorlist_dat(path)` → `list[str]`
- `parse_sector_weight_members(path)` → `dict[sector, list[code]]`
- `parse_sector_weight_index(path, index_code)` → `dict[code, weight]`
- `load_*_from_root(root)` 系列：从 datadir 根目录自动发现文件。

## datadir 自动发现

- `qp.QmtDataDir(root)`：`root` 为 datadir 根目录。
- `qp.parse_security_code("000001.SZ")` → `(Market.Sz, "000001")`；也支持 `"SH600000"`。
- 方法：`tick_path/min_path/day_path/finance_path/dividend_db_path`、
  `parse_ticks_to_structs/parse_min_to_structs/parse_daily_*`、
  `read_finance`、`open_dividend_db`、`load_holidays`、`load_sector_names`、
  `load_sectorlist`、`load_sector_weight_members`、`load_sector_weight_index`、`load_industry`。

## 异常

`qp.QmtParseError` 基类；`TickParseError`、`MinParseError`、`DailyParseError`、
`FinanceError`、`DividendError`、`MetadataParseError`、`DataDirError`。

## 时间与数值语义

- Tick 价格字段 ÷1000；日线成交额 ÷100；分钟线成交额不缩放（原值）。
- Tick `raw_qmt_timestamp` 是 QMT 原始值；`DataFrame` 的 `time` 列按市场规则换算为北京时间：
  上海/深圳 `raw - 396300000`（结果 < 86400000 才有效），北京 `(raw % 86400000 + 86400000 - 50400000) % 86400000`。
- 日线 `DataFrame` 的 `preClose` 为库内重算：`suspendFlag = (volume==0 且 amount==0)`，
  停牌日用当日 `close`，否则用上一交易日 `close`。
- 财务数值列的哨兵值 `0x7FEFFFFFFFFFFFFF` → `NaN`。

## 注意事项

- QMT 运行时会锁定部分文件，建议只读打开或先复制到临时目录。
- LevelDB（DividData）同时只能被一个进程加锁访问，QMT 运行时需用备份目录。
- 财务 `7002`/`7003` 记录头部有 8 字节额外前导槽，库内已处理，上层无需关心。
