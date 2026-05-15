# Plan: 股票筛选与多头趋势策略复现

## Requirements Summary

目标是从知识星球 `LLMQuant` 中的《独家资源 量化策略代码复现》专栏定位《独家资源｜量化策略代码｜股票筛选与多头趋势策略》，整理文章内容和代码，并按当前 Streamlit + Backtrader 项目规范实现一个新策略。

当前阻塞：知识星球 API 对该星球返回“该星球内容仅限成员在星球内查看，暂不支持通过 API 访问”。已验证的失败入口包括：

- `zsxq-cli topic +search --group-id 51111558248484 --query "股票筛选与多头趋势策略"`
- `get_group_topics(group_id=51111558248484)`
- `search_topics(group_id=51111558248484, query="独家资源 量化策略代码复现 股票筛选 多头趋势")`
- `get_hashtag_topics(hashtag_id=48811412558228)`
- 公共网页搜索未命中该标题的公开副本

因此实现不能从标题臆造交易规则。执行前需要拿到文章正文和代码，来源可以是用户粘贴、可访问的导出文件、截图 OCR 文本，或其他已授权可读内容。

## Acceptance Criteria

- 文档落地到 `docs/stock_selection_bull_trend/`，至少包含原始资料摘要、策略规则、参数说明、Python 实现说明和复现差异说明。
- 新策略类命名为 `StockSelectionBullTrendStrategy`，策略 `_name` 为 `StockSelectionBullTrend`，文件路径为 `strategy/stock_selection_bull_trend.py`。
- `strategy/__init__.py` 导出新策略，因为运行时按 `getattr(__import__("strategy"), f"{strategy.name}Strategy")` 动态导入策略类（`utils/processing.py:64-67`）。
- `config/strategy.yaml` 增加 `StockSelectionBullTrend` 参数段，因为参数 UI 由 YAML 驱动（`config/strategy.yaml:1-101`）。
- 策略逻辑继承 `BaseStrategy`，遵守现有 `order`、`notify_order`、`trade_log` / 状态记录风格，参考 `strategy/turtle_trading.py:10-180`。
- 添加 focused unit tests，使用合成 `PandasData` feed 验证入场、出场、过滤条件、参数注入和无信号不交易，参考 `tests/turtle_trading_test.py:9-151`。
- 相关测试通过：`uv run python -m unittest tests.stock_selection_bull_trend_test`，并运行至少一个回归测试，例如 `uv run python -m unittest tests.turtle_trading_test`。

## Implementation Steps

1. 获取资料并建档
   - 将文章正文和代码整理为 `docs/stock_selection_bull_trend/股票筛选与多头趋势策略.txt`。
   - 新建 `docs/stock_selection_bull_trend/RESEARCH.md`：抽取股票池、筛选条件、趋势判定、调仓频率、仓位/风控、手续费假设、不可复现点。
   - 新建 `docs/stock_selection_bull_trend/README_PYTHON.md`：说明 Backtrader 版本的参数、行为和测试方式。

2. 规则映射
   - 如果文章是多股票筛选策略，先确认当前应用是否能提供多标的数据。当前 `run_backtrader` 只对单个 `PandasData` 调用 `cerebro.adddata(data)`（`utils/processing.py:49-54`），所以多股票策略需要在单标回测模式下退化为“信号过滤/择时”，或另开多数据管线。
   - 若文章代码包含选股池/排名逻辑，优先在策略类内部保留可测试的纯计算 helper；只有确需跨标的时，才扩展数据层。

3. 实现策略
   - 新建 `strategy/stock_selection_bull_trend.py`。
   - 参数初稿只使用文章明确参数，例如均线周期、趋势确认窗口、成交量过滤、止损/止盈、调仓间隔；不要添加文章没有定义的优化参数。
   - 复用 `BaseStrategy.notify_order` 和现有状态模式。

4. 注册与 UI
   - 在 `strategy/__init__.py:1-20` 增加 import 和 `__all__`。
   - 在 `config/strategy.yaml` 增加 `StockSelectionBullTrend` 参数配置。

5. 测试
   - 新建 `tests/stock_selection_bull_trend_test.py`。
   - 用人工 OHLCV 数据覆盖：
     - 多头趋势成立后买入；
     - 趋势跌破或风控触发后卖出；
     - 筛选条件未满足时不交易；
     - pending order 时不重复下单；
     - 参数注入生效。

6. 验证
   - `uv run python -m unittest tests.stock_selection_bull_trend_test`
   - `uv run python -m unittest tests.turtle_trading_test`
   - 如果策略加入了数据层能力，再运行 `uv run pytest -s -k stock_selection_bull_trend` 和相关 `utils/processing` 回归。

## Risks And Mitigations

- 文章内容不可通过 API 读取：不臆造规则；等待授权内容输入后执行实现。
- 多股票筛选与当前单数据回测管线冲突：先用文档记录差异，若必须扩展管线，则拆成独立变更并补集成测试。
- 原代码可能依赖平台专用数据字段：建立字段映射表，缺失字段用显式 `Not-supported` 记录，不静默替代。
- AkShare 网络数据不稳定：核心策略测试使用合成数据，避免把正确性绑定到外部数据源。

## Verification Evidence Needed

- 文章正文/代码已归档到 `docs/stock_selection_bull_trend/`。
- 单元测试能证明文章规则被复现，而不是仅证明代码能运行。
- 回测入口能通过 `StrategyBase.name="StockSelectionBullTrend"` 动态加载新策略。

## Execution Handoff

拿到文章正文和代码后，可直接执行本计划。推荐单人实现即可；若需要并行，使用：

- `explore`：确认文章代码与当前数据管线差异。
- `executor`：实现策略、文档、注册和参数配置。
- `test-engineer`：补合成数据测试和回归验证。

