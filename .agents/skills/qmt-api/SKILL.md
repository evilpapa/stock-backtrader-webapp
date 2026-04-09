---
name: qmt-api
description: Retrieve and use the QMT Python API documentation (from qmt.ptradeapi.com) for questions about writing QMT strategies, ContextInfo methods, market data access, quote subscriptions, trading functions (passorder/algo_passorder/smart_algo_passorder), callbacks, factor/financial data, and QMT enums/appendices. Use when the user asks about QMT Python API function signatures, return structures, parameters, or wants example code aligned with the official docs.
---

# qmt-api

Use this skill as the authoritative reference for the QMT Python API manual sourced from the official web page.

## Primary reference

Read in this order:

1. `references/00-index.md` (entrypoint + function index)
2. One of the split volumes (recommended for search):
   - `references/概述.md`
   - `references/1-创建策略.md`
   - `references/2-创建一个-python-策略.md`
   - `references/3-python-api-手册.md`
   - `references/4-财务数据接口使用方法.md`
   - `references/5-多因子数据接口使用方法.md`
   - `references/6-附录.md`

Source:

- https://qmt.ptradeapi.com/QMT_Python_API_Doc.html

## Workflow

1. Search the reference for the exact function name or section.
2. Copy the signature and parameter names exactly (do not invent params).
3. If writing code examples, keep them minimal and aligned with QMT strategy conventions:
   - `init(ContextInfo)`
   - `handlebar(ContextInfo)`
   - optional `stop(ContextInfo)`
4. Call out mode constraints when relevant (回测 vs 运行/模拟 vs 实盘)。
5. For trading-related APIs, clearly separate **documentation/code generation** from **real order execution**.

## Common routing

- Strategy skeleton / lifecycle → `init`, `handlebar`, `stop`, `run_time`
- Context object usage → `ContextInfo.*` sections
- Market data → `get_history_data`, `get_market_data`, `get_market_data_ex`, `get_full_tick`, `get_local_data`
- Quote subscription → `subscribe_quote`, `unsubscribe_quote`, `get_all_subscription`
- Trading functions → `passorder`, `algo_passorder`, `smart_algo_passorder`, `cancel`, `cancel_task`, `pause_task`, `resume_task`
- Callbacks / real-time pushes → `account_callback`, `order_callback`, `deal_callback`, `position_callback`, `orderError_callback`
- Financial / factor data → financial tables section, `get_factor_data`, factor tables
- Appendices / enums → appendix sections for markets, order types, statuses, etc.

## Answering rules

- Prefer quoting exact names/signatures from the reference.
- If you suspect a table got mangled during HTML→Markdown conversion, say so and point to the source URL section.

