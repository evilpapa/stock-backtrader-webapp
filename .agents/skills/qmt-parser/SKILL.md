---
name: qmt-parser
description: 直接解析 MiniQMT / QMT 本地数据目录下的二进制 .dat 文件与本地元数据，无需 QMT 客户端 API。涵盖 tick 分笔、1分钟K线、日线、财务 .DAT（7001-7008）、分红送配 LevelDB、xtquant 资料文件（节假日/板块/行业），以及 datadir 自动发现。适用于用户要读取本地 QMT 历史行情文件、导出财务数据、核对字段含义、或写离线量化分析脚本等场景。当用户提到解析 QMT/MinQMT 本地数据、读取 .dat 行情/财务文件、本地 datadir 数据提取时触发此 skill。
---

# qmt-parser — QMT 本地数据解析

## 概述

本 skill 提供一个纯 Python 解析库 `qmt_parser`（源码在 `/data1/qmt-parser/python/qmt_parser/`）
和一个统一 CLI `scripts/qmt_parser_cli.py`，用于直接读取 QMT 本地数据目录中的二进制文件，
**不依赖 QMT 客户端 API**。结构化解析只依赖标准库；DataFrame 输出需要 pandas；分红查询需要 plyvel。

## 前置条件

- Python 3.10+（结构化解析无需第三方库）。
- 需要 DataFrame 输出时：`pip install pandas`。
- 需要查询分红 LevelDB 时：`pip install plyvel`。
- 本机 QMT 本地缓存默认绑定在 `/mnt/gjzq_qmt/datadir`（见项目 AGENTS.md）。

## 快速开始

### 方式一：CLI（首选，默认输出 JSON）

```bash
# tick 分笔
python scripts/qmt_parser_cli.py tick /path/to/000001-20250529-tick.dat --head 3

# 1 分钟 K 线
python scripts/qmt_parser_cli.py min /path/to/000001-1m.dat --head 3

# 日线（带日期范围）
python scripts/qmt_parser_cli.py day /path/to/000001-1d.dat --start 20230101 --end 20231231 --head 3

# 财务 .DAT（7006 十大流通股东会自动聚合成同一报告期）
python scripts/qmt_parser_cli.py finance /path/to/002419_7006.DAT --head 1
python scripts/qmt_parser_cli.py finance /path/to/002419_7001.DAT --named --head 1

# 财务表列名
python scripts/qmt_parser_cli.py schema 7008

# 解码单条分红 value（hex）
python scripts/qmt_parser_cli.py dividend-value <hex>

# 从 datadir 根目录自动发现并解析
python scripts/qmt_parser_cli.py datadir /mnt/gjzq_qmt/datadir --code 000001.SZ --tick 20250529 --min --day --holidays
```

所有命令默认输出 JSON（`ok` / `total` / `rows` 或 `error` / `detail`），加 `--table` 输出人类可读表格。

> 脚本会自动把 `/data1/qmt-parser/python` 加入 `sys.path`。若包已 pip 安装，直接 `import qmt_parser` 即可；
> 也可用环境变量 `QMTPARSER_PYTHON` 指向包所在目录。

### 方式二：Python API

```python
import qmt_parser as qp

# tick
ticks = qp.parse_ticks_to_structs("/path/to/000001-20250529-tick.dat")

# 日线
rows = qp.parse_daily_to_structs("/path/to/000001-1d.dat", "20230101", "20231231")

# 财务（自动识别 type id，返回 typed 记录）
records = qp.FinanceReader.read_file("/path/to/002419_7001.DAT")
for name, value in records[0].named_values():
    print(name, value)

# datadir 自动发现
qmt = qp.QmtDataDir("/mnt/gjzq_qmt/datadir")
market, symbol = qmt.parse_security_code("000001.SZ")
daily = qmt.parse_daily_file_to_structs(market, symbol)
```

## 数据文件位置（QMT datadir 约定）

```text
{QMT_ROOT}/datadir/
├── SH|SZ|BJ/
│   ├── 0/<code>/<YYYYMMDD>.dat        # tick 分笔
│   ├── 60/<code>.DAT                  # 1 分钟线
│   └── 86400/<code>.DAT               # 日线
├── Finance|finance|financial/<code>_<type>.DAT   # 财务 7001-7008
├── DividData/                          # 分红 LevelDB
└── (xtquant 资料) holiday.csv / IndustryData.txt / sectorWeightData.txt / sectorlist.DAT ...
```

## 财务文件类型（7001-7008）

| Type ID | 内容 | 记录步长 | 载荷 |
|---------|------|---------|------|
| 7001 | 资产负债表 | 1264 | `ReportData` 156 列 |
| 7002 | 利润表 | 664 | `ReportData` 80 列 |
| 7003 | 现金流量表 | 920 | `ReportData` 111 列 |
| 7004 | 股本结构 | 56 | `CapitalData` |
| 7005 | 股东户数 | 64 | `HolderCountData` |
| 7006 | 十大流通股东 | 416 | `TopHolderData`（按报告期聚合） |
| 7007 | 十大股东 | 416 | `TopHolderData` |
| 7008 | 财务比率/每股指标 | 344 | `RatiosData` 41 列 |

## 关键语义

- Tick 价格字段 ÷1000；日线成交额 ÷100；分钟线成交额不缩放。
- Tick 集合竞价阶段（`market_phase_status == 12`）无实际成交，只有参考价与累计委托量。
- 日线 DataFrame 的 `preClose` 是库内按业务规则重算（停牌日=当日 close，否则=上一交易日 close），
  `suspendFlag = (volume==0 且 amount==0)`。
- 财务数值列哨兵值 `0x7FEFFFFFFFFFFFFF` → `NaN`。
- 财务 `7005` 表头顺序是 [AnnounceDate][ReportDate]（与其它类型相反），库内已处理。

## 注意事项

1. QMT 运行时会锁定部分文件，建议只读打开或先复制到临时目录。
2. LevelDB（DividData）同时只能被一个进程加锁访问；QMT 运行时查询分红请用备份目录。
3. 财务列名以逆向结果为准，优先用 `FinanceRecord.named_values()`，不要自行硬编码列顺序。

## 参考

详细 API、字段说明和数值语义见 `references/api_reference.md`。
等价性测试见 `/data1/qmt-parser/python/tests/test_parse.py`（与 Rust crate 单测断言对齐）。
