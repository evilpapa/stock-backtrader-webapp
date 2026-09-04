# 股票回测 Web 应用

基于 Python 的 A 股策略回测应用。应用通过 Streamlit 提供交互界面，使用
Backtrader 执行回测，并通过 `xtquant-big-convert` 的 Big QMT RPC 桥接服务获取行情。

![demo](demo.gif)

## 核心特性

- **Big QMT 行情数据**：通过 `xtquant-big-convert` 访问大 QMT 的历史行情 RPC。
- **策略回测**：使用 Backtrader 测试交易策略表现。
- **结果可视化**：使用 Pyecharts 展示行情与回测结果。
- **交互界面**：使用 Streamlit 配置数据源、策略参数和回测参数。

## 技术架构

| 组件                    | 功能                                  | 链接                                                  |
|-------------------------|---------------------------------------|-------------------------------------------------------|
| **xtquant-big-convert** | 连接大 QMT 的 Redis RPC 行情/交易桥接 | [PyPI](https://pypi.org/project/xtquant-big-convert/) |
| **Streamlit**           | 构建交互式数据应用界面                | [官方仓库](https://github.com/streamlit/streamlit)    |
| **Backtrader**          | 执行量化交易策略回测                  | [官方仓库](https://github.com/mementum/backtrader)    |
| **Pyecharts**           | 生成金融数据图表                      | [官方仓库](https://github.com/pyecharts/pyecharts)    |

## 快速开始

### 1. 安装项目依赖

项目已锁定 `xtquant-big-convert[redis]==0.3.14`。在项目根目录执行：

```powershell
uv sync
```

### 2. 部署 Big QMT 桥接服务

桥接服务分为两端：开发机上的客户端（本项目）和大 QMT 内置 Python 中运行的服务端。

1. 将 `xtquant-big-convert` 安装/同步到 QMT 环境。
2. 将包中的 `bigqmt_signal_trader/`、`bigqmt_signal_trader_strategy.py`、
   `bigqmt_signal_trader_redis_rpc_runtime.py` 和 `BIGQMT_REDIS_DRYRUN.py`
   复制到 QMT 的 `python` 目录。
3. 在同一目录创建未提交到 Git 的 `bigqmt_signal_trader_local_config.py`：

```python
# coding: utf-8
BIGQMT_ACCOUNT_ID = "资金账号"
BIGQMT_REDIS_CONFIG = {
    "host": "Redis 地址",
    "port": 6379,
    "db": 5,
    "password": "Redis 密码",
    "rpc_allow_order_methods": False,
    "rpc_process_in_listener": True,
    "rpc_listener_methods": ("*",),
    "rpc_background_threads": False,
    "schedule_adjust": True,
    "schedule_adjust_interval": "500nMilliSecond",
}
```

4. 在 QMT 策略编辑器中加载并运行 `BIGQMT_REDIS_DRYRUN.py`。看到
   `bigqmt_rpc started channel=bigqmt:rpc:req:...` 后，服务端即已就绪。

> 配置文件包含账号和 Redis 凭据，必须保持在 QMT 本机且不要提交到版本库。远程下单默认关闭；
> 本项目回测只使用行情读取能力，无需开启 `rpc_allow_order_methods`。

### 3. 配置本项目的 Big QMT 客户端

在启动应用的终端中设置与服务端一致的 Redis 配置：

```powershell
$env:BIGQMT_ACCOUNT_ID = "资金账号"
$env:BIGQMT_REDIS_HOST = "Redis 地址"
$env:BIGQMT_REDIS_PORT = "6379"
$env:BIGQMT_REDIS_DB = "5"
$env:BIGQMT_REDIS_PASSWORD = "Redis 密码"
# 可选：Redis ACL 用户名
$env:BIGQMT_REDIS_USERNAME = ""
```

应用会从上述环境变量读取连接信息；侧边栏仅用于选择本次请求的账号和 RPC 超时。

### 4. 启动应用

```powershell
uv run streamlit run app.py
```

在侧边栏填写股票代码、周期和日期范围后，应用会调用 Big QMT RPC 的
`get_market_data_ex`，并将返回结果标准化为 `date/open/high/low/close/volume`
列后交给 Backtrader。

### 5. 运行测试

```powershell
uv run python -m pytest tests/bigqmt_client_test.py -q
```

## 数据与回测参数

### Big QMT 数据参数

| 参数                      | 说明                                                              |
|---------------------------|-------------------------------------------------------------------|
| **symbol**                | 股票代码，例如 `600070` 或 `600070.SH`；客户端会补全交易所后缀。  |
| **period**                | 数据周期，例如 `1d`、`1w`、`1mon`。                               |
| **start date / end date** | 行情数据的起止日期。                                              |
| **dividend type**         | 复权方式：`front`（前复权）、`back`（后复权）、`none`（不复权）。 |
| **Big QMT account ID**    | 与桥接服务端一致的资金账号；默认读取 `BIGQMT_ACCOUNT_ID`。        |
| **Big QMT RPC timeout**   | 单次 RPC 请求等待时长，默认 10 秒。                               |

### Backtrader 回测参数

| 参数                      | 说明                 |
|---------------------------|----------------------|
| **start date / end date** | 回测起止日期。       |
| **start cash**            | 初始资金。           |
| **commission fee**        | 交易佣金比例。       |
| **stake**                 | 每次交易的固定股数。 |

## 支持的策略

- **MA 策略**：基于单一移动平均线的趋势跟踪策略。
- **MACross 策略**：基于快慢双均线交叉的交易策略。

## 常见问题

| 现象                       | 排查方向                                                                               |
|----------------------------|----------------------------------------------------------------------------------------|
| RPC 超时                   | 确认 QMT 端已运行入口脚本，客户端和服务端的 Redis 地址、端口、db、密码与账号完全一致。 |
| 行情返回为空               | 确认账户具有对应标的和周期的行情权限，并检查股票代码的交易所后缀。                     |
| `import redis` 被 QMT 拒绝 | 使用桥接包提供的无 Redis/ZMQ 部署方式，并将客户端与服务端的 transport 保持一致。       |
| 下单方法不可用             | 正常安全限制；服务端默认禁止远程下单。本项目不需要开启该选项。                         |
