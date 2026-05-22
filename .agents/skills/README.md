# Skills Index

本目录存放面向量化交易与行情文档检索的本地 skills。

## 快速导航

### XtQuant 相关

- `xtquant-xtdata`
  - 用途：查询 `xtquant.xtdata` 行情模块文档
  - 适合问题：历史行情下载、实时订阅、缓存读取、财务数据、合约信息、板块成分、交易日历、ETF 申赎、可转债、公式模型
  - 入口：`xtquant-xtdata/SKILL.md`
  - 本地参考索引：`xtquant-xtdata/references/00-index.md`

- `xtquant-xttrade`
  - 用途：查询 `xtquant.xttrader` 交易模块文档
  - 适合问题：Trader 生命周期、连接与订阅、同步/异步下单、撤单、资产/委托/成交/持仓查询、信用业务、约券接口、回调类、交易枚举、返回对象字段
  - 入口：`xtquant-xttrade/SKILL.md`
  - 本地参考索引：`xtquant-xttrade/references/00-index.md`

### QMT 相关

- `qmt-api`
  - 用途：查询 QMT Python API 手册
  - 适合问题：`ContextInfo`、QMT 策略生命周期、QMT 行情接口、交易函数、财务/因子接口、附录枚举
  - 入口：`qmt-api/SKILL.md`
  - 本地参考索引：`qmt-api/references/00-index.md`

## 如何选择

### 先看数据源或模块名

- 问题里出现 `xtdata`、`download_history_data`、`subscribe_quote`、`get_market_data` → `xtquant-xtdata`
- 问题里出现 `xttrader`、`XtQuantTrader`、`order_stock`、`cancel_order_stock`、`query_stock_orders` → `xtquant-xttrade`
- 问题里出现 `ContextInfo`、`passorder`、`handlebar`、QMT 策略脚本 → `qmt-api`

### 再看问题类型

- 行情下载、行情字段、财务表、板块、交易日 → `xtquant-xtdata`
- 交易连接、下单撤单、账户查询、回调推送、信用和约券 → `xtquant-xttrade`
- QMT 策略开发、QMT 生命周期、QMT 原生接口 → `qmt-api`

## XtQuant 内部路由

### 当问题属于 `xtquant-xtdata`

- 先看：`xtquant-xtdata/references/00-index.md`
- 常用分卷：
  - `xtquant-xtdata/references/1-行情接口.md`
  - `xtquant-xtdata/references/2-财务数据接口.md`
  - `xtquant-xtdata/references/3-基础行情信息.md`
  - `xtquant-xtdata/references/4-附录-行情字段与字典.md`
  - `xtquant-xtdata/references/5-附录-财务字段与合约字段.md`

### 当问题属于 `xtquant-xttrade`

- 先看：`xtquant-xttrade/references/00-index.md`
- 常用分卷：
  - `xtquant-xttrade/references/1-数据字典.md`
  - `xtquant-xttrade/references/2-数据结构说明.md`
  - `xtquant-xttrade/references/3-系统与操作接口.md`
  - `xtquant-xttrade/references/4-查询接口.md`
  - `xtquant-xttrade/references/5-约券与回调.md`

## 常见边界

- `xtdata` 负责行情、财务、基础信息、日历、专题数据、模型结果。
- `xttrader` 负责交易连接、报撤单、查询、回调、信用业务、约券业务。
- `qmt-api` 负责 QMT Python 策略运行时和 `ContextInfo` 相关能力。

## 推荐用法

- 用户只提模块名时，优先进入对应 skill 的 `SKILL.md`。
- 用户问具体函数签名或返回值时，优先进入对应 skill 的 `references/00-index.md`。
- 用户问字段或枚举时，优先跳到各自的附录或数据字典分卷。
