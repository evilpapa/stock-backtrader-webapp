# 3. Python API 手册

（1）国金 Python API 是绑定在我们的主流平台中的，底层是 C++，保证了国金 Python API 对行情数据，财务数据等的高访问速度。

（2）支持跨资产类别的量化交易策略的回测、模拟交易功能。依照我们提供的的策略模板，可以编程出各种独特的投资策略，进行单一市场或跨市场交易。

（3）可以便捷的对投资策略进行日频率、分钟频率的历史回测，了解策略在市场中的历史表现，比较不同策略的优劣；也可以对策略进行模拟交易，了解策略在市场中的真实表现，更加准确的对策略进行评估。

（4）采用的是所见即所得的策略运行机制，完美展示策略运行结果。

## 3.1. 对第三方库的支持

QMT Python API 提供基于Python 3.X 规范的标准量化投资策略应用程序接口。主要通过以下两种方式对外提供：

### 3.1.1. 平台自带的 Python 环境

QMT 平台的安装包默认自带 Python 运行环境。
用户安装完国金客户端后，默认可以直接使用Python。
在这个打包的Python环境中，国金除了提供标准的 Python api 带的库外，还集成了如下一些第三方库：

| 名称          | 版本     | 说明                                                                                                                                                  |
|-------------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| NumPy       | 1.16.2 | NumPy (Numeric Python) 提供了许多高级的数值编程工具，如：矩阵数据类型、矢量处理，以及精密的运算库。专为进行严格的数字处理而产生。                                                                        |
| Pandas      | 0.22.0 | Python Data Analysis Library 或 Pandas 是基于 NumPy 的一种工具，该工具是为了解决数据分析任务而创建的。Pandas 入了大量库和一些标准的数据模型，提供了高效地操作大型数据集所需的工具。Pandas 提供了大量能使我们快速便捷地处理数据的函数和方法。 |
| Patsy       | 0.5.0  | 一个线性模型分析和构建工具库。                                                                                                                                     |
| SciPy       | 1.2.1  | SciPy 函数库在 NumPy 库的基础上增加了众多的数学、科学以及工程计算中常用的库函数。例如线性代数、常微分方程数值求解、信号处理、图像处理、稀疏矩阵等等。                                                                   |
| Statsmodels | 0.8.0  | Python 的统计建模和计量经济学工具包，包括一些描述统计、统计模型估计和推断。                                                                                                           |
| TA_Lib      | 0.4.17 | 称作技术分析库，是一种广泛用在程序化交易中进行金融市场数据的技术分析的函数库。它提供了多种技术分析的函数，可以大大方便我们量化投资中编程工作，内容包括：多种指标，如 ADX, MACD, RSI, 布林轨道等；K 线形态识别，如黄昏之星，锤形线等等。                       |
| sklearn     | 0.20.3 | Scikit-learn(sklearn) 是机器学习中常用的第三方模块，对常用的机器学习方法进行了封装，包括回归(Regression)、降维(Dimensionality Reduction)、分类(Classfication)、聚类(Clustering)等方法。             |
| tensorflow  | 1.8.0  | TensorFlow 是一个开源的、基于 Python 的机器学习框架，它由 Google 开发，并在图形分类、音频处理、推荐系统和自然语言处理等场景下有着丰富的应用，是目前最热门的机器学习框架。                                                  |
| numexpr     | 2.7.0  | Numexpr 是一个非常简单易用的 Numpy 性能提升工具。                                                                                                                    |
| xlrd        | 1.2.0  | python 操作 excel 主要用到 xlrd 和 xlwt 这两个库，即 xlrd 是读 excel，xlwt 是写 excel 的库。                                                                             |
| xlwt        | 1.3.0  | python 操作 excel 主要用到 xlrd 和 xlwt 这两个库，即 xlrd 是读 excel，xlwt 是写 excel 的库。                                                                             |
| xlsxwriter  | 1.2.7  | XlsxWriter 是 Python 用来构造 xlsx 文件的模块，可用于在 Excel2007 + XLSX 文件中写入多个工作表的文本，数字，公式和超链接。可以完成 xlsx 文件的自动化构造，包括：合并单元格，制作excel图表等功能。                         |
| matplotlib  | 3.0.3  | matplotlib是基于numpy的一套Python工具包。这个包提供了丰富的数据绘图工具，主要用于绘制一些统计图形。                                                                                        |

### 3.1.2. 用户自行安装 Python 三方库

对于有经验的 Python 开发者来说，平台提供了自行安装第三方库的方式。为了引入额外的第三方库，用户需要做如下一些操作：

安装前注意事项：

- 三方库的安装有可能会引起系统错误，建议有经验的用户进行尝试，已经内置的库，如果没有特殊需要请勿随意升级，特别是平台内置的
  pandas 库请务必不要升级，其他库请自行尝试；

- 安装三方库前，请备份 `QMT安装目录\bin.x64\` 目录下的 `DLLs` 和 `Lib` 这两个文件夹，以便在安装三方库引起系统错误后，替换回来，恢复系统默认的库所用。

安装流程：

- 下载官方的 Python3，并安装（目前 QMT 内置的 Python 版本为3.6.8，安装的官方的 Python 版本最好也是3.6.8，这样安装的库有最好的兼容性）；

- 按【win + r】键打开系统运行框，输入cmd，回车，打开 cmd 命令行窗口；

- 在命令行窗口输入一下命令，并回车进行安装：

```txt
Python3安装目录\Scripts\pip.exe install 三方库的名称 --target=QMT安装目录\bin.x64\Lib\site-packages

```

- 安装示例：

- 如要安装 tensorflow，可在 cmd 窗口中输入以下指令：

```cmd
C:\Python36\Scripts\pip.exe install tensorflow --target=D:\QMT\bin.x64\Lib\site-packages

```

- 如果是升级的话加-U参数，例如：

```cmd
C:\Python36\Scripts\pip.exe install -U tensorflow --target=D:\QMT\bin.x64\Lib\site-packages

```

- 临时使用清华源安装（速度快）：

```cmd
C:\Python36\Scripts\pip.exe install -i https://pypi.tuna.tsinghua.edu.cn/simple tensorflow --target=D:\QMT\bin.x64\Lib\site-packages

```

经过以上几个步骤后，用户就可以在国金的 Python 编辑器中使用自己安装的 Python 第三方库。

### 3.1.3. 用户自行设置 Python 三方库路径

为了满足部分客户需求，系统也提供了自行设定三方库的路径的功能，可点击系统左上方设置，在弹出的系统设置面板中，切换到交易设置 -
模型设置子面板，设置功能如下：

Python库路径：可自定义设定 Python 库的路径；

Python库下载：点击 Python 库下载，系统将会从服务器上下载最新的 QMT Python 库到上面指定的路径。

## 3.2. 使用说明

### 3.2.1. 概述

#### 3.2.1.1. 一般规定

在编写一个策略时，首先需要在代码的最前一行写上：

```python
# coding:gbk
```

统一脚本的编码格式是GBK

#### 3.2.1.2. 重要方法

QMT 平台 Python API 策略代码结构分两个部分，初始化函数 init() 和行情事件函数 handlebar() 。

初始化函数 init() 在整个策略中只执行一次，一般在此函数中设置交易佣金、滑点、基准等一些常用参数。

行情事件函数 handlebar() 为行情数据的处理函数，当前图中每根 K 线为一个行情数据，handlebar() 在每根 K 线上分别依次执行一次。
特别的，对于实时行情，最后一根 K 线还没确定时，每个tick执行一次 handlebar() 。
handlebar() 里面一般写整个策略的执行逻辑。

Python策略中必须有包含这两个基本方法，否则策略将运行不起来。

#### （1）初始化函数 init()

用法： init(ContextInfo)

释义： 初始化函数，只在整个策略开始时调用运行一次

参数： ContextInfo：策略运行环境对象，可以用于存储自定义的全局变量

返回： 无

示例：

```python
def init(ContextInfo):
	ContextInfo.initProfit = 0

```

#### （2）行情事件函数 handlebar()

用法： handlebar(ContextInfo)

释义： 行情事件函数，每根 K 线运行一次；实时行情获取状态下，先每根历史 K 线运行一次，再在每个 tick
数据来后驱动运行一次

参数： ContextInfo：策略运行环境对象，可以用于存储自定义的全局变量

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 输出当前运行到的 K 线的位置
	print(ContextInfo.barpos)

```

### 3.2.2. ContextInfo 对象

ContextInfo 是策略运行环境对象，是 init() 和 handlebar()
这两个基本方法必传参数，里面包括了终端自带的属性和方法，还可以添加自定义属性。

> 注：除特殊标明外，以下函数均支持回测和实盘/模拟运行模式。

#### （1）设定股票池 ContextInfo.set_universe()

用法： ContextInfo.set_universe(stocklist)

释义： 设定股票池

参数： list

返回： 无

示例：

```python
def init(ContextInfo):


	stocklist = ['000300.SH', '000004.SZ']
ContextInfo.set_universe(stocklist)

```

#### （2）设定交易账号 ContextInfo.set_account()

用法： ContextInfo.set_account(account)

释义： 设定交易账号，并将该账号用于之后的交易主推订阅。

> 注：
> 一、可多次调用以设置多个账号，应在init中进行设置完毕，init执行后再设置将不再订阅交易主推；
> 二、调用passorder传入账号为空时会使用最后一次设置的账号作为下单账号。

参数： string

返回： 无

示例：

```python
def init(ContextInfo):
	account = '6000000223'
    ContextInfo.set_account(account)

```

#### （3）设定回测起止时间 ContextInfo.start / ContextInfo.end

用法： ContextInfo.start / ContextInfo.end

释义： 设定回测起止时间，标准格式如”2009-07-14 01:13:30”，读写

> 注：
>
> 一、此函数只支持回测模式；
>
> 二、仅在init中设置生效，应在init中设置完毕；
>
> 三、缺省值为策略编辑界面设定的回测时间范围；
>
> 四、回测起止时间也可在策略编辑器的回测参数面板中设置，若两处同时设置，则以代码中设置的值为准；
>
> 五、结束时间小于等于开始时间则计算范围为空。

参数： 无

返回： 无

示例：

```python
def init(ContextInfo):
	ContextInfo.start = '2012-06-06 10:00:00'
	ContextInfo.end = '2013-08-08 14:30:00'

```

#### （4）设定回测初始资金 ContextInfo.capital

用法： ContextInfo.capital

释义： 设定回测初始资金，读写，默认为 1000000

> 注：此函数只支持回测模式。回测初始资金也可在策略编辑器的回测参数面板中设置，若两处同时设置，则以代码中设置的值为准。

参数： 无

返回： number

示例：

```python
def init(ContextInfo):
	ContextInfo.capital = 10000000


def handlebar(ContextInfo):
	print(ContextInfo.capital)

```

#### （5）设定策略回测滑点 ContextInfo.set_slippage()

用法： ContextInfo.set_slippage(slippageType, slippage)

释义： 设定策略回测滑点，默认值 0.00

> 注：此函数只支持回测模式。回测滑点也可在策略编辑器的回测参数面板中设置，若两处同时设置，则以代码中设置的值为准。

参数：

- slippageType：滑点类型，可选值：
    - 0：tick跳数设置滑点
    - 1：按照固定值（价格）设置滑点
    - 2：价格比例设置滑点
- slippage：滑点值

返回： 无

示例：

```python
def init(ContextInfo):
	# 按照固定值（价格）设置滑点值为 0.01
	ContextInfo.set_slippage(1, 0.01)

```

#### （6）设定策略回测各种手续费率 ContextInfo.set_commission()

用法： ContextInfo.set_commission(commissionType, commissionList)

释义： 设定策略回测各种手续费率，默认类型值 0 按比例，默认值 0.000

> 注：此函数只支持回测模式。回测各种手续费率也可在策略编辑器的回测参数面板中设置，若两处同时设置，则以代码中设置的值为准。

参数：

- commissionType：number，可选值：
    - 0：按比例
    - 1：按每手（股）
-
commissionList：list，包含六个值，commissionList = [open_tax, close_tax, open_commission, close_commission, close_tdaycommission, min_commission]
- open_tax：买入印花税
- close_tax：卖出印花税
- open_commission：开仓手续费;
- close_commission：平仓（平昨）手续费
- close_tdaycommission：平今手续费
- min_commission：最少手续费

> 注：如果只填写一个参数则代表输入的参数值赋值给 open_commission = close_commission = close_today_commission，其他的值均为
> 0，这时 commissionType 为 0

返回： 无

示例1：

```python
def init(ContextInfo):
	# 万三
	commission = 0.0003

	# 设定开仓手续费和平仓手续费以及平今手续费均为 0.0003，其余为 0
	ContextInfo.set_commission(commission)
```

示例2：

```python
def init(ContextInfo):
	commissionList = [0, 0.0001, 0.0003, 0.0003, 0, 5]

	# 设定买入印花税为 0，卖出印花税为 0.0001，开仓手续费和平仓（平昨）手续费均为万三，平今手续费为 0，最小手续费为 5
	ContextInfo.set_commission(0, commissionList)

```

#### （7）获取股票池中的股票 ContextInfo.get_universe()

用法： ContextInfo.get_universe()

释义： 获取股票池中的股票

参数： 无

返回： list

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_universe())

```

#### （8）获取当前周期 ContextInfo.period

用法： ContextInfo.period

释义： 获取当前周期，即基本信息中设置的默认周期，只读

参数： 无

返回： string，返回值含义：

- ‘1d’：日线
- ‘1m’：1分钟线
- ‘3m’：3分钟线
- ‘5m’：5分钟线
- ‘15m’：15分钟线
- ‘30m’：30分钟线
- ‘1h’：小时线
- ‘1w’：周线
- ‘1mon’：月线
- ‘1q’：季线
- ‘1hy’：半年线
- ‘1y’：年线

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.period)

```

#### （9）获取当前运行到 K 线索引号 ContextInfo.barpos

用法： ContextInfo.barpos

释义： 获取当前运行到 K 线索引号，只读，索引号从0开始

参数： 无

返回： number

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.barpos)

```

#### （10）获取当前图 K 线数目 ContextInfo.time_tick_size

用法： ContextInfo.time_tick_size

释义： 获取当前图 K 线数目，只读

参数： 无

返回： number

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.time_tick_size)

```

#### （11）判定是否为最后一根 K 线 ContextInfo.is_last_bar()

用法： ContextInfo.is_last_bar()

释义： 判定是否为最后一根 K 线

参数： 无

返回： bool，返回值含义：

- True：是
- False：否

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.is_last_bar())

```

#### （12）判定是否为新的 K 线 ContextInfo.is_new_bar()

用法： ContextInfo.is_new_bar()

释义： 某根 K 线的第一个 tick 数据到来时，判定该 K 线为新的 K 线

参数： 无

返回： bool，返回值含义：

- True：是
- False：否

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.is_new_bar())

```

#### （13）判定股票是否停牌 ContextInfo.is_suspended_stock()

用法： ContextInfo.is_suspended_stock(stockcode.market)

释义： 判定股票是否停牌

参数： 股票市场和代码

返回： bool，返回值含义：

- True：停牌
- False：未停牌

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.is_suspended_stock('600004.SH'))

```

#### （14）判定给定股票代码是否在指定的板块中 is_sector_stock()

用法： is_sector_stock(sectorname, market, stockcode)

释义： 判定给定股票代码是否在指定的板块中

参数：

- sectorname：string，板块名
- market：string，市场
- stockcode：string，股票代码

返回： bool，返回值含义：

- True：在板块中
- False：不在板块中

示例：

```python
def handlebar(ContextInfo):


	print(is_sector_stock('沪深300', 'SH', '600000'))

```

#### （15）判定给定股票是否属于某个类别 is_typed_stock()

用法： is_typed_stock(stocktypenum, market, stockcode)

释义： 判定给定股票是否属于某个类别

参数：

- stocktypenum：number，类别标号，如股票类别标号为100003，详细见[6.3. 附录3 is_typed_stock 函数证券分类表](# 6.3. 附录3
  is_typed_stock 函数证券分类表)，或者见 xtstocktype.lua 文件
- market：string，市场
- stockcode：string，股票代码

返回： number，返回值含义：

- 1：True
- 0：False

示例：

```python
def handlebar(ContextInfo):
	print(is_typed_stock(100003, 'SH', '600000'))

```

#### （16）判定给定股票代码是否在指定的行业分类中 get_industry_name_of_stock()

用法： get_industry_name_of_stock(industryType, stockcode)

释义： 判定给定股票代码是否在指定的行业分类中

参数：

- industryType：string，行业类别，有 ‘CSRC’ 和 ‘SW’ 两种
- stockcode：string，形式如 ‘stockcode.market’，如 ‘600000.SH’

返回： string：对应行业名，找不到则返回空 string

示例：

```python
def handlebar(ContextInfo):


	print(get_industry_name_of_stock('SW', '600000.SH'))

```

#### （17）获取当前图代码 ContextInfo.stockcode

用法： ContextInfo.stockcode

释义： 获取当前图代码，只读

参数： 无

返回： string：对应主图代码

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.stockcode)

```

#### （18）获取当前主图复权处理方式 ContextInfo.dividend_type

用法： ContextInfo.dividend_type

释义： 获取当前主图复权处理方式

参数： 无

返回： string，返回值含义：

- ‘none’：不复权
- ‘front’：向前复权
- ‘back’：向后复权
- ‘front_ratio’：等比向前复权
- ‘back_ratio’：等比向后复权

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.dividend_type)

```

#### （19）获取当前主图市场 ContextInfo.market

用法： ContextInfo.market

释义： 获取当前主图市场，只读

参数： 无

返回： string：对应主图市场

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.market)

```

#### （20）根据代码获取名称 ContextInfo.get_stock_name()

用法： ContextInfo.get_stock_name(’stockcode’)

释义： 根据代码获取名称

参数： stockcode：股票代码，如’000001.SZ’，缺省值 ‘ ‘ 默认为当前图代码

返回： string（GBK编码）

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.get_stock_name('000001.SZ'))

```

#### （21）根据代码返回对应股票的上市时间 get_open_date()

用法： get_open_date(’stockcode’)

释义： 根据代码返回对应股票的上市时间

参数： stockcode：股票代码，如’000001.SZ’，缺省值 ‘ ‘ 默认为当前图代码

返回： number

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.get_open_date('000001.SZ'))

```

#### （22）表示当前是否开启回测模式 ContextInfo.do_back_test

用法： ContextInfo.do_back_test

释义： 设定是否开启回测模式，只读，默认值为 False

参数： 无

返回： bool

#### （23）获取回测基准 ContextInfo.benchmark

用法： ContextInfo.benchmark

释义： 获取回测基准，只读

> 注：此函数只支持回测模式。

参数： 无

返回： string

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.benchmark)

```

#### （24）设定回测系统输出日志显示级别 ContextInfo.data_info_level

用法： ContextInfo.data_info_level

释义： 设定回测平台输出日志显示级别，默认是0，可设置的值有：0 信息，1 警告，2 错误，3 致命，根据设定显示大于等于该级别的日志

> 注：此函数只支持回测模式。

参数： 无

返回： 无

示例：

```python
def init(ContextInfo):


  # 显示 '错误' 级别以上的信息
  ContextInfo.data_info_level = 2

```

#### （25）获取某个记录类型对应的某个时刻的记录情况 get_result_records()

用法： get_result_records (recordtype, index, ContextInfo)

释义： 获取某个记录类型对应的某个时刻的记录情况。

*注：模型回测时有效，获取的为回测面板中的记录结果

参数：

- Recordtype：string，面板类型，可选值：
  - ‘buys’：买入持仓
  - ‘sells’：卖出持仓
  - ‘holdings’：当前持仓
  - ‘historysums’：历史汇总
  - ‘dealdetails’：交易明细
- index：number，当前主图对应 K 线索引
- ContextInfo：PythonObj，Python对象，这里必须是ContextInfo

返回： list，返回的 list 结构中包含 0 个或多个 Python 对象，该 Python 对象内含如下属性值：

- market：string，市场代码
- stockcode：string，合约代码
- open_close：number，期货开平：1 开 0 平；股票： 1 买 0 卖
- direction：number，方向：1 多 -1 空；回购：1 逆回购 -1 正回购
- trade_price：number，持仓成本
- current_price：number，最新价，持仓中用这个价
- profit：number，持仓盈亏
- position：number，仓位数量
- current_weight：number，仓位权重[暂无有效数据]
- benefit_weight：number，盈利占比权重，记录类型是 ‘historysums’ 时有效
- holding_periods：number，累计持仓天数，记录类型是 ‘historysums’ 时有效
- buy_sell_times：number，交易次数，记录类型是 ‘historysums’ 时有效
- commission：number，手续费
- trade_balance：number，成交额或市值
- operate_type：number，操作类型，记录类型是 ‘dealdetails’ 时有效
- trade_date：number，交易日期，毫秒标记，记录类型是 ‘dealdetails’ 时有效

示例：

```python
def handlebar(ContextInfo):


	index = ContextInfo.barpos
print(get_result_records('buys', index, ContextInfo))

```

#### （26）设置定时器 run_time()

用法： run_time(funcName, period, startTime, market)

释义： 设置定时器

> 注：回测模式时，run_time()没有意义

参数：

- funcName：回调函数名
- period：重复调用的时间间隔,’5nSecond’表示每5秒运行1次回调函数,’5nDay’表示每5天运行一次回调函数,’500nMilliSecond’表示每500毫秒运行1次回调函数
- startTime：表示定时器第一次启动的时间,如果要定时器立刻启动,可以设置历史的时间

回调函数参数： 

- ContextInfo：策略模型全局对象

示例：

```python
#此例为自2019-10-14 13:20:00后每5s运行一次myHandlebar
import time

def init(ContextInfo):
    ContextInfo.run_time("myHandlebar","5nSecond","2019-10-14 13:20:00","SH")

def myHandlebar(ContextInfo):
    print('hello world')

def handlebar(ContextInfo):
    pass

```

#### （27）停止处理函数 stop()

用法： stop(ContextInfo)

释义： PY策略模型关闭停止前运行到的函数，复杂策略模型，如中间有起线程可通过在该函数内实现停止线程操作。

> 注：PY策略可不用该函数

参数： ContextInfo：策略模型全局对象

示例：

```python
def stop(ContextInfo):


	print('strategy is stop !')

```

### 3.2.3. 获取数据

*注：除特殊标明外，以下函数均支持回测和实盘/模拟运行模式。

#### （1）获取最新流通股本 ContextInfo.get_last_volume()

用法：ContextInfo.get_last_volume(stockcode)

释义： 获取最新流通股本

参数： string：必须是 ‘stock.market’ 形式

返回： number

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.get_last_volume('000002.SZ'))

```

#### （2）获取当前 K 线对应时间的时间戳 ContextInfo.get_bar_timetag()

用法： ContextInfo.get_bar_timetag(index)

释义： 获取当前 K 线对应时间的时间戳

参数： number：K 线索引号

返回： number

示例：

```python
def handlebar(ContextInfo):


	index = ContextInfo.barpos
    print(ContextInfo.get_bar_timetag(index))

```

#### （3）获取当前主图品种最新分笔对应的时间的时间戳 ContextInfo.get_tick_timetag()

用法： ContextInfo.get_tick_timetag()

释义： 获取当前主图品种最新分笔对应的时间的时间戳

参数： 无

返回： number

示例：

```python
def handlebar(ContextInfo):


	print(ContextInfo.get_tick_timetag())

```

#### （4）获取指数成份股 ContextInfo.get_sector()

用法： ContextInfo.get_sector(sector, realtime)

释义： 获取板块成份股，只支持取指数成份股

参数：

- string：必须是 ‘stock.market’ 形式，如 ‘000300.SH’，可取如沪深300（000300.SH）、中证500（000905.SH）、上证50（000016.SH）等指数的历史成份股
- realtime：毫秒级时间戳，如不填则默认取目前最新成份股

返回： list：内含成份股代码，里面股票代码为 ‘000002.SZ’ 形式

示例：

```python
def handlebar(ContextInfo):
	index = ContextInfo.barpos
	realtime = ContextInfo.get_bar_timetag(index)
	print(ContextInfo.get_sector('000300.SH', realtime))

```

#### （5）获取行业成份股 ContextInfo.get_industry()

用法： ContextInfo.get_industry(industry)

释义： 获取行业成份股，证监会行业，行业列表详见[6.2. 附录2 CSRC行业列表](#6.2. 附录2 CSRC行业列表)

参数： string：如 ‘CSRC采矿业’

返回： list：内含成份股代码，里面股票代码为 ‘000002.SZ’ 形式

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_industry('CSRC采矿业'))

```

#### （6）获取板块成份股 ContextInfo.get_stock_list_in_sector()

用法： ContextInfo.get_stock_list_in_sector(sectorname, realtime)

释义： 获取板块成份股，支持客户端左侧板块列表中任意的板块，包括自定义板块

参数：

- string：板块名，如’沪深300’，’中证500’、’上证50’、’我的自选’等
- realtime：毫秒级时间戳

返回： list：内含成份股代码，代码形式为 ‘stockcode.market’，如 ‘000002.SZ’

示例：

```python
def handlebar(ContextInfo):
	index = ContextInfo.barpos
	realtime = ContextInfo.get_bar_timetag(index)
	print(ContextInfo.get_stock_list_in_sector('沪深300', realtime))

```

#### （7）获取某只股票在某指数中的绝对权重 ContextInfo.get_weight_in_index()

用法： ContextInfo.get_weight_in_index(indexcode, stockcode)

释义： 获取某只股票在某指数中的绝对权重

参数：

- indexcode：string，指数代码，形式如 ‘stockcode.market’，如 ‘000300.SH’
- stockcode：string，股票代码，形式如 ‘stockcode.market’，如 ‘600004.SH’

返回： number：返回的数值单位是 %，如 1.6134 表示权重是 1.6134%

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_weight_in_index('000300.SH', '000002.SZ'))

```

#### （8）获取合约乘数 ContextInfo.get_contract_multiplier()

用法： ContextInfo.get_contract_multiplier(contractcode)

释义： 获取合约乘数

参数： string：合约代码，形式如 ‘code.market’，如 ‘IF1707.IF’

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_contract_multiplier('IF1707.IF'))

```

#### （9）获取无风险利率 ContextInfo.get_risk_free_rate()

用法：ContextInfo.get_risk_free_rate(index)

释义： 获取无风险利率，用十年期国债收益率CGB10Y作无风险利率

参数： number：当前图 K 线索引号

返回： number

示例：

```python
def handlebar(ContextInfo):
	index = ContextInfo.barpos
	print(ContextInfo.get_risk_free_rate(index))

```

#### （10）获取给定日期对应的 K 线索引号 ContextInfo.get_date_location()

用法： ContextInfo.get_date_location(strdate)

释义： 获取给定日期对应的 K 线索引号，如给定日期小于当前图 K 线对应的最早的日期，结果返回 0；如给定日期大于当前图 K 线对应的最新日期，结果返回最新 K 线的索引号

参数： string：形式如 ‘yyyymmdd’ ，如 ‘20170711’

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_date_location('20170711'))

```

#### （11）获取策略设定的滑点 ContextInfo.get_slippage()

用法： ContextInfo.get_slippage()

释义： 获取策略设定的滑点

> 注：此函数只支持回测模式。

参数： 无

返回： dict，key 包括：

- slippage_type
- slippage

示例：

```python
def init(ContextInfo):
	ContextInfo.set_slippage(0.003)


def handlebar(ContextInfo):
	print(ContextInfo.get_slippage())

```

#### （12）获取策略设定的各种手续费率 ContextInfo.get_commission()

用法： ContextInfo.get_commission()

释义： 获取策略设定的各种手续费率

> 注：此函数只支持回测模式。

参数： 无

返回： dict，key 包括

- commission_type
- open_tax
- close_tax
- open_commission
- close_commission
- close_tdaycommission
- min_commission

示例：

```python
def init(ContextInfo):
	ContextInfo.set_commission(0.0003)


def handlebar(ContextInfo):
	print(ContextInfo.get_commission())

```

#### （13）获取策略回测的净值 ContextInfo.get_net_value()

用法： ContextInfo.get_net_value(index)

释义： 获取策略回测的净值

> 注：此函数只支持回测模式。

参数： index = ContextInfo.barpos

返回： number

示例：

```python
def handlebar(ContextInfo):
	index = ContextInfo.barpos
	print(ContextInfo.get_net_value(index))

```

#### （14）获取财务数据 ContextInfo.get_financial_data()

用法：ContextInfo.get_financial_data(fieldList,stockList,startDate,endDate,report_type=’announce_time’)

释义： 获取财务数据

参数：

- fieldList：字段列表，如 [’CAPITALSTRUCTURE.total_capital’, ‘ASHAREINCOME.net_profit_incl_min_int_inc’] （例子中取了股本结构中的总股本，与利润表中的净利润），更多支持字段参见[4. 财务数据接口使用方法](#4.财务数据接口使用方法)
- stockList：股票列表，如 [’600000.SH’, ‘000001.SZ’]
- startDate：开始时间，如 ‘20171209’
- endDate：结束时间，如 ‘20171212’
- report_type:时间类型,可缺省,默认是按照数据的公告期为区分取数据,设置为’report_time’为按照报告期取数据,可选值: 
  - ’announce_time’
  - ’report_time’

返回：

函数根据stockList代码列表,startDate,endDate时间范围的大小范围不同的数据类型

- (1)代码列表1-时间范围为1返回： pandas.Series index=字段
- (2)代码列表1-时间范围为n返回： pandas.DataFrame index=时间,columns=字段
- (3)代码列表n-时间范围为1返回： pandas.DataFrame index=代码,columns=字段
- (4)代码列表n-时间范围为n返回： pandas.Panel items=代码,major_axis=时间,minor_axis=字段

选择按照公告期取数和按照报告期取数的区别:若某公司当年4月26日发布上年度年报,如果选择按照公告期取数,则当年4月26日之后至下个财报发布日期之间的

数据都是上年度年报的财务数据,如果选择按照报告期取数,则上年度第4季度(上年度10月1日-12月31日) 的数据就是上年度报告期的数据.代码1-时间1：pandas.Series index = 字段

> 注：必须安装pandas

示例：

```python
def handlebar(ContextInfo):
	# 取股本结构中的总股本，与利润表中的净利润
	fieldList = ['CAPITALSTRUCTURE.total_capital', 'ASHAREINCOME.net_profit_incl_min_int_inc']
	stockList = ['600000.SH', '000001.SZ']
	startDate = '20171209'
	endDate = '20171212'
	# 获取20171209-20171212时间段浦发银行和平安银行的总股本及利润表的净利润
	ContextInfo.get_financial_data(fieldList, stockList, startDate, endDate)

```

#### （15）获取财务数据 ContextInfo.get_financial_data()

用法：ContextInfo.get_financial_data(tabname,colname,market,code,report_type=’report_time’,barpos) (与上一个 ContextInfo.get_financial_data 可同时使用)

释义： 获取财务数据

参数：

- tabname：表格名称
- colname：字段名称
- market：市场
- code：股票代码
- barpos：当前 bar 的索引
- report_type:时间类型,可缺省,默认是按照数据的公告期为区分取数据,设置为’report_time’为按照报告期取数据,可选值:
  - ’announce_time’
  - ’report_time

返回： number

示例：

```python
def handlebar(ContextInfo):
	index = ContextInfo.barpos
	# 获取当前时间点浦发银行利润表的净利润，更多支持字段参见[财务数据接口使用方法]
	ContextInfo.get_financial_data('ASHAREINCOME', 'net_profit_incl_min_int_inc', 'SH', '600000', index)

```

#### （16）获取历史行情数据 ContextInfo.get_history_data()

用法： ContextInfo.get_history_data(len, period, field, dividend_type = 0, skip_paused = True)

释义： 获取历史行情数据

> 注：必须先通过 ContextInfo.set_universe() 设定基础股票池，获取历史行情数据是获取的是股票池中的历史行情数据。

参数：

- len：number，需获取的历史数据长度
- period：string，需获取的历史数据的周期，可选值：
    - ‘tick’：分笔线
    - ‘1d’：日线
    - ‘1m’：1分钟线
    - ‘3m’：3分钟线
    - ‘5m’：5分钟线
    - ‘15m’：15分钟线
    - ‘30m’：30分钟线
    - ‘1h’：小时线
    - ‘1w’：周线
    - ‘1mon’：月线
    - ‘1q’：季线
    - ‘1hy’：半年线
    - ‘1y’：年线
- field：string，需获取的历史数据的类型，可选值：
    - ‘open’
    - ‘high’
    - ‘low’
    - ‘close’
    - ‘quoter’（结构见get_market_data）
- dividend_type：默认参数，number，除复权，默认不复权，可选值：
    - 0：不复权
    - 1：向前复权
    - 2：向后复权
    - 3：等比向前复权
    - 4：等比向后复权
- skip_paused：默认参数，bool，是否停牌填充，默认填充

> 注：可缺省参数：dividend_type，skip_paused

返回： 一个字典dict结构，key 为 stockcode.market, value 为行情数据
list，list 中第 0 位为最早的价格，第 1 位为次早价格，依次下去。

示例：

```python
def init(ContextInfo):


	ContextInfo.set_universe(['000300.SH', '000004.SZ'])


def handlebar(ContextInfo):
	# 获取股票池中所有股票的最近两日的收盘价
	hisdict = ContextInfo.get_history_data(2, '1d', 'close')
	for k, v in hisdict.items():
		if len(v) > 1:
			# 今日涨幅
			print(k, ':', v[1] - v[0])

```

#### （17）获取行情数据 ContextInfo.get_market_data()

用法： ContextInfo.get_market_data(fields, stock_code = [], start_time = ‘’, end_time = ‘’, skip_paused = True, period = ‘1d’, dividend_type = ‘none’, count = -1)

释义： 获取行情数据

参数：

- fields：字段列表：
    - ‘open’：开
    - ‘high’：高
    - ‘low’：低
    - ‘close’：收
    - ‘volume’：成交量
    - ‘amount’：成交额
    - ‘settle’：结算价
    - ‘quoter’：分笔数据（包括历史）
    - ‘quoter’分笔数据结构：dict
      ```txt
      {
          lastPrice：最新价
          amount：成交额
          volume：成交量
          pvolumn：前成交量
          openInt：持仓量
          stockStatus：股票状态
          lastSettlementPrice：最新结算价
          open：开盘价
          high：最高价
          low：最低价
          settlementPrice：结算价
          lastClose：收盘价
          askPrice：列表，卖价五档
          bidPrice：列表，买价五档
          askVol：列表，卖量五档
          bidVol；列表，买量五档
      }
      ```
- stock_code ：默认参数，合约代码列表，合约格式 code.market, 如 ‘600000.SH’，不指定时为当前图合约
- start_time：默认参数，开始时间，格式 ‘20171209’ 或 ‘20171209010101’
- end_time：默认参数，结束时间，格式 ‘20171209’ 或 ‘20171209010101’，周期是分钟级的模型获取日线，获取的实际数据会比结束时间多一天
- skip_paused：默认参数，可选值：
    - true：如果是停牌股，会自动填充未停牌前的价格作为停牌日的价格
    - False：停牌数据为nan
- period：默认参数，周期类型：
    - ‘tick’：分笔线
    - ‘1d’：日线
    - ‘1m’：1分钟线
    - ‘3m’：3分钟线
    - ‘5m’：5分钟线
    - ‘15m’：15分钟线
    - ‘30m’：30分钟线
    - ‘1h’：小时线
    - ‘1w’：周线
    - ‘1mon’：月线
    - ‘1q’：季线
    - ‘1hy’：半年线
    - ‘1y’：年线
- dividend_type：默认参数，缺省值为 ‘none’，除复权，可选值：
    - ‘none’：不复权
    - ‘front’：向前复权
    - ‘back’：向后复权
    - ‘front_ratio’：等比向前复权
    - ‘back_ratio’：等比向后复权
- count：默认参数，缺省值为 -1，大于等于 0 时，效果与 get_history_data 保持一致。

count 和开始时间、结束时间同时设置的效果如下表：

| count 取值   | 时间设置是否生效 | 开始时间和结束时间设置效果                  |
|------------|----------|--------------------------------|
| count >= 0 | 无效       | 从当前时间往回取多少个周期的值，取值数量完全取决于count |
| count = -1 | 生效       | 同时设置开始时间和结束时间，在所设置的时间段内取值      |
| count = -1 | 生效       | 开始时间结束时间都不设置，取当前最新bar的值        |
| count = -1 | 生效       | 只设置开始时间，取所设开始时间到当前时间的值         |
| count = -1 | 生效       | 只设置结束时间，取股票上市第一根 bar 到所设结束时间的值 |

> 注：
>
> - 特别的，默认参数需带上参数名方可生效，调用方式与 Python 别无二致
>
> - 策略点击运行，以策略代码中所设置的开始时间和结束时间为准，策略点击回测，以 ‘回测参数’ 里所设置的开始时间和结束时间为准。
>
> - 可缺省参数：start_time，end_time，skip_paused，dividend_type，count

返回：

count >= 0，不同的参数，返回的数据结构不同，以下举例说明了不同的数据结构的类型。（代码指股票代码；时间即为函数中所设置的时间，主要由 count、start_time、end_time 决定；字段即 fields 里的字段）

##### （1）1支股票代码，在1个时间点（ count 缺省默认为 -1 ，即为当前时间点的 bar），取1个字段的值，则返回相应字段的值。

代码：

```python
def init(ContextInfo):
	ContextInfo.set_universe(['000831.SZ'])


def handlebar(ContextInfo):
	df = ContextInfo.get_market_data(['close'], stock_code=ContextInfo.get_universe(), skip_paused=True, period='1d',
									 dividend_type='front')
	print(df)

```

输出：

`17.40`

##### （2）1支股票代码，在一个时间点（count、start_time、end_time 都缺省，即为当前时间点的 bar），取多个字段的值，返回 pandas.Series（pandas 一维数组）类型的值。

代码：

```python
def init(ContextInfo):
	ContextInfo.set_universe(['000831.SZ'])


def handlebar(ContextInfo):
	df = ContextInfo.get_market_data(['close', 'open'], stock_code=ContextInfo.get_universe(), skip_paused=True,
									 period='1d', dividend_type='front')
	print(df)

```

输出：

```txt
close 17.40
open 17.11
```

##### （3）1支股票代码，在一个时间段取值，返回 pandas.DataFrame （ pandas 二维表格型数据结构）类型的值。

代码：

```python
def init(ContextInfo):
	ContextInfo.set_universe(['000831.SZ'])


def handlebar(ContextInfo):
	df = ContextInfo.get_market_data(['close', 'open'], stock_code=ContextInfo.get_universe(), skip_paused=True,
									 period='1d', dividend_type='front', count=2)
	print(df)

```

输出：

```txt
          close  open
20190618  17.59  17.60
20190619  17.40  17.11
```

##### （4）多个股票代码，在一个时间点取值，返回 pandas.DataFrame （ pandas 二维表格型数据结构）类型的值。

代码：

```python
def init(ContextInfo):
	ContextInfo.set_universe(['000831.SZ', '600000.SH'])


def handlebar(ContextInfo):
	df = ContextInfo.get_market_data(['close', 'open'], stock_code=ContextInfo.get_universe(), skip_paused=True,
									 period='1d', dividend_type='front', count=-1)
	print(df)

```

输出：

```txt
           close  open
000831.SZ  17.40  17.11
600000.SH  11.88  12.04
```

（5）多支股票代码，在一个时间段取值，返回 pandas.Panel （pandas 三维数组结构）类型的值。

代码：

```python
def init(ContextInfo):
	ContextInfo.set_universe(['000831.SZ', '600000.SH'])


def handlebar(ContextInfo):
	df = ContextInfo.get_market_data(['close', 'open'], stock_code=ContextInfo.get_universe(), skip_paused=True,
									 period='1d', dividend_type='front', count=2)
	print(df)

```

输出：

```txt
Dimensions: 2 (items) x 2 (major_axis) x 2 (minor_axis)
Items axis: 000831.SZ to 600000.SH
Major_axis axis: 20190618 to 20190619
Minor_axis axis: close to open
```

> 注：
>
> - 需要下载历史数据；
>
> - pandas相关介绍详见pandas官方文档；
>
> - Python需要安装pandas；
>
> - 时间区间：两边闭区间。
>
> - get_history_data() 和 get_market_data() 两者区别：get_history_data()
    > 是获取设定的股票池中股票某段行情，主要用来构建简单的指标；get_market_data()
    > 可获取任意股票行情，返回行情数据可以是 dataframe ，可用于复杂的分析。

示例1：

```python
def handlebar(ContextInfo):
	# 以 period 参数指定需要的周期
	Result = ContextInfo.get_market_data(['open', 'high', 'low', 'close'], ['600000.SH'], '20170101', '20170102', True,
										 '1d', 'none')
	d_m = ContextInfo.get_market_data(['close'], ['600000.SH'], start_time='20181230', end_time='20190107', period='1d')
	print(d_m)
	m_m = ContextInfo.get_market_data(['close'], ['600000.SH'], start_time='20181230', end_time='20190107', period='1m')
	print(m_m)

```

示例2：

```python
def init(ContextInfo):
	# 先设置股票池，此时股票池只有一个股票
	ContextInfo.set_universe(['000001.SZ'])


def handlebar(ContextInfo):
	# 获取平安银行当前 bar 的收盘价
	close = ContextInfo.get_market_data(['close'], stock_code=ContextInfo.get_universe(), period='1d',
										dividend_type='front', count=1)

	# 打印平安银行当前bar的收盘价
	print(close)  # close 是一个数值

	# 获取平安银行最新的开高低收四个价格
	df1 = ContextInfo.get_market_data(['open', 'high', 'low', 'close'], stock_code=ContextInfo.get_universe(),
									  period='1d', dividend_type='front', count=1)

	# 打印平安银行当前bar的最高价
	print(df1['high'])  # df1 是一个 pandas.series

	# 获取平安银行最近两天的高开低收
	df2 = ContextInfo.get_market_data(['open', 'high', 'low', 'close'], stock_code=ContextInfo.get_universe(),
									  period='1d', dividend_type='front', count=2)

	# 打印平安银行昨天的收盘价
	print(df2['close'][-2])  # df2 是一个 pandas.dataframe

```

#### （18）获取行情数据第二版 ContextInfo.get_market_data_ex()

用法： ContextInfo.get_market_data_ex(fields=[], stock_code=[], period=’follow’, start_time=’’, end_time=’’, count=-1, dividend_type=’follow’, fill_data=True, subscribe=True)

释义： 获取行情数据第二版，目前该接口是用于获取level-2特色指标快照，该项接口需要额外开通level-2增强版权限

参数：

- fields：list，字段列表，对不同周期的数据取值范围不同默认为空list，代表所有字段
- stock_code：list，合约代码列表
- period：str，周期，默认为 ‘follow’，为当前主图周期，可选范围：
    - ‘tick’：分笔数据
    - ‘1m’、’5m’、’15m’ 等分钟周期
    - ‘1d’：日线数据
    - ‘l2quoteaux’：Level2 行情快照指标
    - ‘l2transactioncount’：Level2 大单统计
- start_time：开始时间，为空视为最早，时间格式为’20201231’或’20201231093000’
- end_time：结束时间，为空视为最新，时间格式为’20201231’或’20201231093000’
- count：数据最大个数，-1视为不做个数限制
- dividend_type：复权方式，默认为’follow’，为当前主图复权方式，可选范围：
    - ‘none’：不复权
    - ‘front’:前复权
    - ‘back’:后复权
    - ‘front_ratio’: 等比前复权
    - ‘back_ratio’: 等比后复权
- fill_data：停牌填充方式，默认为True（暂不可用）
- subscribe：订阅数据开关，默认为True，设置为False时不做数据订阅，只读取本地已有数据

返回：

- {code1: data1, code2: data2, …}
    - code：str，合约代码
    - data：pd.DataFrame，数据集，index为字符串格式的时间序列，columns为数据字段

示例：

```python
def handlebar(ContextInfo):
	if not ContextInfo.is_last_bar():
		return
	data = ContextInfo.get_market_data_ex(['open', 'high', 'low', 'close'], ['000300.SH'], period='1d', start_time='',
										  end_time='', count=-1, dividend_type='follow', fill_data=True, subscribe=True)

```

#### （19）获取分笔数据 ContextInfo.get_full_tick()

用法： ContextInfo.get_full_tick(stock_code=[])

释义： 获取最新分笔数据

参数：

- stock_code：number，默认参数，合约代码列表，如[’600000.SH’,’600036.SH’]，不指定时为当前主图合约。

返回： 根据stock_code返回一个dict，该字典的key值是股票代码，其值仍然是一个dict，在该dict中存放股票代码对应的最新的数据。该字典数据key值有：

- lastPrice:最新价
- amount:成交额
- volume:成交总量（手）
- pvolume:成交总量（股）
- openInt:持仓量
- stockStatus:股票状态
- lastSettlementPrice:最新结算价
- open:开盘价
- high:最高价
- low:最低价
- settlementPrice:结算价
- lastClose:收盘价
- askPrice:列表,卖价五档
- bidPrice:列表,买价五档
- askVol:列表,卖量五档
- bidVol:列表,买量五档

示例：

```python
def handlebar(ContextInfo):
	if not ContextInfo.is_last_bar():
		return
	Result = ContextInfo.get_full_tick(['600000.SH', '000001.SZ'])

```

#### （20）获取除权除息日和复权因子 ContextInfo.get_divid_factors()

用法： ContextInfo.get_divid_factors(stock.market)

释义： 获取除权除息日和复权因子

参数： stock.market：股票代码.市场代码，如 ‘600000.SH’

返回： dict，除权除息日与复权因子的映射字典

示例：

```python
def handlebar(ContextInfo):
	Result = ContextInfo.get_divid_factors('600000.SH')

```

#### （21）获取当前期货主力合约 ContextInfo.get_main_contract()

用法： ContextInfo.get_main_contract(codemarket)

释义： 获取当前期货主力合约

参数： codemarket：合约和市场，合约格式为品种名，如IF.IF，zn.SF

返回： str，合约代码

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_main_contract('IF.IF'))

```

#### （22）将毫秒时间转换成日期时间 timetag_to_datetime()

用法： timetag_to_datetime(timetag, format)

释义： 将毫秒时间转换成日期时间

参数：

- timetag：毫秒时间，1512748800000
- Format：格式字符串，’%Y-%m-%d %H:%M:%S’ 等任意格式

返回： str，合约代码

示例：

```python
def handlebar(ContextInfo):
	print(timetag_to_datetime(1512748860000, '%Y%m%d %H:%M:%S'))

```

#### （23）获取总股数 ContextInfo.get_total_share()

用法： ContextInfo.get_total_share(stockcode)

释义： 获取总股数

参数： stockcode：string，股票代码，缺省值 ‘’，默认为当前图代码, 如：’600000.SH’

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_total_share('600000.SH'))

```

#### （24）获取指定个股 / 合约 / 指数的 K 线（交易日）列表 ContextInfo.get_trading_dates()

用法： ContextInfo.get_trading_dates(stockcode, start_date, end_date, count, period)

释义： 获取指定个股 / 合约 / 指数的 K 线（交易日）列表

参数：

- stockcode：string，股票代码，缺省值’’，默认为当前图代码，如 ‘600000.SH’
- start_date：string，开始时间，缺省值’’，为空时不使用，如 ‘20170101’，’20170101000000’
- end_date：string，结束时间，缺省值’’，默认为当前bar的时间，如 ‘20170102’，’20170102000000’
- count：int，K 线个数，必须大于 0，取包括 end_date 往前的 count 个 K 线，start_date 不为空时不使用
- period：string，K 线类型如下：
    - ‘1d’：日线
    - ‘1m’：1分钟线
    - ‘3m’：3分钟线
    - ‘5m’：5分钟线
    - ‘15m’：15分钟线
    - ‘30m’：30分钟线
    - ‘1h’：小时线
    - ‘1w’：周线
    - ‘1mon’：月线
    - ‘1q’：季线
    - ‘1hy’：半年线
    - ‘1y’：年线

> 注：可缺省参数：start_date，end_date

返回： List，K 线周期（交易日）列表，period为日线时返回 [’20170101’, ‘20170102’, …]，其它返回[’20170101010000’, ‘20170102020000’, …]

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_trading_dates('600000.SH', '20170101', '20170401', 1, '1d'))

```

#### （25）根据代码获取对应股票的内盘成交量 ContextInfo.get_svol()

用法： ContextInfo.get_svol(stockcode)

释义： 根据代码获取对应股票的内盘成交量

参数： stockcode：股票代码，如 ‘000001.SZ’，缺省值’’，默认为当前图代码

返回： string

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_svol('000001.SZ'))

```

#### （26）根据代码获取对应股票的外盘成交量 ContextInfo.get_bvol()

用法： ContextInfo.get_bvol(stockcode)

释义： 根据代码获取对应股票的外盘成交量

参数： stockcode：股票代码，如 ‘000001.SZ’，缺省值’’，默认为当前图代码

返回： string

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_bvol('000001.SZ'))

```

#### （27）获取龙虎榜数据 ContextInfo.get_longhubang()

用法： ContextInfo.get_longhubang(stock_list, startTime, endTime)

释义： 获取龙虎榜数据

参数：

- stock_list：股票列表，list，如 [’600000.SH’, ‘600036.SH’]
- startTime：起始时间，如 ‘20170101’
- endTime：结束时间，如 ‘20180101’

返回： Dataframe，字段：

- reason：上榜原因
- close：收盘价
- spreadRate：涨跌幅
- TurnoverVolune：成交量
- Turnover_Amount：成交金额
- buyTraderBooth：买方席位,datframe
- sellTraderBooth：卖方席位,datframe
- buyTraderBooth 或 sellTraderBooth 包含字段：
    - traderName：交易营业部名称
    - buyAmount：买入金额
    - buyPercent：买入金额占总成交占比
    - sellAmount：卖出金额
    - sellPercent：卖出金额占总成交占比
    - totalAmount：该席位总成交金额
    - rank：席位排行
    - direction：买卖方向

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_longhubang(['000002.SZ'], '20100101', '20180101'))

```

#### （28）获取十大股东数据 ContextInfo.get_top10_share_holder()

用法： get_top10_share_holder(self, stock_list, data_name, start_time, end_time)

释义： 获取十大股东数据

参数：

- data_name：flow_holder 或 holder
- stock_list：股票列表，list，如[’600000.SH’, ‘600036.SH’]
- startTime：起始时间，如 ‘20170101’
- endTime：结束时间，如 ‘20180101’

返回：

- series（一只股票一个季度）
- dataframe（多只股票一个季度数据或者一只股票多个季度数据）
- panel（多只股票多个季度）
  字段
    - holdName：股东名称
    - holderType：持股类型
    - holdNum：持股数量,
    - changReason：变动原因
    - holdRatio：持股比例
    - stockType：股份性质
    - rank：持股排名
    - status：持股状态
    - changNum：增减数量
    - changeRatio：增减比例

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_top10_share_holder(['000002.SZ'], 'flow_holder', '20100101', '20180101'))

```

#### （29）获取指定期权品种的详细信息 ContextInfo.get_option_detail_data()

用法： ContextInfo.get_option_detail_data(optioncode)

释义： 获取指定期权品种的详细信息

参数：

- optioncode：期权代码,如’10001506.SHO’,当填写空字符串时候默认为当前主图的期权品种

返回： 根据optioncode返回一个dict，该字典数据key值有：

- ExchangeID：期权市场代码
- InstrumentID：期权代码
- ProductID：期权标的的产品ID
- OpenDate：发行日期
- ExpireDate：到期日
- PreClose：前收价格
- SettlementPrice：前结算价格
- UpStopPrice：当日涨停价
- DownStopPrice：当日跌停价
- LongMarginRatio：多头保证金率
- ShortMarginRatio：空头保证金率
- PriceTick：最小变价单位
- VolumeMultiple：合约乘数
- MaxMarketOrderVolume：涨跌停价最大下单量
- MinMarketOrderVolume：涨跌停价最小下单量
- MaxLimitOrderVolume：限价单最大下单量
- MinLimitOrderVolume：限价单最小下单量
- OptUnit：期权合约单位
- MarginUnit：期权单位保证金
- OptUndlCode：期权标的证券代码
- OptUndlMarket：期权标的证券市场
- OptExercisePrice：期权行权价
- NeeqExeType：全国股转转让类型
- OptUndlRiskFreeRate：期权标的无风险利率
- OptUndlHistoryRate：期权标的历史波动率
- EndDelivDate：期权行权终止日
- optType：期权类型,CALL或PUT

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_option_detail_data('10001506.SHO'))

```

#### （30）获取一篮子证券编码数据 ContextInfo.load_stk_list()

用法： ContextInfo.load_stk_list(filePath，fileName)

释义： 获取一篮子证券编码数据

txt文件信息格式：600000.SH,600004.SH,600006.SH,或600000.SH600004.SH600006.SH(最后一个字段600006.SH需要增加分隔符)

csv文件信息格式：600000.SH,600004.SH,600006.SH,(最后一个600006.SH需要增加分隔符)

参数：

- filePath：文件路径
- fileName：文件名(比如：a.txt,b.csv)

返回： 返回文档内容

示例：

```python
def handlebar(ContextInfo):
	ContextInfo.load_stk_list('D:/data/', 'list.txt')

```

#### （31）获取一篮子证券编码及数量数据ContextInfo.load_stk_vol_list()

用法： ContextInfo.load_stk_vol_list(filePath，fileName)

释义： 获取一篮子证券编码及数量数据

txt文件信息格式：600000.SH,100,600004.SH,200,或600000.SH100600004.SH200(篮子数据成对存在(前面是合约代码，后面是数量)
且数量字段200后需要增加分隔符)

csv文件信息格式：600000.SH,100,600004.SH,200,(篮子数据成对存在(前面是合约代码，后面是数量)且数量字段200后需要增加分隔符)

参数：

- filePath：文件路径
- fileName：文件名(比如：a.txt,b.csv)

返回： 返回文档内容

示例：

```python
def handlebar(ContextInfo):
	ContextInfo.load_stk_vol_list('D:/data/', 'list.txt')

```

#### （32）获取本地行情数据 ContextInfo.get_local_data()

用法：
ContextInfo.get_local_data(stock_code,start_time=’’,end_time=’’,period=’1d’,divid_type=’none’,count=-1)

释义： 获取本地行情数据

参数：

- stock_code：默认参数，合约代码code.market不指定时为当前图合约
- start_time：默认参数，开始时间，格式’20171209’或’20171209010101’
- end_time：默认参数，结束时间，格式同start_time
- period：string，默认参数，，K线类型，可选值：
    - ‘tick’：分笔线（只用于获取’quoter’字段数据）
    - ‘realtime’：实时线
    - ‘1d’：日线
    - ‘md’：多日线
    - ‘1m’：1分钟线
    - ‘3m’：3分钟线
    - ‘5m’：5分钟线
    - ‘15m’：15分钟线
    - ‘30m’：30分钟线
    - ‘mm’：多分钟线
    - ‘1h’：小时线
    - ‘mh’：多小时线
    - ‘1w’：周线
    - ‘1mon’：月线
    - ‘1q’：季线
    - ‘1hy’：半年线
    - ‘1y’：年线
- dividend_type：默认参数，number，除复权，可选值：
    - ‘none’：不复权
    - ‘front’：向前复权
    - ‘back’：向后复权
    - ‘front_ratio’：等比向前复权
    - ‘back_ratio’：等比向后复权
-
count：默认参数，大于等于0时，若指定了start_time，end_time，此时以end_time为基准向前取count条；若start_time，end_time缺省，默认取本地数据最新的count条数据；若start_time，end_time，count都缺省时，默认取本地全部数据。

特别的，默认参数需带上参数名方可生效，调用方式与python别无二致。

返回： 返回一个dict，键值为timetag，value为另一个dict(valuedict)

- period=’tick’时函数获取分笔数据，valuedict字典数据key值有：
    - lastPrice：最新价
    - amount：成交额
    - volume：成交量
    - pvolume：前成交量
    - openInt：持仓量
    - stockStatus：股票状态
    - lastSettlementPrice：最新结算价
    - open：开盘价
    - high：最高价
    - low：最低价
    - settlementPrice：结算价
    - lastClose：收盘价
    - askPrice：列表,卖价五档
    - bidPrice：列表,买价五档
    - askVol：列表,卖量五档
    - bidVol：列表,买量五档
- period为其他值时，valuedict字典数据key值有：
    - amount：成交额
    - volume：成交量
    - open：开盘价
    - high：最高价
    - low：最低价
    - close：收盘价

> 注：时间区间两边闭区间

示例：

```python
def handlebar(ContextInfo):
	Result = ContextInfo.get_local_data(stock_code='600000.SH', start_time='20170101', end_time='20170102', period='1d',
										divid_type='none')

```

#### （33）获取换手率 ContextInfo.get_turnover_rate()

用法：ContextInfo.get_turnover_rate(stock_list,startTime,endTime)

释义： 获取换手率

参数：

- stock_list：股票列表，list,如[’600000.SH’,’000001.SZ’]
- startTime：起始时间，如’20170101’
- endTime：结束时间，如’20180101’

返回： dataframe

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_turnover_rate(['000002.SZ'], '20170101', '20180101'))

```

#### （34）根据ETF基金代码获取ETF申赎清单及对应成分股数据 get_etf_info()

用法： get_etf_info(stockcode)

释义： 根据ETF基金代码获取ETF申赎清单及对应成分股数据

参数：

- stockcode：ETF基金代码（如”510050.SH”）

返回： 返回一个dict，键值为timetag，value为另一个dict(valuedict)

- etfCode：ETF代码
- etfExchID：ETF市场
- prCode：基金申赎代码
- cashBalance：现金差额（单位：元）
- maxCashRatio：现金替代比例上限
- reportUnit：最小申购、赎回单位（单位：份）
- name：基金名称
- navPerCU：最小申购、赎回单位净值（单位：元）
- nav：基金份额净值（单位：元）
- ecc：预估现金差额（单位：元）
- needPublish：是否需要公布IOPV（1：是，0：否）
- enableCreation：是否允许申购（1：是，0：否）
- enableRedemption：是否允许赎回（1：是，0：否）
- creationLimit：申购上限（单位:份，0：不限制）
- redemptionLimit：赎回上限（单位:份，0：不限制）
- tradingDay：交易日期（格式YYYYMMDD）
- preTradingDay：前交易日期（格式YYYYMMDD）
- stocks：成分股列表
- exchangeID：ETF基金市场代码
- etfCode：ETF基金代码
- etfName：ETF基金名称
- componentExchID：成份股市场代码
- componentCode：成份股代码
- componentName：成份股名称
- componentVolume：成份股数量
- ReplaceFlag：替代标记(48：禁止替代，49：允许替代，50：必须替代，51：替补替代)
- ReplaceRatio：溢价比率
- ReplaceBalance：替代金额

示例：

```python
get_etf_info("510050.SH")  # 获取ETF基金代码为511050的全部ETF申赎清单数据

```

#### （35）根据ETF基金代码获取ETF的基金份额参考净值 get_etf_iopv()

用法： get_etf_iopv(stockcode)

释义： 根据ETF基金代码获取ETF的基金份额参考净值

参数：

- stockcode：ETF基金代码（如”510050.SH”）

返回： IOPV，基金份额参考净值

示例：

```python
get_etf_iopv("510050.SH")

```

#### （36）根据代码获取合约详细信息 ContextInfo.get_instrumentdetail()

用法： ContextInfo.get_instrumentdetail(stockcode)

释义： 根据代码获取合约详细信息

参数：

- stockcode：string，股票代码，如’600000.SH’

返回： 根据stockcode返回一个dict，该字典数据key值有：

- ExchangeID：合约市场代码
- InstrumentID：合约代码
- InstrumentName：合约名称
- ProductID：合约的品种ID(期货)
- ProductName：合约的品种名称(期货)
- CreateDate：上市日期(期货)
- OpenDate：IPO日期(股票)
- ExpireDate：退市日或者到期日
- PreClose：前收盘价格
- SettlementPrice：前结算价格
- UpStopPrice：当日涨停价
- DownStopPrice：当日跌停价
- FloatVolumn：流通股本
- TotalVolumn：总股本
- LongMarginRatio：多头保证金率
- ShortMarginRatio：空头保证金率
- PriceTick：最小变价单位
- VolumeMultiple：合约乘数(对期货以外的品种，默认是1)
- MainContract：主力合约标记
- LastVolume：昨日持仓量
- InstrumentStatus：合约停牌状态
- IsTrading：合约是否可交易
- IsRecent：是否是近月合约

示例：

```python
def handlebar(ContextInfo):
	print
	ContextInfo.get_instrumentdetail('600000.SH')

```

#### （37）获取期货合约到期日 ContextInfo.get_contract_expire_date()

用法： ContextInfo.get_contract_expire_date(codemarket)

释义： 获取期货合约到期日

参数：

- Codemarket：合约和市场，如IF00.IF，zn00.SF

返回： int，合约到期日

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_contract_expire_date('IF00.IF'))

```

#### （38）获取指定期权标的对应的期权品种列表 ContextInfo.get_option_undl_data()

用法： ContextInfo.get_option_undl_data(undl_code_ref)

**释义：** 获取指定期权标的对应的期权品种列表

参数：

- undl_code_ref：期权标的代码,如’510300.SH’，传空字符串时获取全部标的数据

返回：

- list，指定期权标的代码时返回对应该标的的期权合约列表
- dict，期权标的代码为空字符串时返回全部标的对应的品种列表的字典

示例：

```python
def handlebar(ContextInfo):
	data = ContextInfo.get_option_undl_data('510300.SH')
	print(data)

```

#### （39）查询两融最大可下单量 query_credit_opvolume()

用法： query_credit_opvolume(accountId ,stockCode, opType, prType, price, seq, ContextInfo);

释义：
本函数一次最多查询200只股票的两融最大下单量，且同时只能有一个查询，如果前面的查询正在进行中，后面的查询将会提前返回。注意，本函数从服务器查询数据，建议平均查询时间间隔30s一次，不可频繁调用。
须配合 credit_opvolume_callback() 函数使用

参数：

- accountId: 查询的两融账号
- stockCode: 需要查询的股票代码，stockCode为List的类型,可以查询多只股票
- opType: 两融下单类型，同passorder的下单类型
- prType: 报单价格类型，同passorder的报价类型,
- seq: 查询序列号，int型，建议输入唯一值以便对应结果回调
- price: 报价(非限价单可以填任意值)，如果stockCode为List类型，报价也需要为长度相同的List

示例：

```python
def handlebar(ContextInfo):
	# 查询accid账号担保品买入600000.SH限价10元的最大可下单量
	query_credit_opvolume(ContextInfo.accid, '600000.SH', 33, 11, 10, int(time.time()), ContextInfo)
	# 查询accid账号担保品买入600000.SH限价10元，000001.SZ担保品买入限价20元的最大可下单量
	query_credit_opvolume(ContextInfo.accid, ['600000.SH', '000001.SZ'], 33, 11, [10, 20], int(time.time()),
						  ContextInfo)

```

#### （40）查询两融最大可下单量的回调 credit_opvolume_callback()

用法： credit_opvolume_callback(ContextInfo, accid, seq, ret, result)

释义： 查询两融最大可下单量的回调，须配合 query_credit_opvolume()
函数使用

参数：

- ContextInfo：策略模型全局对象
- accid:查询的账号
- seq:query_credit_opvolume时输入查询seq
- ret:查询结果状态。正常返回:1,正在查询中-1,输入账号非法:-2,输入查询参数非法:-3,超时等服务器返回报错:-4
- result:查询到的结果

示例：

```python
def handlebar(ContextInfo):
	# 查询accid账号担保品买入600000.SH限价10元的最大可下单量
	query_credit_opvolume(ContextInfo.accid, '600000.SH', 33, 11, 10, int(time.time()), ContextInfo)


def credit_opvolume_callback(ContextInfo, accid, seq, ret, result):
	print(accid, seq, ret, result)

```

#### （41）获取多因子数据 ContextInfo.get_factor_data()

**注：** 除AI因子之外，其他数据可以取到的截止日期至2022年2月22日

用法1： ContextInfo.get_factor_data(fieldList, stockList, startDate, endDate)

释义： 获取多因子数据

参数：

- fieldList：字段列表，list，如：[’AI_MARKET_LEVEL_FORCAST.stk_p_ai’, ‘AI_MARKET_LEVEL_FORCAST.stk_sw1_p_ai’]
- stockList：代码列表，list，如： [‘600000.SH’, ‘000001.SZ’]
- startDate：开始时间，string，如：’20201209’
- endDate：结束时间，string，如：’20201212’

返回：

函数根据stockList代码列表,startDate,endDate时间范围的大小范围不同的数据类型

- 代码列表1-时间范围为1返回： pandas.Series index=字段

- 代码列表1-时间范围为n返回： pandas.DataFrame index=时间, columns=字段

- 代码列表n-时间范围为1返回： pandas.DataFrame index=代码 ,columns=字段

- 代码列表n-时间范围为n返回： dict Key=代码,value=df(index=日期, col=因子名)

示例：

```python
def handlebar(ContextInfo):
	fieldList = ['AI_MARKET_LEVEL_FORCAST.stk_p_ai', 'AI_MARKET_LEVEL_FORCAST.stk_sw1_p_ai']
	stockList = ['600000.SH', '000001.SZ']
	startDate = '20201209'
	endDate = '20201212'
	ContextInfo.get_factor_data(fieldList, stockList, startDate, endDate)

```

用法2： ContextInfo.get_factor_data(fieldList, stockCode, startDate, endDate)

释义： 获取多因子数据

参数：

- fieldList 字段列表，list，如：[’AI_MARKET_LEVEL_FORCAST.stk_p_ai’, ‘AI_MARKET_LEVEL_FORCAST.stk_sw1_p_ai’]
- stockCode：股票代码，string，如： ‘600000.SH’
- startDate：开始时间，string，如：’20201209’
- endDate：结束时间，string，如：’20201212’

返回：

函数根据startDate,endDate时间范围的大小范围不同的数据类型

- 时间范围为1返回： pandas.Series index=字段

- 时间范围为n返回： pandas.DataFrame index=时间, columns=字段

示例：

```python
def handlebar(ContextInfo):
	fieldList = ['AI_MARKET_LEVEL_FORCAST.stk_p_ai', 'AI_MARKET_LEVEL_FORCAST.stk_sw1_p_ai']
	stockCode = '600000.SH'
	startDate = '20201209'
	endDate = '20201212'
	ContextInfo.get_factor_data(fieldList, stockCode, startDate, endDate)

```

#### （42）获取过期ST数据 ContextInfo.get_his_st_data()

用法： ContextInfo.get_his_st_data(stockCode)

释义： 获取某只股票ST的历史

参数：

- stockCode：股票代码，string，如： ‘600000.SH’

返回：

- dict：st历史，key为ST, *ST ,PT ,历史未ST会返回{}

示例：

```python
def init(ContextInfo):
	#获取股票代码“000004.SZ”ST的历史
	print(ContextInfo.get_his_st_data('000004.SZ'))

```

#### （43）获取过期指数数据 ContextInfo.get_his_index_data()

用法： ContextInfo.get_his_index_data(index)

释义： 获取某只指数历史调整日的历史的成分股列表,需要下载历史数据

参数：

- index：指数代码，string，如： ‘000300.SH’

返回：

- dict：st历史，key为ST, *ST ,PT ,历史未ST会返回{}

示例：

```python
def init(ContextInfo):
	# 获取沪深300函数历次调整时的指数成分列表，计算对应权重可以进一步取历史股本进行计算
	print(ContextInfo.get_his_index_data('000300.SH'))

```

#### （44）订阅行情数据 ContextInfo.subscribe_quote()

用法： ContextInfo.subscribe_quote(stock_code, period=’follow’, dividend_type=’follow’, callback=None)

释义： 订阅某个代码的行情数据，在策略盘中运行时，多只代码时用 handlebar 驱动（主图代码的 tick 行情驱动）不太够，存在主图代码
tick 来了而其它代码 tick 还没更新的情况，通过此函数可以在某只代码行情更新后立即执行。支持订阅level-2特色指标快照，该项接口需要额外开通level-2增强版权限。

参数：

- stock_code：string，形式如 ‘stkcode.market’，如 ‘600000.SH’
- period：str，周期，默认为’follow’，为当前主图周期，可选范围：
    - ‘tick’：分笔数据
    - ‘1m’、’5m’、’15m’ 等分钟周期
    - ‘1d’：日线数据
    - ‘l2quoteaux’：Level2 行情快照指标
    - ‘l2transactioncount’：Level2 大单统计
- dividend_type：复权方式，默认为’follow’，为当前主图复权方式（分笔周期返回数据均为不复权），可选范围：
    - ‘none’：不复权
    - ‘front’:前复权
    - ‘back’:后复权
    - ‘front_ratio’: 等比前复权
    - ‘back_ratio’: 等比后复权
- callback：数据推送回调

示例：

```python
def on_quote(datas):
	print(datas)

```

datas：{code: data}

- code：合约代码
- data：pd.DataFrame，数据集，index为字符串格式的时间序列，columns为数据字段

返回：

- int，订阅号，可用 unsubscribe_quote 做反订阅

示例：

```python
def on_quote(datas):
	print(datas)

	ContextInfo.subscribe_quote('000300.SH', '1d', 'follow', on_quote)

```

#### （45）反订阅行情数据 ContextInfo.unsubscribe_quote()

用法： ContextInfo.unsubscribe_quote(subId)

释义： 反订阅行情数据

参数：

- subId：行情订阅返回的订阅号

返回：

- 无

示例：

```python
ContextInfo.unsubscribe_quote(subId)

```

#### （46）获取当前所有的行情订阅信息 ContextInfo.get_all_subscription()

用法： ContextInfo.get_all_subscription()

释义： 获取当前所有的行情订阅信息

参数：

- 无

返回：

- dict：”stockCode”：合约代码，”period”：周期，”dividendType”：除权方式

示例：

```python
data = ContextInfo.get_all_subscription()
print(data)

```

#### （47）获取指定期权列表 ContextInfo.get_option_list()

用法： ContextInfo.get_option_list(undl_code, dedate,
opttype, isavailable)

释义： 获取指定期权列表

*注：获取历史期权需要下载过期合约列表

参数：

- undl_code：期权标的代码,如’510300.SH’
- dedate：期权到期月或当前交易日期，”YYYYMM” 格式为期权到期月，”YYYYMMDD” 格式为获取当前日期交易的期权
- opttype：期权类型,默认值为空,如”CALL”，”PUT”，为空时认购认沽都取。
- isavailable：是否可交易,当 dedate 的格式为 “YYYYMMDD” 格式为获取当前日期交易的期权时，isavailable 为 True
  时返回当前可用，为False时返回当前和历史可用

返回：

list, 期权合约代码列表

示例：

```python
# 获取到期月份为202101的上交所510300ETF认购合约
data = ContextInfo.get_option_list('510300.SH', '202101', "CALL")
# 获取20210104当天上交所510300ETF可交易的认购合约
data = ContextInfo.get_option_list('510300.SH', '20210104', "CALL", True)
# 获取20210104当天上交所510300ETF已经上市的认购合约(包括退市)
data = ContextInfo.get_option_list('510300.SH', '20210104', "CALL", False)

```

#### （48）获取指定市场过期合约列表 ContextInfo.get_his_contract_list()

用法： ContextInfo.get_his_contract_list(market)

释义： 获取指定市场过期合约列表

*注：获取过期合约需要手动补充过期合约列表

参数：

- market: 市场, 如 SH, SZ, SHO, SZO, IF 等

返回：

list, 期权合约代码列表

示例：

```python
def handlebar(ContextInfo):
	# 获取中金所过期合约列表
	print(ContextInfo.get_his_contract_list('IF'))
	# 获取深交所期权过期合约列表
	print(ContextInfo.get_his_contract_list('SHO'))

```

#### （49）获取指定期权品种的实时隐含波动率 ContextInfo.get_option_iv()

用法： ContextInfo.get_option_iv(optioncode)

释义： 获取股票期权的实时隐含波动率

参数：

- optioncode：期权代码，如 ‘10003280.SHO’

返回：double

示例：

```python
def handlebar(ContextInfo):
	print(ContextInfo.get_option_iv('10003280.SHO'))

```

#### （50）基于BS模型计算欧式期权理论价格 ContextInfo.bsm_price()

用法： ContextInfo.bsm_price(optionType, objectPrices, strikePrice, riskFree, sigma, days, dividend)

释义： 基于 Black-Scholes-Merton 模型，输入期权标的价格、期权行权价、无风险利率、期权标的年化波动率、剩余天数、标的分红率、计算期权的理论价格

参数：

- optionType：期权类型，认购：’C’，认沽：’P’
- objectPrices：期权标的价格，可以是价格列表或者单个价格
- strikePrice：期权行权价
- riskFree：无风险收益率
- sigma：标的波动率
- days：剩余天数
- dividend：分红率

返回：

- objectPrices 为 float 时，返回 float
- objectPrices 为 list 时，返回 list

计算结果最小值0.0001，结果保留4位小数，输入非法参数返回 nan

示例：

```python
import numpy as np

object_prices = list(np.arange(3, 4, 0.01))
# 计算剩余15天的行权价3.5的认购期权,在无风险利率3%,分红率为0,标的年化波动率为23%时标的价格从3元到4元变动过程中期权理论价格序列
prices = ContextInfo.bsm_price('C', object_prices, 3.5, 0.03, 0.23, 15, 0)
print(prices)
# 计算剩余15天的行权价3.5的认购期权,在无风险利率3%,分红率为0,标的年化波动率为23%时标的价格为3.51元的平值期权的理论价格
price = ContextInfo.bsm_price('C', 3.51, 3.5, 0.03, 0.23, 15, 0)
print(price)

```

#### （51）基于BS模型计算欧式期权隐含波动率 ContextInfo.bsm_iv()

用法： ContextInfo.bsm_iv(optionType, objectPrices, strikePrice, optionPrice, riskFree, days, dividend)

释义： 基于 Black-Scholes-Merton
模型，输入期权标的价格、期权行权价、期权现价、无风险利率、剩余天数、标的分红率,计算期权的隐含波动率

参数：

- optionType：期权类型，认购：’C’，认沽：’P’
- objectPrice：期权标的价格
- strikePrice：期权行权价
- optionPrice：期权现价
- riskFree：无风险收益率
- days：剩余天数
- dividend：分红率

返回： double

示例：

```python
# 计算剩余15天的行权价3.5的认购期权,在无风险利率3%,分红率为0时,标的现价3.51元,期权价格0.0725元时的隐含波动率
iv = ContextInfo.bsm_iv('C', 3.51, 3.5, 0.0725, 0.03, 15)
print(iv)

```

公式：

### 3.2.4. 交易函数

交易函数下单跟界面人工点击下单走的下单、风控流程是一样的，唯一的区别是：交易函数下单通过解析下单函数接口传过来的参数，形成相应的下单任务；而界面人工点击下单通过解析界面的输入、选择，形成相应的下单任务。

运作流程：

（1）编写测试策略

（2）运行策略

（3）触发下单，解析参数

（4）生成任务

（5）形成委托，过风控

（6）成交

#### 3.2.4.1. 交易函数基本信息

QMT 平台提供了一系列的 Python 下单函数接口，如下所示。

*注：在回测模式中，交易函数调用虚拟账号进行交易，在历史 K
线上记录买卖点，用以计算策略净值/回测指标；实盘运行调用策略中设置的资金账号进行交易，产生实际委托；模拟运行模式下交易函数无效。其中，can_cancel_order,
cancel_task, cancel和do_order交易函数在回测模式中无实际意义，不建议使用。

（1）交易函数

| 函数名                     | 释义                |
|-------------------------|-------------------|
| `passorder`             | `综合交易下单`          |
| `smart_algo_passorder`  | `智能算法交易`          |
| `get_trade_detail_data` | `取交易细明数据函数`       |
| `get_value_by_order_id` | `根据委托Id取委托或成交信息`  |
| `get_last_order_id`     | `获取最新的委托或成交的委托Id` |
| `can_cancel_order`      | `查询委托是否可撤销`       |
| `cancel`                | `取消委托`            |
| `cancel_task`           | `撤销任务`            |
| `pause_task`            | `暂停任务`            |
| `resume_task`           | `继续任务`            |
| `do_order`              | `实时触发前一根bar信号函数`  |

（2）股票下单函数

| 函数名                    | 释义       |
|------------------------|----------|
| `order_lots`           | `指定手数交易` |
| `order_value`          | `指定价值交易` |
| `order_percent`        | `一定比例下单` |
| `order_target_value`   | `目标价值下单` |
| `order_target_percent` | `目标比例下单` |
| `order_shares`         | `指定股数交易` |

（3）期货下单函数

| 函数名 | 释义 |

| `buy_open` | `买入开仓` |
| `sell_close_tdayfirst` | `卖出平仓，平今优先` |
| `sell_close_ydayfirst` | `卖出平仓，平昨优先` |
| `sell_open` | `卖出开仓` |
| `buy_close_tdayfirst` | `买入平仓，平今优先` |
| `buy_close_ydayfirst` | `买入平仓，平昨优先` |

#### 3.2.4.2. 交易函数介绍

#### （1）综合交易下单 passorder()

用法： passorder(opType, orderType, accountid, orderCode, prType, modelprice,
volume[, strategyName, quickTrade, userOrderId], ContextInfo)

释义： 综合交易下单

参数：

- opType，操作类型，可选值：
    - 期货六键：
        - 0：开多
        - 1：平昨多
        - 2：平今多
        - 3：开空
        - 4：平昨空
        - 5：平今空
    - 期货四键：
        - 6：平多,优先平今
        - 7：平多,优先平昨
        - 8：平空,优先平今
        - 9：平空,优先平昨
    - 期货两键：
        - 10：卖出,如有多仓,优先平仓,优先平今,如有余量,再开空
        - 11：卖出,如有多仓,优先平仓,优先平昨,如有余量,再开空
        - 12：买入,如有空仓,优先平仓,优先平今,如有余量,再开多
        - 13：买入,如有空仓,优先平仓,优先平昨,如有余量,再开多
        - 14：买入,不优先平仓
        - 15：卖出,不优先平仓
    - 股票买卖：
        - 23：股票买入，或沪港通、深港通股票买入
        - 24：股票卖出，或沪港通、深港通股票卖出
    - 融资融券：
        - 27：融资买入
        - 28：融券卖出
        - 29：买券还券
        - 30：直接还券
        - 31：卖券还款
        - 32：直接还款
        - 33：信用账号股票买入
        - 34：信用账号股票卖出
    - 组合交易：
        - 25：组合买入，或沪港通、深港通的组合买入
        - 26：组合卖出，或沪港通、深港通的组合卖出
        - 27：融资买入
        - 28：融券卖出
        - 29：买券还券
        - 31：卖券还款
        - 33：信用账号股票买入
        - 34：信用账号股票卖出
        - 40：期货组合开多
        - 43：期货组合开空
        - 46：期货组合平多,优先平今
        - 47：期货组合平多,优先平昨
        - 48：期货组合平空,优先平今
        - 49：期货组合平空,优先平昨
    - 期权交易：
        - 50：买入开仓
        - 51：卖出平仓
        - 52：卖出开仓
        - 53：买入平仓
        - 54：备兑开仓
        - 55：备兑平仓
        - 56：认购行权
        - 57：认沽行权
        - 58：证券锁定
        - 59：证券解锁
- orderType，下单方式

> 注：
>
> 一、期货不支持 1102 和 1202
>
> 二、对所有账号组的操作相当于对账号组里的每个账号做一样的操作，如 passorder(23, 1202, ‘testS’, ‘000001.SZ’, 5, -1, 50000,
> ContextInfo)，意思就是对账号组 testS 里的所有账号都以最新价开仓买入 50000 元市值的 000001.SZ
> 平安银行；passorder(60,1101,”test”,’510050.SH’,5,-1,1,ContextInfo)意思就是账号test申购1个单位(900000股)的华夏上证50ETF(
> 只申购不买入成分股)。

可选值：

- 1101：单股、单账号、普通、股/手方式下单
- 1102：单股、单账号、普通、金额（元）方式下单（只支持股票）
- 1113：单股、单账号、总资产、比例 [0 ~ 1] 方式下单
- 1123：单股、单账号、可用、比例[0 ~ 1]方式下单
- 1201：单股、账号组（无权重）、普通、股/手方式下单
- 1202：单股、账号组（无权重）、普通、金额（元）方式下单（只支持股票）
- 1213：单股、账号组（无权重）、总资产、比例 [0 ~ 1] 方式下单
- 1223：单股、账号组（无权重）、可用、比例 [0 ~ 1] 方式下单
- 2101：组合、单账号、普通、按组合股票数量（篮子中股票设定的数量）方式下单 > 对应 volume 的单位为篮子的份
- 2102：组合、单账号、普通、按组合股票权重（篮子中股票设定的权重）方式下单 > 对应 volume 的单位为元
- 2103：组合、单账号、普通、按账号可用方式下单 >（底层篮子股票怎么分配？答：按可用资金比例后按篮子中股票权重分配，如用户没填权重则按相等权重分配）只对股票篮子支持
- 2201：组合、账号组（无权重）、普通、按组合股票数量方式下单
- 2202：组合、账号组（无权重）、普通、按组合股票权重方式下单
- 2203：组合、账号组（无权重）、普通、按账号可用方式下单只对股票篮子支持

- 组合套利交易接口特殊设置（accountID、orderType 特殊设置）

passorder(opType, orderType, accountID, orderCode, prType, hedgeRatio, volume, ContextInfo)

    accountID = ‘stockAccountID, futureAccountID’
    
    orderCode = ‘basketName, futureName’
    
    hedgeRatio：套利比例（0 ~ 2 之间值，相当于 %0 至 200% 套利）
    volume：份数 \ 资金 \ 比例

    orderType（特殊设置）

orderType 可选值：

- 2331：组合、套利、合约价值自动套利、按组合股票数量方式下单
- 2332：组合、套利、按合约价值自动套利、按组合股票权重方式下单
- 2333：组合、套利、按合约价值自动套利、按账号可用方式下单

- accountID，资金账号

passorder(opType, orderType, accountID, orderCode, prType, price, volume, ContextInfo)

> 注：下单的账号ID（可多个）或账号组名或套利组名（一个篮子一个套利账号，如 accountID = ‘股票账户名, 期货账号’）

- orderCode，下单代码

passorder(opType, orderType, accountID, orderCode, prType, price, volume, ContextInfo)

> 注：
>
> 一、如果是单股或单期货、港股，则该参数填合约代码；
>
> 二、如果是组合交易,则该参数填篮子名称；
>
> 三、如果是组合套利，则填一个篮子名和一个期货合约名（如orderCode = ‘篮子名, 期货合约名’）

- prType，下单选价类型

passorder(opType, orderType, accountID, orderCode, prType, price, volume, ContextInfo)

可选值（特别的对于套利，这个 prType 只对篮子起作用，期货的采用默认的方式）：

> 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。

- -1：无效（实际下单时,需要用交易面板交易函数那设定的选价类型）
- 0：卖5价
- 1：卖4价
- 2：卖3价
- 3：卖2价
- 4：卖1价
- 5：最新价
- 6：买1价
- 7：买2价（组合不支持）
- 8：买3价（组合不支持）
- 9：买4价（组合不支持）
- 10：买5价（组合不支持）
- 11：（指定价）模型价（只对单股情况支持,对组合交易不支持）
- 12：涨跌停价
- 13：挂单价
- 14：对手价
- 27：市价即成剩撤(仅对股票期权申报有效)
- 28：市价即全成否则撤(仅对股票期权申报有效)
- 29：市价剩转限价(仅对股票期权申报有效)
- 42：最优五档即时成交剩余撤销申报(仅对上交所申报有效)
- 43：最优五档即时成交剩转限价申报(仅对上交所申报有效)
- 44：对手方最优价格委托(仅对深交所申报有效)
- 45：本方最优价格委托(仅对深交所申报有效)
- 46：即时成交剩余撤销委托(仅对深交所申报有效)
- 47：最优五档即时成交剩余撤销委托(仅对深交所申报有效)
- 48：全额成交或撤销委托(仅对深交所申报有效)
- 49：科创板盘后定价

- price，下单价格

passorder(opType, orderType, accountID, orderCode, prType, price, volume, ContextInfo)

> 注：
>
> 一、单股下单时，prType 是模型价/科创板盘后定价时 price 有效；其它情况无效；即单股时， prType
> 参数为 11，49 时被使用。 prType 参数不为 11，49 时也需填写，填写的内容可为
> -1，0，2，100 等任意数字；
>
> 二、组合下单时，是组合套利时，price 作套利比例有效，其它情况无效。

- volume，下单数量（股 / 手 / 元 / %）

passorder(opType, orderType, accountID, orderCode, prType, price, volume, ContextInfo)

根据 orderType 值最后一位确定 volume 的单位：

单股下单时：

1：股 / 手
2：金额（元）
3：比例（%）

组合下单时：

1：按组合股票数量（份）
2：按组合股票权重（元）
3：按账号可用（%）

- strategyName，string，自定义策略名，可缺省不写，用来区分 order 委托和 deal
  成交来自不同的策略。根据该策略名，get_trade_detail_data，get_last_order_id
  函数可以获取相应策略名对应的委托或持仓结果。

> 注：strategyName 只对同账号本地客户端有效，即 strategyName
> 只对当前客户端下的单进行策略区分，且该策略区分只能当前客户端使用。

- quickTrade，int，设定是否立即触发下单（回测时无效），可选值：

0：否
1：是

>
注：passorder是对最后一根K线完全走完后生成的模型信号在下一根K线的第一个tick数据来时触发下单交易；采用quickTrade参数设置为1时，非历史bar上执行时（ContextInfo.is_last_bar()
为True），只要策略模型中调用到就触发下单交易。quickTrade参数设置为2时，不判断bar状态，只要策略模型中调用到就触发下单交易，历史bar上也能触发下单，请谨慎使用。

- userOrderId，string，用户自设委托 ID，可缺省不写，写的时候必须把起前面的 strategyName 和 quickTrade 参数也填写。对应 order
  委托对象和 deal 成交对象中的 m_strRemark 属性，通过 get_trade_detail_data 函数或委托主推函数 order_callback 和成交主推函数
  deal_callback 可拿到这两个对象信息。

- userOrderParam，string，用户自定义交易参数模板名称，可缺省不写，写的时候必须把起前面的strategyName和quickTrade参数也填写。

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 单股单账号期货最新价买入 10 手
	passorder(0, 1101, 'test', target, 5, -1, 10, ContextInfo)

	# 单股单账号期货指定价买入 10 手
	passorder(0, 1101, 'test', target, 11, 3000, ContextInfo)

	# 单股单账号股票最新价买入 100 股（1 手）
	passorder(23, 1101, 'test', target, 5, 0, 100, ContextInfo)

	# 单股单账号股票指定价买入 100 股（1 手）
	passorder(23, 1101, 'test', target, 11, 7, 100, ContextInfo)

```

#### （2）算法交易下单 algo_passorder()

用法： algo_passorder(opType, orderType, accountid, orderCode, prType, modelprice,
volume[, strategyName, quickTrade, userOrderId, userOrderParam], ContextInfo)

释义： 算法交易下单，此时使用交易面板 - 程序交易 - 函数交易 - 函数交易参数中设置的下单类型（普通交易，算法交易，随机量交易）
如果函数交易参数使用未修改的默认值，此函数和 passorder 函数一致，设置了函数交易参数后，将会使用函数交易参数的超价等拆单参数，如果入参的
prType = -1，同时将会使用函数交易参数的报价方式。

参数：

- opType，操作类型，同 passorder 中的 opType
- orderType，下单方式，同 passorder 中的 orderType
- accountID，下单的账号 ID，同 passorder 中的 accountID
- orderCode，下单代码：同 passorder 中的 orderCode
- prType，报价类型，同 passorder 中的报价类型 prType，特别的，当 prType = -1 时，使用函数交易面板中的报价类型参数
- price，下单价格，同 passorder 中的 price 参数
- volume，下单量，同 passorder 中的 volume 参数
- strategyName，策略名，同 passorder 中的 strategyName 参数
- quickTrade，是否快速交易，同passorder中的 quickTrade 参数
- userOrderId，投资备注，同 passorder 中的 userOrderId 参数
- userOrderParam，字典类型，用户自定义交易参数，主要用于修改算法交易的参数
    - OrderType 普通交易：0，算法交易：1，随机量交易：2
    - PriceType 报价方式：数值同 pyType
    - MaxOrderCount 最大下单次数
    - SinglePriceRange 波动区间是否单向 否：0，是：1
    - PriceRangeType 波动区间类型 按比例：0，按数值：1
    - PriceRangeValue 波动区间（按数值）
    - PriceRangeRate 波动区间（按比例）[0 - 1]
    - SuperPriceType 单笔超价类型 按比例：0，按数值：1
    - SuperPriceRate 单笔超价（按比例）[0-1]
    - SuperPriceValue 单笔超价（按数值）
    - VolumeType 单笔基准量类型（与界面列表的序号一致）卖1+2+3+4+5量：0，卖1+2+3+4量：1，…目标剩余量：11
    - VolumeRate 单笔下单比率
    - SingleNumMin 单笔下单量最小值
    - SingleNumMax 单笔下单量最大值
    - ValidTimeElapse 有效持续时间
    - UndealtEntrustRule 未成委托处理数值同 pyType
    - PlaceOrderInterval 下撤单时间间隔
    - UseTrigger 是否触价 否：0，是：1
    - TriggerType 触价类型 最新价大于：0，最新价小于：2
    - TriggerPrice 触价价格

示例：

```python
def handlebar(ContextInfo):
	# 表示设置交易类型为算法交易，最大委托次数为20，下撤单时间间隔15s，其他参数同函数交易参数中设置
	userparam = {"OrderType": 1, "MaxOrderCount": 20, 'PlaceOrderInterval': 15}
	algo_passorder(23, 1101, '918800000818', '000001.SZ', 11, 21, 200, 'name', 2, 'algo_passorder_test', userparam,
				   ContextInfo)

```

#### （3）智能算法交易 smart_algo_passorder()

用法： smart_algo_passorder（opType, orderType, accountid, orderCode, prType, modelprice, volume, smartAlgoType,
limitOverRate, minAmountPerOrder, [targetPriceLevel], ContextInfo）
释义： 智能算法交易

参数：

- opType，操作类型，可选值：
    - 股票买卖：
        - 23：股票买入，或沪港通、深港通股票买入
        - 24：股票卖出，或沪港通、深港通股票卖出
    - 融资融券：
        - 27：融资买入
        - 28：融券卖出
        - 29：买券还券
        - 30：直接还券
        - 31：卖券还款
        - 32：直接还款
        - 33：信用账号股票买入
        - 34：信用账号股票卖出
- orderType，下单方式
    - 可选值：
        - 1101：单股、单账号、普通、股/手方式下单
        - 1102：单股、单账号、普通、金额（元）方式下单（只支持股票）
        - 1113：单股、单账号、总资产、比例 [0 ~ 1] 方式下单
        - 1123：单股、单账号、可用、比例[0 ~ 1]方式下单
        - 1201：单股、账号组（无权重）、普通、股/手方式下单
        - 1202：单股、账号组（无权重）、普通、金额（元）方式下单（只支持股票）
        - 1213：单股、账号组（无权重）、总资产、比例 [0 ~ 1] 方式下单
        - 1223：单股、账号组（无权重）、可用、比例 [0 ~ 1] 方式下单
- accountID，资金账号
  > 注：下单的账号ID（可多个）或账号组名
- orderCode，下单代码
  > 注：单股下单，则该参数填合约代码；
- prType，下单选价类型
    - 可选值：
        - -1：无效（实际下单时,需要用交易面板交易函数那设定的选价类型）
        - 0：卖5价
        - 1：卖4价
        - 2：卖3价
        - 3：卖2价
        - 4：卖1价
        - 5：最新价
        - 6：买1价
        - 7：买2价
        - 8：买3价
        - 9：买4价
        - 10：买5价
        - 11：（指定价）模型价
        - 12：涨跌停价
        - 13：挂单价
        - 14：对手价
        - 49：科创板盘后定价
- price，下单价格
  > 注：prType 是模型价/科创板盘后定价时 price 有效；其它情况无效；即 prType 参数为 11，49 时被使用。
  > prType 参数不为 11，49 时也需填写，填写的内容可为 -1，0，2，100 等任意数字。
- volume，下单数量（股 / 元 / %）
  根据 orderType 值最后一位确定 volume 的单位：
  单股下单时：
    - 1：股
    - 2：金额（元）
    - 3：比例（%）
- strageName，策略名
  不同于passorder，这里不可缺省
- quickTrade，参数内容说明
  quickTrade：int，是否立马触发下单，0 否，1 是
  > 注：
  >
  > passorder是对最后一根K线完全走完后生成的模型信号在下一根K线的第一个tick数据来时触发下单交易；
  >
  > 采用quickTrade参数设置为1时，非历史bar上执行时（ContextInfo.is_last_bar()为True），只要策略模型中调用到就触发下单交易。
  >
  > quickTrade参数设置为2时，不判断bar状态，只要策略模型中调用到就触发下单交易，历史bar上也能触发下单，请谨慎使用。
- userid，投资备注
  不同于passorder，这里不可缺省
- smartAlgoType，string，智能算法类型
  可选值：
    - VWAP：VWAP
    - TWAP：TWAP
    - VP：跟量
    - PINLINE：跟价
    - DMA：快捷
    - FLOAT：盘口
    - SWITCH：换仓
    - ICEBERG：冰山
    - MOC：尾盘
- limitOverRate，int，量比，数据范围0-100，如果输入其他无效值，则limitOverRate为0。
  > 注：网格算法无此项。
- minAmountPerOrder，int，智能算法最小委托金额，数据范围0-100000，默认为0。
- targetPriceLevel，智能算法目标价格
    - 可选值：
        - 1：己方盘口1
        - 2：己方盘口2
        - 3：己方盘口3
        - 4：己方盘口4
        - 5：己方盘口5
        - 6：最新价
        - 7：对方盘口
  > 注：
  >
  > 一、输入无效值则targetPriceLevel为1；
  >
  > 二、本项只针对冰山算法,其他算法可缺省。
    - 可选值：
        - VWAP：VWAP
        - TWAP：TWAP
        - VP：跟量
        - PINLINE：跟价
        - DMA：快捷
        - FLOAT：盘口
        - SWITCH：换仓
        - ICEBERG：冰山
        - MOC：尾盘
- startTime，智能算法开始时间​ 格式”HH:MM:SS”，如”10:30:00”。如果缺省值，则默认为”09:30:00”
- endTime，智能算法截止时间​ 格式”HH:MM:SS”，如”14:30:00”。如果缺省值，则默认为”15:30:00”

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 账户600000105最新价开仓买入50000股的000001.SZ平安银行,使用TWAP智能算法,量比20%,最小买卖金额0
	smart_algo_passorder(23, 1101, '600000105', '000001.SZ', 5, -1, 50000, "strageName", 0, "remark", "TWAP", 20, 0,
						 ContextInfo)

	# 账户600000105最新价快速交易开仓买入50000股的000001.SZ平安银行,使用TWAP智能算法,量比20%,最小买卖金额0且有效时长为09:30-14:00
	smart_algo_passorder(23, 1101, '600000105', '000001.SZ', 5, -1, 50000, "strageName", 1, "remark", "TWAP", 20, 0, 0,
						 '09:30:00', '14:00:00', ContextInfo)

```

#### （4）获取交易明细数据 get_trade_detail_data()

用法： get_trade_detail_data(accountID, strAccountType, strDatatype, strategyName) 或不区分策略get_trade_detail_data(
accountID, strAccountType, strDatatype)

释义： 获取交易明细数据函数

参数：

- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- strDatatype：string，数据类型：
    - ‘POSITION’：持仓
    - ‘ORDER’：委托
    - ‘DEAL’ ：成交
    - ‘ACCOUNT’：账号
    - ‘TASK’：任务
- strategyName：string，策略名，对应 passorder 下单函数中的参数 strategyName 的值，只对委托 ‘ORDER’、成交 ‘DEAL’ 起作用。

返回： list，list 中放的是 PythonObj，通过 dir(pythonobj) 可返回某个对象的属性列表。

注：有五种交易相关信息，包括：

- POSITION：持仓
- ORDER：委托
- DEAL：成交
- ACCOUNT：账号
- TASK：任务

示例：

```python
def handlebar(ContextInfo):
	obj_list = get_trade_detail_data('6000000248', 'stock', 'position')
	for obj in obj_list:
		print(obj.m_strInstrumentID)
	# 查看有哪些属性字段
	print(dir(obj))

	# 可用资金查询
	acct_info = get_trade_detail_data('6000000248', 'stock', 'account')
	for i in acct_info:
		print(i.m_dAvailable)

	# 当前持仓查询
	position_info = get_trade_detail_data('6000000248', 'stock', 'position')
	for i in position_info:
		print(i.m_strInstrumentID, i.m_nVolume)

```

#### （5）根据委托号获取委托或成交信息 get_value_by_order_id()

用法： get_value_by_order_id(orderId, accountID, strAccountType, strDatatype)

释义： 根据委托号获取委托或成交信息。

参数：

- orderId：string，委托号。
- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- strDatatype：string，数据类型：
    - ‘ORDER’：委托
    - ‘DEAL’ ：成交

返回： pythonObj

示例：

```python
def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	orderid = get_last_order_id(ContextInfo.accid, 'stock', 'order')
	print(orderid)
	obj = get_value_by_order_id(orderid, ContextInfo.accid, 'stock', 'order')
	print(obj.m_strInstrumentID)

```

#### （6）获取最新的委托或成交的委托号 get_last_order_id()

用法： get_last_order_id(accountID, strAccountType, strDatatype, strategyName) 或不区分策略 get_last_order_id(accountID,
strAccountType, strDatatype)

释义： 获取最新的委托或成交的委托号。

参数：

- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- strDatatype：string，数据类型：
    - ‘ORDER’：委托
    - ‘DEAL’ ：成交
- strategyName，string，策略名，对应 passorder 下单函数中的参数 strategyName 的值。

返回： String，委托号，如果没找到返回 ‘-1’。

示例：

```python
def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	orderid = get_last_order_id(ContextInfo.accid, 'stock', 'order')
	print(orderid)
	obj = get_value_by_order_id(orderid, ContextInfo.accid, 'stock', 'order')
	print(obj.m_strInstrumentID)

```

#### （7）查询委托是否可撤销 can_cancel_order()

用法： can_cancel_order(orderId, accountID, strAccountType)

释义： 查询委托是否可撤销。

参数：

- orderId，string，委托号。
- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权

返回： bool，是否可撤，返回值含义：

- True：可撤销
- False：不可撤销

示例：

```python
def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	orderid = get_last_order_id(ContextInfo.accid, 'stock', 'order')
	print(orderid)
	can_cancel = can_cancel_order(orderid, ContextInfo.accid, 'stock')
	print('是否可撤:', can_cancel)

```

#### （8）取消委托 cancel()

用法： cancel(orderId, accountId, accountType, ContextInfo)

释义： 取消委托

参数：

- orderId：string，委托号。
- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- ContextInfo：pythonobj

返回： bool，是否发出了取消委托信号，返回值含义：

- True：是
- False：否

示例1：

```python
'''
使用委托号撤单
（1）下单前,根据 get_trade_detail_data 函数返回账号的信息，判定资金是否充足，账号是否在登录状态，统计持仓情况等等。
（2）满足一定的模型条件，用 passorder 下单。
（3）下单后，时刻根据 get_last_order_id 函数获取委托和成交的最新id，注意如果委托生成了，就有了委托号（这个id需要自己保存做一个全局控制）。
（4）用该委托号根据 get_value_by_order_id 函数查看委托的状态，各种情况等。
当一个委托的状态变成“已成'后，那么对应的成交 deal 信息就有一条成交数据；用该委托号可查看成交情况。
*注：委托列表和成交列表中的委托号是一样的,都是这个 m_strOrderSysID 属性值。
可用 get_last_order_id 获取最新的 order 的委托号,然后根据这个委托号获取 deal 的信息，当获取成功后，也说明这笔交易是成了，可再根据 position 持仓信息再进一步验证。
（5）根据委托号获取委托信息，根据委托状态，或模型设定，用 cancel 取消委托。
'''


def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	orderid = get_last_order_id(ContextInfo.accid, 'stock', 'order')
	print(cancel(orderid, ContextInfo.accid, 'stock', ContextInfo))

```

#### （9）撤销任务 cancel_task()

用法：
cancel_task(taskId,accountId,accountType,ContextInfo)

释义： 撤销任务。

参数：

- taskId，string，任务编号, 为空的时候表示撤销所有该资金账号可撤的任务。
- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- ContextInfo：pythonobj

返回： bool，是否发出了取消任务信号，返回值含义：

- True：是
- False：否

示例：

```python
'''
（1）根据get_trade_detail_data函数返回任务的信息,获取任务编号（m_nTaskId），任务状态等等；
（2）根据任务编号，用cancel_task取消委托。
'''


def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	obj_list = get_trade_detail_data(ContextInfo.accid, 'stock', 'task')
	for obj in obj_list:
		cancel_task(obj.m_nTaskId, ContextInfo.accid, 'stock', ContextInfo)

```

#### （10）暂停任务 pause_task()

用法： pause_task(taskId,accountId,accountType,ContextInfo)

释义： 暂停智能算法任务。

参数：

- taskId，string，任务编号, 为空的时候表示暂停所有该资金账号可暂停的任务。
- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- ContextInfo：pythonobj

返回： bool，是否发出了暂停任务信号，返回值含义：

- True：是
- False：否

示例：

```python
'''
（1）根据get_trade_detail_data函数返回任务的信息,获取任务编号（m_nTaskId），任务状态等等；
（2）根据任务编号，用pause_task暂停智能算法任务。
'''


def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	obj_list = get_trade_detail_data(ContextInfo.accid, 'stock', 'task')
	for obj in obj_list:
		pause_task(obj.m_nTaskId, ContextInfo.accid, 'stock', ContextInfo)

```

#### （11）继续任务 cancel_task()

用法：
cancel_task(taskId,accountId,accountType,ContextInfo)

释义： 继续智能算法任务。

参数：

- taskId，string，任务编号, ,为空的时候表示启动所有该资金账号已暂停的任务。
- accountID：string，资金账号。
- strAccountType：string，账号类型，可选值：
    - ‘FUTURE’：期货
    - ‘STOCK’：股票
    - ‘CREDIT’：信用
    - ‘HUGANGTONG’：沪港通
    - ‘SHENGANGTONG’：深港通
    - ‘STOCK_OPTION’：期权
- ContextInfo：pythonobj

返回： bool，是否发出了重启信号，返回值含义：

- True：是
- False：否

示例：

```python
'''
（1）根据get_trade_detail_data函数返回任务的信息,获取任务编号（m_nTaskId），任务状态等等；
（2）根据任务编号，用resume_task启动已暂停智能算法任务。
'''


def init(ContextInfo):
	ContextInfo.accid = '6000000248'


def handlebar(ContextInfo):
	obj_list = get_trade_detail_data(ContextInfo.accid, 'stock', 'task')
	for obj in obj_list:
		resume_task(obj.m_nTaskId, ContextInfo.accid, 'stock', ContextInfo)

```

#### （12）实时触发前一根 bar 信号函数 do_order()

用法： do_order(ContextInfo)

释义： 实时触发前一根bar信号函数。

平台实盘中交易下单函数一般是把上一个周期产生的信号在最新的周期的第一个 tick 下单出去，而日 K 线第一个 tick 是在 9:25
分集合竞价结束时产生，如果策略模型在 9:25 分之后跑又想把前一天的下单信号发出去，就可用 do_order 函数配合实现。

特别的，需要注意，有调用 do_order 函数的策略模型跑在 9:25 分之前或别的日内周期下时，原有下单函数和 do_order
函数都有下单信号，有可能导致重复下单。、

参数： 无

返回： 无

示例：

```python
# 实现跑日 K 线及以上周期下,在固定时间点把前一周期的交易信号发送出去
def init(ContextInfo):
	pass


def handlebar(ContextInfo):
	order_lots('000002.SZ', 1, ContextInfo, '600000248')
	ticktimetag = ContextInfo.get_tick_timetag()
	int_time = int(timetag_to_datetime(ticktimetag, '%H%M%S'))
	if 100500


#### （13）指定手数交易 order_lots()

用法： order_lots(stockcode, lots[, style, price], ContextInfo[, accId])

释义：
指定手数交易，指定手数发送买 / 卖单。如有需要落单类型当做一个参量传入，如果忽略掉落单类型，那么默认以最新价下单。

参数：

- stockcode：代码，string，如 ‘000002.
SZ’
- lots：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
> 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
- ‘LATEST’：最新
- ‘FIX’：指定
- ‘HANG’：挂单
- ‘COMPETE’：对手
- ‘MARKET’：市价
- ‘SALE5’, ‘SALE4’, ‘SALE3’, ‘SALE2’, ‘SALE1’：卖5 - 1
价
- ‘BUY1’, ‘BUY2’, ‘BUY3’, ‘BUY4’, ‘BUY5’：买1 - 5
价
- price：价格，double
- ContextInfo：PythonObj，Python
对象，这里必须是
ContextInfo
- accId：账号，string

返回： 无

示例：

```python


def handlebar(ContextInfo):
	# 按最新价下 1 手买入
	order_lots('000002.SZ', 1, ContextInfo, '600000248')

	# 用对手价下 1 手卖出
	order_lots('000002.SZ', -1, 'COMPETE', ContextInfo, '600000248')

	# 用指定价 37.5 下 2 手卖出
	order_lots('000002.SZ', -2, 'fix', 37.5, ContextInfo, '600000248')

```

#### （14）指定价值交易 order_value()

用法： order_value(stockcode, value[, style, price], ContextInfo[, accId])

释义： 指定价值交易，使用想要花费的金钱买入 / 卖出股票，而不是买入 / 卖出想要的股数，正数代表买入，负数代表卖出。股票的股数总是会被调整成对应的
100 的倍数（在中国 A 股市场 1 手是 100股）。
当您提交一个卖单时，该方法代表的意义是您希望通过卖出该股票套现的金额，如果金额超出了您所持有股票的价值，那么您将卖出所有股票。需要注意，如果资金不足，该
API 将不会创建发送订单。

参数：

- stockcode：代码，string，如 ‘000002.SZ’
- value：金额（元），double
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE5’, ‘SALE4’, ‘SALE3’, ‘SALE2’, ‘SALE1’：卖5-1价
    - ‘BUY1’, ‘BUY2’, ‘BUY3’, ‘BUY4’, ‘BUY5’：买1-5价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价下 10000 元买入
	order_value('000002.SZ', 10000, ContextInfo, '600000248')

	# 用对手价下 10000 元卖出
	order_value('000002.SZ', -10000, 'COMPETE', ContextInfo, '600000248')

	# 用指定价 37.5 下 20000 元卖出
	order_value('000002.SZ', -20000, 'fix', 37.5, ContextInfo, '600000248')

```

#### （15）指定比例交易 order_percent()

用法： order_percent(stockcode, percent[, style, price], ContextInfo[, accId])

释义： 指定比例交易，发送一个等于目前投资组合价值（市场价值和目前现金的总和）一定百分比的买 /
卖单，正数代表买，负数代表卖。股票的股数总是会被调整成对应的一手的股票数的倍数（1 手是 100股）。
百分比是一个小数，并且小于或等于1（小于等于100%），0.5 表示的是 50%。需要注意，如果资金不足，该 API 将不会创建发送订单。

参数：

- stockcode：代码，string，如 ‘000002.SZ’
- percent：比例，double
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE5’, ‘SALE4’, ‘SALE3’, ‘SALE2’, ‘SALE1’：卖5-1价
    - ‘BUY1’, ‘BUY2’, ‘BUY3’, ‘BUY4’, ‘BUY5’：买1-5价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价下 5.1% 价值买入
	order_percent('000002.SZ', 0.051, ContextInfo, '600000248')

	# 用对手价下 5.1% 价值卖出
	order_percent('000002.SZ', -0.051, 'COMPETE', ContextInfo, '600000248')

	# 用指定价 37.5 下 10.2% 价值卖出
	order_percent('000002.SZ', -0.102, 'fix', 37.5, ContextInfo, '600000248')

```

#### （16）指定目标价值交易 order_target_value()

用法： order_target_value(stockcode, tar_value[, style, price], ContextInfo[, accId])

释义： 指定目标价值交易，买入 /
卖出并且自动调整该证券的仓位到一个目标价值。如果还没有任何该证券的仓位，那么会买入全部目标价值的证券；如果已经有了该证券的仓位，则会买入 /
卖出调整该证券的现在仓位和目标仓位的价值差值的数目的证券。
需要注意，如果资金不足，该API将不会创建发送订单。

参数：

- stockcode：代码，string，如 ‘000002.SZ’
- tar_value：目标金额（元），double，非负数
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE5’, ‘SALE4’, ‘SALE3’, ‘SALE2’, ‘SALE1’：卖5-1价
    - ‘BUY1’, ‘BUY2’, ‘BUY3’, ‘BUY4’, ‘BUY5’：买1-5价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	#按最新价下调仓到 10000 元持仓
	order_target_value('000002.SZ', 10000, ContextInfo, '600000248')

	#用对手价调仓到 10000 元持仓
	order_target_value('000002.SZ', 10000, 'COMPETE', ContextInfo, '600000248')

	#用指定价 37.5 下调仓到 20000 元持仓
	order_target_value('000002.SZ', 20000, 'fix', 37.5, ContextInfo, '600000248')

```

#### （17）指定目标比例交易 order_target_percent()

用法： order_target_percent(stockcode, tar_percent[, style, price], ContextInfo[, accId])

释义： 指定目标比例交易，买入 /
卖出证券以自动调整该证券的仓位到占有一个指定的投资组合的目标百分比。投资组合价值等于所有已有仓位的价值和剩余现金的总和。买 /
卖单会被下舍入一手股数（A 股是 100 的倍数）的倍数。
目标百分比应该是一个小数，并且最大值应该小于等于1，比如 0.5 表示50%，需要注意，如果资金不足，该API将不会创建发送订单。

参数：

- stockcode：代码，string，如 ‘000002.SZ’
- tar_percent：目标百分比 [0 ~ 1]，double
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE5’, ‘SALE4’, ‘SALE3’, ‘SALE2’, ‘SALE1’：卖5-1价
    - ‘BUY1’, ‘BUY2’, ‘BUY3’, ‘BUY4’, ‘BUY5’：买1-5价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	#按最新价下买入调仓到 5.1% 持仓
	order_target_percent('000002.SZ', 0.051, ContextInfo, '600000248')

	#用对手价调仓到 5.1% 持仓
	order_target_percent('000002.SZ', 0.051, 'COMPETE', ContextInfo, '600000248')

	#用指定价 37.5 调仓到 10.2% 持仓
	order_target_percent('000002.SZ', 0.102, 'fix', 37.5, ContextInfo, '600000248')

```

#### （18）指定股数交易 order_shares()

用法： order_shares(stockcode, shares[, style, price], ContextInfo[, accId])

释义： 指定股数交易，指定股数的买 /
卖单,最常见的落单方式之一。如有需要落单类型当做一个参量传入，如果忽略掉落单类型，那么默认以最新价下单。

参数：

- stockcode：代码，string，如 ‘000002.SZ’
- shares：股数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE5’, ‘SALE4’, ‘SALE3’, ‘SALE2’, ‘SALE1’：卖5-1价
    - ‘BUY1’, ‘BUY2’, ‘BUY3’, ‘BUY4’, ‘BUY5’：买1-5价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价下 100 股买入
	order_shares('000002.SZ', 100, ContextInfo, '600000248')

	# 用对手价下 100 股卖出
	order_shares('000002.SZ', -100, 'COMPETE', ContextInfo, '600000248')

	# 用指定价 37.5 下 200 股卖出
	order_shares('000002.SZ', -200, 'fix', 37.5, ContextInfo, '600000248')

```

#### （19）期货买入开仓 buy_open()

用法： buy_open(stockcode, amount[, style, price], ContextInfo[, accId])

释义： 期货买入开仓

参数：

- stockcode：代码，string，如 ‘IF1805.IF’
- amount：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE1’：卖一价
    - ‘BUY1’：买一价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价 1 手买入开仓
	buy_open('IF1805.IF', 1, ContextInfo, '110476')

	# 用对手价 1 手买入开仓
	buy_open('IF1805.IF', 1, 'COMPETE', ContextInfo, '110476')

	# 用指定价 3750 元 2 手买入开仓
	buy_open('IF1805.IF', 2, 'fix', 3750, ContextInfo, '110476')

```

#### （20）期货买入平仓（平今优先） buy_close_tdayfirst()

用法： buy_close_tdayfirst(stockcode, amount[, style, price], ContextInfo[, accId])

释义： 期货买入平仓，平今优先

参数：

- stockcode：代码，string，如 ‘IF1805.IF’
- amount：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE1’：卖一价
    - ‘BUY1’：买一价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	#按最新价 1 手买入平仓，平今优先
	buy_close_tdayfirst('IF1805.IF', 1, ContextInfo, '110476')

	#用对手价 1 手买入平仓，平今优先
	buy_close_tdayfirst('IF1805.IF', 1, 'COMPETE', ContextInfo, '110476')

	#用指定价 3750 元 2 手买入平仓，平今优先
	buy_close_tdayfirst('IF1805.IF', 2, 'fix', 3750, ContextInfo, '110476')

```

#### （21）期货买入平仓（平昨优先） buy_close_ydayfirst()

用法： buy_close_ydayfirst(stockcode, amount[, style, price], ContextInfo[, accId])

释义： 期货买入开仓，平昨优先

参数：

- stockcode：代码，string，如 ‘IF1805.IF’
- amount：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE1’：卖一价
    - ‘BUY1’：买一价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价 1 手买入平仓，平昨优先
	buy_close_ydayfirst('IF1805.IF', 1, ContextInfo, '110476')

	# 用对手价 1 手买入平仓，平昨优先
	buy_close_ydayfirst('IF1805.IF', 1, 'COMPETE', ContextInfo, '110476')

	# 用指定价 3750 元 2 手买入平仓，平昨优先
	buy_close_ydayfirst('IF1805.IF', 2, 'fix', 3750, ContextInfo, '110476')

```

#### （22）期货卖出开仓 sell_open()

用法： sell_open(stockcode, amount[, style, price], ContextInfo[, accId])

释义： 期货卖出开仓

参数：

- stockcode：代码，string，如 ‘IF1805.IF’
- amount：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE1’：卖一价
    - ‘BUY1’：买一价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价 1 手卖出开仓
	sell_open('IF1805.IF', 1, ContextInfo, '110476')

	# 用对手价 1 手卖出开仓
	sell_open('IF1805.IF', 1, 'COMPETE', ContextInfo, '110476')

	# 用指定价 3750 元 2 手卖出开仓
	sell_open('IF1805.IF', 2, 'fix', 3750, ContextInfo, '110476')

```

#### （23）期货卖出平仓（平今优先） sell_close_tdayfirst()

用法： sell_close_tdayfirst(stockcode, amount[, style, price], ContextInfo[, accId])

释义： 期货卖出平仓，平今优先

参数：

- stockcode：代码，string，如 ‘IF1805.IF’
- amount：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值：
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE1’：卖一价
    - ‘BUY1’：买一价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价下 1 手卖出平仓，平今优先
	sell_close_tdayfirst('IF1805.IF', 1, ContextInfo, '110476')

	# 用对手价 1 手卖出平仓，平今优先
	sell_close_tdayfirst('IF1805.IF', 1, 'COMPETE', ContextInfo, '110476')

	# 用指定价 3750 元 2 手卖出平仓，平今优先
	sell_close_tdayfirst('IF1805.IF', 1, 'fix', 3750, ContextInfo, '110476')

```

#### （24）期货卖出平仓（平昨优先） sell_close_ydayfirst()

用法： sell_close_ydayfirst(stockcode, amount[, style, price], ContextInfo[, accId])

释义： 期货卖出平仓，平今优先

参数：

- stockcode：代码，string，如 ‘IF1805.IF’
- amount：手数，int
- style：下单选价类型，string，默认为最新价 ‘LATEST’，可选值
  > 注意：回测时，除了指定价，其他下单选价类型均以当期k线收盘价结算。
    - ‘LATEST’：最新
    - ‘FIX’：指定
    - ‘HANG’：挂单
    - ‘COMPETE’：对手
    - ‘MARKET’：市价
    - ‘SALE1’：卖一价
    - ‘BUY1’：买一价
- price：价格，double
- ContextInfo：PythonObj，Python 对象，这里必须是 ContextInfo
- accId：账号，string

返回： 无

示例：

```python
def handlebar(ContextInfo):
	# 按最新价 1 手卖出平仓，平昨优先
	sell_close_ydayfirst('IF1805.IF', 1, ContextInfo, '110476')

	# 用对手价 1 手卖出平仓，平昨优先
	sell_close_ydayfirst('IF1805.IF', 1, 'COMPETE', ContextInfo, '110476')

	# 用指定价 3750 元 2 手卖出平仓，平昨优先
	sell_close_ydayfirst('IF1805.IF', 2, 'fix', 3750, ContextInfo, '110476')

```

#### （25）获取两融负债合约明细 get_debt_contract()

用法： get_debt_contract(accId)

释义： 获取信用账户负债合约明细

参数：

- accId：信用账户

返回： list，list 中放的是 PythonObj，通过 dir(pythonobj) 可返回某个对象的属性列表。

示例：

```python
def handlebar(ContextInfo):
	obj_list = get_debt_contract('6000000248')
	for obj in obj_list:
		# 输出负债合约名
		print(obj.m_strInstrumentName)

```

#### （26）获取两融担保标的明细 get_assure_contract()

用法： get_debt_contract(accId)

释义： 获取信用账户担保合约明细

参数：

- accId：信用账户

示例：

```python
def handlebar(ContextInfo):
	obj_list = get_assure_contract('6000000248')
	for obj in obj_list:
		# 输出担保合约名
		print(obj.m_strInstrumentName)

```

#### （27）获取可融券明细 get_enable_short_contract()

用法： get_enable_short_contract(accId)

释义： 获取信用账户当前可融券的明细

参数：

- accId：信用账户

示例：

```python
def handlebar(ContextInfo):
	obj_list = get_enable_short_contract('6000000248')
	for obj in obj_list:
		#输出可融券合约名
		print(obj.m_strInstrumentName)

```

#### （28）获取当日新股新债信息 get_ipo_data()

用法： get_ipo_data([,type])

释义： 获取当日新股新债信息，返回结果为一个字典,包括新股申购代码,申购名称,最大申购数量,最小申购数量等数据

参数：

- type：为空时返回新股新债信息，type=”STOCK”时只返回新股申购信息，type=”BOND”时只返回新债申购信息

示例：

```python
def init(ContextInfo):
	ipoData = get_ipo_data()  #返回新股新债信息
	ipoStock = get_ipo_data("STOCK")  #返回新股信息
	ipoCB = get_ipo_data("BOND")  #返回新债申购信息

```

#### （29）获取账户新股申购额度 get_new_purchase_limit()

用法： get_new_purchase_limit(accid)

释义： 获取账户新股申购额度，返回结果为一个字典,包括上海主板,深圳市场,上海科创版的申购额度

参数：

- accid：资金账号，必须时股票账号或者信用账号

示例：

```python
def init(ContextInfo):
	ContextInfo.accid = "10000001"  #返回新股新债信息
	purchase_limit = get_new_purchase_limit(ContextInfo.accid)

```

### 3.2.5. 交易回报实时主推函数

> 注：在使用交易回报实时主推函数时，需要在init函数中使用set_account()用于绑定资金账号返回回调信息。

​ 交易回报实时主推函数仅在实盘运行模式下生效。

#### （1）资金账号状态变化主推 account_callback()

用法： account_callback(ContextInfo, accountInfo)

释义： 当资金账号状态有变化时，运行这个函数

参数：

- ContextInfo：特定对象
- accountInfo：资金账号对象，可对应查看[6.4. 附录4 交易函数内含属性说明](#6.4. 附录4 交易函数内含属性说明)

返回： 无

示例：

```python
def init(ContextInfo):
	#设置对应的资金账号
	ContextInfo.set_account('6000000058')


def handlebar(ContextInfo):
	pass


def account_callback(ContextInfo, accountInfo):
	print('accountInfo')
	print(accountInfo.m_strStatus)  # m_strStatus 为资金账号的属性之一，表示资金账号的状态

```

#### （2）账号委托状态变化主推 order_callback()

用法： order_callback(ContextInfo, orderInfo)

释义： 当账号委托状态有变化时，运行这个函数

参数：

- ContextInfo：特定对象
- orderInfo：委托账号对象，可对应查看[6.4. 附录4 交易函数内含属性说明](#6.4. 附录4 交易函数内含属性说明)

返回： 无

示例：

```python
def init(ContextInfo):
	#设置对应的资金账号
	ContextInfo.set_account('6000000058')


def handlebar(ContextInfo):
	pass


def order_callback(ContextInfo, orderInfo):
	print('orderInfo')

```

#### （3）账号成交状态变化主推 deal_callback()

用法： deal_callback(ContextInfo, dealInfo)

释义： 当账号成交状态有变化时，运行这个函数

参数：

- ContextInfo：特定对象
- dealInfo：资金账号对象，可对应查看[6.4. 附录4 交易函数内含属性说明](#6.4. 附录4 交易函数内含属性说明)

返回： 无

示例：

```python
def init(ContextInfo):
	# 设置对应的资金账号
	ContextInfo.set_account('6000000058')


def handlebar(ContextInfo):
	pass


def deal_callback(ContextInfo, dealInfo):
	print('dealInfo')

```

#### （4）账号持仓状态变化主推 position_callback()

用法： position_callback(ContextInfo, positonInfo)

释义： 当账号持仓状态有变化时，运行这个函数

参数：

- ContextInfo：特定对象
- positonInfo：资金账号对象，可对应查看[6.4. 附录4 交易函数内含属性说明](#6.4. 附录4 交易函数内含属性说明)

返回： 无

示例：

```python
def init(ContextInfo):
	# 设置对应的资金账号
	ContextInfo.set_account('6000000058')


def handlebar(ContextInfo):
	pass


def position_callback(ContextInfo, positonInfo):
	print('positonInfo')

```

#### （5）账号异常下单主推 orderError_callback()

用法： orderError_callback(ContextInfo,orderArgs,errMsg)

释义： 当账号下单异常时，运行这个函数

参数：

- ContextInfo：特定对象
- orderArgs：下单参数，可对应查看[6.4. 附录4 交易函数内含属性说明](#6.4. 附录4 交易函数内含属性说明)
- errMsg：错误信息

返回： 无

示例：

```python
def init(ContextInfo):
	#设置对应的资金账号
	ContextInfo.set_account('6000000058')


def handlebar(ContextInfo):
	pass


def position_callback(ContextInfo, orderArgs, errMsg):
	print('orderArgs')
	print(errMsg)

```

### 3.2.6. 引用函数

*注：以下函数均支持回测和实盘/模拟运行模式。

#### （1）获取扩展数据 ext_data()

用法： ext_data(extdataname, stockcode, deviation, ContextInfo)

释义： 获取扩展数据

参数：

- extdataname：string，扩展数据名
- stockcode：string，形式如 ‘stkcodemarket’，如 ‘600000.SH’
- deviation：number，K 线偏移，可取值：
    - 0：不偏移
    - N：向右偏移N
    - -N：向左偏移N
- ContextInfo：pythonObj，Python 对象，这里必须是 ContextInfo

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(ext_data('mycci', '600000.SH', 0, ContextInfo))

```

#### （2）获取引用的扩展数据的数值在所有品种中的排名 ext_data_rank()

用法： ext_data_rank(extdataname, stockcode, deviation, ContextInfo)

释义： 获取引用的扩展数据的数值在所有品种中的排名

参数：

- extdataname：string，扩展数据名
- stockcode：string，形式如 ‘stkcodemarket’，如 ‘600000.SH’
- deviation：number，K 线偏移，可取值：
    - 0：不偏移
    - N：向右偏移N
    - -N：向左偏移N
- ContextInfo：pythonObj，Python 对象，这里必须是 ContextInfo

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(ext_data_rank('mycci', '600000.SH', 0, ContextInfo))

```

#### （3）获取引用的扩展数据的数值在指定时间区间内所有品种中的排名 ext_data_rank_range()

用法： ext_data_rank_range(extdataname, stockcode, begintime, endtime, ContextInfo)

释义： 获取引用的扩展数据的数值在指定时间区间内所有品种中的排名

参数：

- extdataname：string，扩展数据名
- stockcode：string，形式如 ‘stkcodemarket’，如 ‘600000.SH’
- begintime：string，区间的起始时间（包括该时间点在内）格式为 ‘2016-08-02 12:12:30’
- endtime：string，区间的结束时间（包括该时间点在内）格式为 ‘2017-08-02 12:12:30’
- ContextInfo：pythonObj，Python 对象，这里必须是 ContextInfo

返回： pythonDict

示例：

```python
def handlebar(ContextInfo):
	print(ext_data_rank_range('mycci', '600000.SH', '2016-08-02 12:12:30', '2017-08-02 12:12:30', ContextInfo))

```

#### （4）获取扩展数据在指定时间区间内的值 ext_data_range()

用法： ext_data_range(extdataname, stockcode, begintime, endtime, ContextInfo)

释义： 获取扩展数据在指定时间区间内的值

参数：

- extdataname：string，扩展数据名
- stockcode：string，形式如 ‘stkcodemarket’，如 ‘600000.SH’
- begintime：string，区间的起始时间（包括该时间点在内）格式为 ‘2016-08-02 12:12:30’
- endtime：string，区间的结束时间（包括该时间点在内）格式为 ‘2017-08-02 12:12:30’
- ContextInfo：pythonObj，Python 对象，这里必须是 ContextInfo

返回： pythonDict

示例：

```python
def handlebar(ContextInfo):
	print(ext_data_range('mycci', '600000.SH', '2016-08-02 12:12:30', '2017-08-02 12:12:30', ContextInfo))

```

#### （5）引用扩展数据在指定时间区域内的所有值和排名 ContextInfo.get_ext_all_data()

用法：ContextInfo.get_ext_all_data(extdataname,start_time=’19720101’,end_time=’22010101’)

释义： 引用扩展数据在指定时间区域内的所有值和排名

> 注：本函数最好在init中调用,一次性将要用的数据取出

参数：

- extdataname：string，扩展数据名
- start_time：起始时间，可缺省，缺省值1972年1月1日
- end_time：截止时间，可缺省，缺省值2201年1月1日

返回： pandas.panel

- Items：时间戳
- Major_axis：股票代码
- Minor_axis：扩展数据的域名(rank和value)

示例：

```python
def init(ContextInfo):
	print(ContextInfo.get_ext_all_data('mycci'))

```

#### （6）获取因子数据 get_factor_value()

用法： get_factor_value(factorname, stockcode, deviation, ContextInfo)

释义： 获取因子数据

参数：

- factorname：string，因子名
- stockcode：string，形式如 ‘stkcodemarket’，如 ‘600000.SH’
- deviation：number，K 线偏移，0 不偏移，N 向右偏移 N，-N 向左偏移 N
- ContextInfo：pythonObj，Python 对象，这里必须是 ContextInfo

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(get_factor_value('zzz', '600000.SH', 0, ContextInfo))

```

#### （7）获取引用的因子数据的数值在所有品种中排名 get_factor_rank()

用法： get_factor_rank(factorname, stockcode, deviation, ContextInfo)

释义： 获取引用的因子数据的数值在所有品种中排名

参数：

- factorname：string，因子名
- stockcode：string，形式如 ‘stkcodemarket’，如 ‘600000.SH’
- deviation：number，K 线偏移，0不偏移，N向右偏移N，-N向左偏移N
- ContextInfo：pythonObj，Python 对象，这里必须是 ContextInfo

返回： number

示例：

```python
def handlebar(ContextInfo):
	print(get_factor_rank('zzz', '600000.SH', 0, ContextInfo))

```

### 3.2.7. 绘图函数

*注：以下函数均支持回测和实盘/模拟运行模式。

#### （1）在界面上画图 ContextInfo.paint()

用法： ContextInfo.paint(name, value, index, line_style, color = ‘white’, limit = ‘’)

释义： 在界面上画图

参数：

- name：string，需显示的指标名
- value：number，需显示的数值
- index：number，显示索引位置，填 -1 表示按主图索引显示
- line_style：number，线型，可取值：
    - 0：曲线
    - 42：柱状线
- color：string，颜色（不填默认为白色）目前支持以下几种颜色：
    - blue：蓝
    - brown：棕
    - cyan：蓝绿
    - green：绿
    - magenta：品红
    - red：红
    - white：白
    - yellow：黄
- limit：string，画线控制，可取值：
    - ‘noaxis’： 不影响坐标画线
    - ‘nodraw’ ：不画线

返回： 无

示例：

```python
def handlebar(ContextInfo):
	realtimetag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
	value = ContextInfo.get_close_price('', '', realtimetag)
	ContextInfo.paint('close', value, -1, 0, 'white', 'noaxis')

```

#### （2）在图形上显示文字 ContextInfo.draw_text()

用法： ContextInfo.draw_text(condition, position, text)

释义： 在图形上显示数字

参数：

- condition：条件
- Position：位置
- text：文字

返回： 无

示例：

```python
def handlebar(ContextInfo):
	ContextInfo.draw_text(1, 10, '文字')

```

#### （3）在图形上显示数字 ContextInfo.draw_number()

用法： ContextInfo.draw_number(cond, height, number, precision)

释义： 在图形上显示数字

参数：

- cond：bool，条件
- height：number，显示文字的高度位置
- text：string，显示的数字
- precision：为小数显示位数（取值范围 0 - 7）

返回： 无

示例：

```python
def handlebar(ContextInfo):
	close = ContextInfo.get_market_data(['close'])
	ContextInfo.draw_number(1 > 0, close, 66, 1)

```

#### （4）在数字 1 和数字 2 之间绘垂直线 ContextInfo.draw_vertline()

用法： ContextInfo.draw_vertline(cond, number1, number2, color = ‘’, limit = ‘’)

释义： 在数字1和数字2之间绘垂直线

参数：

- cond：bool，条件
- number1：number，数字1
- number2：number，数字2
- color：string，颜色（不填默认为白色）目前支持以下几种颜色：
    - blue：蓝
    - brown：棕
    - cyan：蓝绿
    - green：绿
    - magenta：品红
    - red：红
    - white：白
    - yellow：黄
- limit：string，画线控制，可取值：
    - ‘noaxis’： 不影响坐标画线
    - ‘nodraw’ ：不画线

返回： 无

示例：

```python
def handlebar(ContextInfo):
	close = ContextInfo.get_market_data(['close'])
	open = ContextInfo.get_market_data(['open'])
	ContextInfo.draw_vertline(1 > 0, close, open, 'cyan')

```

#### （5）在图形上绘制小图标 ContextInfo.draw_icon()

用法： ContextInfo.draw_icon(cond, height, type)

释义： 在图形上绘制小图标

参数：

- cond：bool，条件
- height：number，图标的位置
- text：number，图标的类型，可取值：
    - 1：椭圆
    - 0：矩形

返回： 无

示例：

```python
def handlebar(ContextInfo):
	close = ContextInfo.get_market_data(['close'])
	ContextInfo.draw_icon(1 > 0, close, 0)

```
