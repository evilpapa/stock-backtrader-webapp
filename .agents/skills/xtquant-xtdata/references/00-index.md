# xtquant-xtdata 二次整理索引

来源：[XtQuant.XtData 行情模块](https://dict.thinktrader.net/nativeApi/xtdata.html?id=olYCD5)

## 参考文件

- 分卷（推荐检索）：
  - `概述.md`
  - `1-行情接口.md`
  - `2-财务数据接口.md`
  - `3-基础行情信息.md`
  - `4-附录-行情字段与字典.md`
  - `5-附录-财务字段与合约字段.md`

## 检索建议

- 想找函数签名：优先看对应分卷中的“函数速查”。
- 想确认返回值形状：优先看 `1-行情接口.md` 和 `2-财务数据接口.md`。
- 想确认字段/枚举：优先看 `4-附录-行情字段与字典.md`。
- 想确认财务表名、合约字段：优先看 `5-附录-财务字段与合约字段.md`。

## 函数索引

### 行情接口

- `subscribe_quote(stock_code, period='1d', start_time='', end_time='', count=0, callback=None)`
- `subscribe_whole_quote(code_list, callback=None)`
- `unsubscribe_quote(seq)`
- `run()`
- `subscribe_formula(formula_name, stock_code, period, start_time='', end_time='', count=-1, dividend_type=None, extend_param={}, callback=None)`
- `unsubscribe_formula(subID)`
- `call_formula(formula_name, stock_code, period, start_time='', end_time='', count=-1, dividend_type='none', extend_param={})`
- `call_formula_batch(formula_names, stock_codes, period, start_time='', end_time='', count=-1, dividend_type='none', extend_params=[])`
- `generate_index_data(formula_name, formula_param={}, stock_list=[], period='1d', dividend_type='none', start_time='', end_time='', fill_mode='fixed', fill_value=float('nan'), result_path=None)`
- `get_market_data(field_list=[], stock_list=[], period='1d', start_time='', end_time='', count=-1, dividend_type='none', fill_data=True)`
- `get_local_data(field_list=[], stock_list=[], period='1d', start_time='', end_time='', count=-1, dividend_type='none', fill_data=True, data_dir=data_dir)`
- `get_full_tick(code_list)`
- `get_divid_factors(stock_code, start_time='', end_time='')`
- `download_history_data(stock_code, period, start_time='', end_time='', incrementally=None)`
- `download_history_data2(stock_list, period, start_time='', end_time='', callback=None, incrementally=None)`
- `download_history_contracts()`
- `get_holidays()`
- `get_trading_calendar(market, start_time='', end_time='')`
- `download_cb_data()`
- `get_cb_info(stockcode)`
- `get_ipo_info(start_time, end_time)`
- `get_period_list()`
- `download_etf_info()`
- `get_etf_info()`
- `download_holiday_data()`
- `get_full_kline(field_list=[], stock_list=[], period='1m', start_time='', end_time='', count=1, dividend_type='none', fill_data=True)`

### 财务数据接口

- `get_financial_data(stock_list, table_list=[], start_time='', end_time='', report_type='report_time')`
- `download_financial_data(stock_list, table_list=[])`
- `download_financial_data2(stock_list, table_list=[], start_time='', end_time='', callback=None)`

### 基础行情信息

- `get_instrument_detail(stock_code, iscomplete)`
- `get_instrument_type(stock_code)`
- `get_trading_dates(market, start_time='', end_time='', count=-1)`
- `get_sector_list()`
- `get_stock_list_in_sector(sector_name)`
- `download_sector_data()`
- `create_sector_folder(parent_node, folder_name, overwrite)`
- `create_sector(parent_node, sector_name, overwrite)`
- `add_sector(sector_name, stock_list)`
- `remove_stock_from_sector(sector_name, stock_list)`
- `remove_sector(sector_name)`
- `reset_sector(sector_name, stock_list)`
- `get_index_weight(index_code)`
- `download_index_weight()`

## 常见主题跳转

- 历史补数与缓存读取：`1-行情接口.md`
- 订阅与回调：`1-行情接口.md`
- 公式/模型：`1-行情接口.md`
- 财务表与下载：`2-财务数据接口.md`
- 合约详情、板块、指数权重：`3-基础行情信息.md`
- tick / K线 / level2 字段与枚举：`4-附录-行情字段与字典.md`
- 财务字段与合约字段列表：`5-附录-财务字段与合约字段.md`
