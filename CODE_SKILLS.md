# Python 现代与高效编码技巧指南

本文档总结了在实际 Python 工程与量化交易系统（如本项目）中常用、能够显著提升代码简洁性、可读性与运行效率的编码模式和进阶技巧。

---

## 目录
1. [条件判断与分支简化](#1-条件判断与分支简化)
2. [短路逻辑与默认值提取](#2-短路逻辑与默认值提取)
3. [容器与字典操作利器](#3-容器与字典操作利器)
4. [循环与迭代技巧](#4-循环与迭代技巧)
5. [解包与结构赋值](#5-解包与结构赋值)
6. [函数式与闭包模式](#6-函数式与闭包模式)
7. [面向对象与数据模型优化](#7-面向对象与数据模型优化)
8. [上下文管理与资源安全](#8-上下文管理与资源安全)

---

## 1. 条件判断与分支简化

### 1.1 三元条件表达式（Ternary Operator）
适用于两分支、单值计算/赋值场景，消除冗余的 `if-else` 代码块：
```python
# 传统写法
if is_production:
    mode = "live"
else:
    mode = "sim"

# 优雅写法
mode = "live" if is_production else "sim"
```

### 1.2 字典分发代替长 `if-elif-else`（Dispatch Table）
当需要根据某一标识符执行不同逻辑或调用不同函数时，用字典映射代替长串分支：
```python
# 传统写法
if action == "buy":
    handle_buy(order)
elif action == "sell":
    handle_sell(order)
elif action == "cancel":
    handle_cancel(order)
else:
    handle_default(order)

# 优雅写法：表驱动 / 策略模式
HANDLERS = {
    "buy": handle_buy,
    "sell": handle_sell,
    "cancel": handle_cancel,
}
handler = HANDLERS.get(action, handle_default)
handler(order)
```

### 1.3 `match-case` 结构化模式匹配（Python 3.10+）
适用于复杂结构（tuple/dict/类实例/嵌套类型）解构与多态分支匹配：
```python
match event:
    case {"type": "order", "status": "filled", "order_id": oid}:
        mark_order_filled(oid)
    case {"type": "order", "status": "rejected", "reason": reason}:
        log_order_rejection(reason)
    case {"type": "tick", "price": p} if p > 0:
        update_price(p)
    case _:
        pass
```

### 1.4 `in` 集合判断代替多个 `==` 或 `or`
```python
# 传统写法
if status == "filled" or status == "cancelled" or status == "rejected":
    ...

# 优雅写法
if status in {"filled", "cancelled", "rejected"}:
    ...
```

---

## 2. 短路逻辑与默认值提取

### 2.1 利用 `or` 赋默认假值回退（Falsy Fallback）
在 Python 中，`or` 会返回第一个真值对象，常用于空值/空容器默认回退：
```python
# 传统写法
codes = params.get("stock_list")
if not codes:
    codes = params.get("stock_code")

# 优雅写法
codes = params.get("stock_list") or params.get("stock_code") or []
```
> **注意**：若合法值可能包含 `0`、`""` 或 `False`，请使用显式的 `None` 判断（如 `val if val is not None else default`）。

### 2.2 利用 `and` 执行链式属性/安全调用
```python
# 当 obj 可能为 None 时
name = obj and obj.name

# 执行带条件的回调
callback and callback(result)
```

### 2.3 海象运算符 `:=`（Walrus Operator，Python 3.8+）
在条件判断、循环或推导式中同时完成“赋值”与“测试”，避免二次查找或多重嵌套：
```python
# 传统写法
data = cache.get(key)
if data is not None:
    process(data)

# 优雅写法
if (data := cache.get(key)) is not None:
    process(data)

# 循环中消费生成器/流
while (chunk := file.read(8192)):
    process_chunk(chunk)
```

---

## 3. 容器与字典操作利器

### 3.1 推导式（List / Dict / Set Comprehensions）
不仅代码更紧凑，底层由 C 循环实现，通常比手写 `for + append` 快 15%~30%：
```python
# 列表推导式
valid_codes = [c.upper() for c in raw_codes if c]

# 字典推导式（倒排索引、数据转换）
symbol_to_id = {sym: idx for idx, sym in enumerate(symbols)}

# 集合推导式（自动去重）
unique_exchanges = {code.split(".")[-1] for code in stock_list}
```

### 3.2 字典合并操作符 `|` 与 `|=`（Python 3.9+）
替代旧式的 `dict(d1, **d2)` 或 `copy() + update()`：
```python
base_config = {"timeout": 3.0, "mode": "sim"}
custom_config = {"mode": "live", "port": 6379}

# 合并生成新字典
config = base_config | custom_config  # custom 优先覆盖

# 就地原地更新
base_config |= custom_config
```

### 3.3 `collections.defaultdict` 与 `dict.setdefault`
处理字典中的嵌套容器（如按行业分组、按账号归类持仓）：
```python
from collections import defaultdict

# 传统写法
grouped = {}
for item in positions:
    k = item["account_id"]
    if k not in grouped:
        grouped[k] = []
    grouped[k].append(item)

# 优雅写法 1: defaultdict
grouped = defaultdict(list)
for item in positions:
    grouped[item["account_id"]].append(item)

# 优雅写法 2: setdefault
grouped = {}
for item in positions:
    grouped.setdefault(item["account_id"], []).append(item)
```

### 3.4 `collections.Counter` 计数与频次分析
```python
from collections import Counter

# 频次统计
counts = Counter(["SH", "SZ", "SH", "BJ", "SZ", "SH"])
top_market, count = counts.most_common(1)[0]  # ("SH", 3)
```

---

## 4. 循环与迭代技巧

### 4.1 聚合断言 `any()` 与 `all()`（惰性求值）
结合生成器表达式，遇到满足/不满足条件时立即短路返回，无需完整遍历：
```python
# 传统写法
has_failed = False
for item in task_results:
    if not item.is_success():
        has_failed = True
        break

# 优雅写法
has_failed = any(not item.is_success() for item in task_results)
all_valid = all(is_valid(x) for x in stock_codes)
```

### 4.2 `enumerate()` 带索引遍历
避免使用 `range(len(items))`：
```python
# 传统写法
for i in range(len(orders)):
    print(f"Order #{i}: {orders[i]}")

# 优雅写法
for idx, order in enumerate(orders, start=1):
    print(f"Order #{idx}: {order}")
```

### 4.3 `zip()` 与 `itertools.zip_longest()` 并行迭代
```python
codes = ["000001.SZ", "600000.SH"]
prices = [10.5, 8.2]

# 合并遍历或转为字典
for code, price in zip(codes, prices):
    print(code, price)

quote_map = dict(zip(codes, prices))
```

### 4.4 生成器表达式（Generator Expression）节约内存
处理海量记录时不一次性生成大列表：
```python
# 列表推导（立即占用内存）
total = sum([item.volume * item.price for item in huge_trades])

# 生成器（边计算边累加，极度省内存）
total = sum(item.volume * item.price for item in huge_trades)
```

---

## 5. 解包与结构赋值

### 5.1 扩展可迭代解包（Starred Expression）
```python
first, *middle, last = [1, 2, 3, 4, 5]
# first=1, middle=[2, 3, 4], last=5

# 分割路径或股票代码
code, _, market = "000001.SZ".partition(".")
```

### 5.2 变量安全交换（Tuple Swap）
无需临时变量 `temp`：
```python
a, b = b, a
```

### 5.3 字典解包传参（`**kwargs` 与 `*args`）
```python
params = {"codes": ["000001.SZ"], "period": "1d", "count": 100}
xtdata.get_market_data_ex(**params)
```

---

## 6. 函数式与闭包模式

### 6.1 `functools.partial` 偏函数固定参数
常用于固定回调函数的部分前置上下文参数（如特定账号、通道标识）：
```python
from functools import partial

def on_push(account_id, topic, data):
    ...

# 固定特定账号的订阅回调
account_push_cb = partial(on_push, "8886800503")
subscribe(topic, callback=account_push_cb)
```

### 6.2 `functools.lru_cache` 自动记忆化缓存
对无副作用的高频计算、元数据查询增加内存缓存：
```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def get_exchange_by_code(code: str) -> str:
    # 复杂匹配或解析
    return parse_exchange(code)
```

### 6.3 `operator` 模块提速排序/查找
替代简单的 `lambda x: x['key']`，底层为 C 加速：
```python
from operator import itemgetter, attrgetter

# 按字段排序
orders.sort(key=itemgetter("timestamp"))
# 按对象属性排序
trades.sort(key=attrgetter("trade_time"))
```

---

## 7. 面向对象与数据模型优化

### 7.1 `dataclasses.dataclass` 声明轻量结构体（Python 3.7+）
自动生成 `__init__`, `__repr__`, `__eq__` 等样板代码：
```python
from dataclasses import dataclass

@dataclass(slots=True)  # Python 3.10+ 支持 slots=True，性能更高且更省内存
class OrderInfo:
    order_sys_id: str
    symbol: str
    volume: int
    price: float = 0.0
```

### 7.2 类内部声明 `__slots__` 节省内存
对成千上万个高频创建的简单对象（如 Tick、Order、Bar），声明 `__slots__` 阻止创建内部 `__dict__`，可节省 40%~60% 内存开销并提速属性访问：
```python
class TickSnapshot:
    __slots__ = ("code", "last_price", "volume", "amount", "timestamp")

    def __init__(self, code, last_price, volume, amount, timestamp):
        self.code = code
        self.last_price = last_price
        self.volume = volume
        self.amount = amount
        self.timestamp = timestamp
```

### 7.3 使用 `@property` 延迟计算与只读保护
```python
class AccountContext:
    def __init__(self, account_id):
        self.account_id = account_id
        self._cached_balance = None

    @property
    def is_credit(self) -> bool:
        return self.account_id.startswith("100")
```

---

## 8. 上下文管理与资源安全

### 8.1 多个上下文管理器单行合并
```python
# 传统嵌套
with open("source.txt") as src:
    with open("dest.txt", "w") as dst:
        dst.write(src.read())

# 优雅写法
with open("source.txt") as src, open("dest.txt", "w") as dst:
    dst.write(src.read())
```

### 8.2 `contextlib.suppress` 替代空白 `try-except-pass`
当需要忽略某些已知且无害的异常类型时：
```python
# 传统写法
try:
    os.remove(temp_path)
except FileNotFoundError:
    pass

# 优雅写法
from contextlib import suppress

with suppress(FileNotFoundError):
    os.remove(temp_path)
```

### 8.3 `@contextmanager` 快速定义上下文
无需繁琐实现 `__enter__` 与 `__exit__` 类：
```python
from contextlib import contextmanager
import time

@contextmanager
def measure_time(task_name: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        cost_ms = (time.perf_counter() - t0) * 1000
        print(f"[{task_name}] took {cost_ms:.2f} ms")

# 使用
with measure_time("fetch_kline"):
    data = fetch_bars("000001.SZ")
```

---

## 9. 最佳实践准则（何时用与何时不用）

1. **可读性优先（PEP 20 - Zen of Python）**：
   - “*Flat is better than nested.*”（扁平优于嵌套）
   - “*Readability counts.*”（可读性至关重要）
2. **避免过犹不及**：
   - 嵌套超过 2 层条件的三元表达式（如 `a if x else b if y else c`）应果断改写为清晰的 `if-elif-else` 或表驱动分发；
   - 过于晦涩的单行推导式应拆分为具名步骤或生成器函数；
3. **保持类型稳定与向后兼容**：
   - 在多版本兼容库（如需兼容 Python 3.6/3.12 混合环境）中，避免使用仅限新版本的语法（如 3.10+ match-case 或 3.9+ 字典合并符），优先选择全版本通用模式。
