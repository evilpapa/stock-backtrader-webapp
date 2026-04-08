# QMT Python API 接口文档

`文档版本：3.3.6    `Python
版本：3.6.8`    `更新日期：2022.03.03

更新说明

| 序号 |
| 更新时间 |
| 新增项 |

| 1 |
| 2020.01.16 |
| 新增函数说明：cancel_task(taskId, accountId, accountType, ContextInfo) |

| 2 |
| 2020.03.03 |
| 新增函数说明：
1. 获取指定期权品种的详细信息
ContextInfo.get_option_detail_data()
2. 定时器函数 run_time(funcName,
period, startTime, market)
内容更新：
1. get_trade_detail_data()
新增获取任务功能
2. ContextInfo.get_financial_data() 新增公告时间 |

| 3 |
| 2020.05.20 |
| 新增函数说明：
1. 获取账户新股申购额度 get_new_purchase_limit()
2. 获取当日新股新债信息
get_ipo_data()
内容更新：
1. passorder() 函数补充说明 |

| 4 |
| 2020.05.21 |
| 新增函数说明：
1. 获取一篮子证券编码数据 ContextInfo.load_stk_list()
2.
获取一篮子证券编码及数量数据 ContextInfo.load_stk_vol_list()
3. 从本地获取行情数据
ContextInfo.get_local_data()
4. 获取换手率数据
ContextInfo.get_turnover_rate()
5. 获取ETF申赎清单数据
get_etf_info()
6. 获取ETF的基金份额参考净值 get_etf_iopv()
7. 停止处理函数
stop()
8. 获取合约详细信息 ContextInfo.get_instrumentdetail()
9.
获取期货合约到期日 ContextInfo.get_contract_expire_date()
10.
引用扩展数据在指定时间区域内的所有值和排名 ContextInfo.get_ext_all_data() |

| 5 |
| 2020.06.18 |
| 新增函数说明：
1. 暂停任务 pause_task()
2. 继续任务
resume_task()
内容更新：
1. smart_algo_passorder 新增参数
2. order
（委托对象）中新增 m_nTaskId （任务号）
3. 新增任务对象 CTaskDetail 说明
4. 新增下单操作类型
/ 主要交易类型 enum_EOperationType 说明 |

| 6 |
| 2021.01.07 |
| 新增函数说明：
1. 获取指定期权标的对应的期权品种列表
ContextInfo.get_option_undl_data()
2. 查询两融最大可下单量
query_credit_opvolume()
3. 查询两融最大可下单量的回调
credit_opvolume_callback()
4. 获取多因子数据 ContextInfo.get_factor_data()

| 7 |
| 2021.03.10 |
| 新增函数说明：
1. 获取过期ST数据 ContextInfo.get_his_st_data()；
2. 获取过期指数数据
ContextInfo.get_his_index_data()；
3. 订阅行情数据
ContextInfo.subscribe_quote()
4. 反订阅行情数据
ContextInfo.unsubscribe_quote()
5. 获取当前所有的行情订阅信息
ContextInfo.get_all_subscription()
内容更新：
1. 用户自行安装 Python
三方库
2. 用户自定义 Python 库路径及 QMT Python 库下载
3. 新增多因子数据接口使用方法 |

| 8 |
| 2021.04.20 |
| 新增函数说明：
1. 获取指定期权列表 ContextInfo.get_option_list()
2.
获取指定期权品种的实时隐含波动率 ContextInfo.get_option_iv()
3. 基于BS模型计算欧式期权理论价格
ContextInfo.bsm_price()
4. 基于BS模型计算欧式期权隐含波动率 ContextInfo.bsm_iv()

| 9 |
| 2021.06.04 |
| 内容更新：
1. 多因子数据 Python 接口使用说明
2.
回测模式和运行模式的区别更新说明，新增了业务支持说明
3. 下单函数新增说明：回测时，除了指定价，其他下单选价类型均以当期 k
线收盘价结算
4. 更正了 passorder 信用账号股票卖出参数，由 33 改为 34
5.
沪港通和深港通的市场代码由原来的 HGT 和 SHT 统一更改为 HK
6. 更正了多处笔误 |

| 10 |
| 2021.08.18 |
| 为丰富用户产品种类，支持高净值用户使用 Level2 指标进行 python 策略交易，国信对 Level2
产品进行差异化定价，其中：
标准版：可展示 Level2 行情，并可在行情界面查看 / 运行 Level2
相关数据指标。
增强版：在标准版的基础上，支持用户在策略中使用相关函数获取 Level2
行情指标数据，并使用该策略交易。
新增函数说明（仅支持在 Level2 增强版使用）：
1.
获取行情数据第二版 ContextInfo.get_market_data_ex()
2. 订阅行情数据
ContextInfo.subscribe_quote() 新增了订阅Level2 数据功能
内容更新：
1.
优化部分内容说明，提高阅读体验 |
