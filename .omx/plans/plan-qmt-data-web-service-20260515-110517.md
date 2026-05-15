# Plan: QMT Data Web Service Wrapper

## Requirements Summary

Build a QMT-side data gateway method/module that wraps QMT `ContextInfo` market-data APIs behind a small local HTTP service so strategy code can request QMT data through stable JSON endpoints.

Primary goal:
- Expose QMT market data methods safely from inside the QMT strategy lifecycle, where `ContextInfo` is available.
- Normalize QMT return values (`dict`, scalar, `pd.Series`, `pd.DataFrame`) into predictable JSON.
- Let strategy/backtest code consume data through a client abstraction instead of directly coupling to `ContextInfo`.

Relevant current code:
- [qmt/etf_momentum.py](/Users/udyrli/github.com/stock-backtrader-webapp/qmt/etf_momentum.py:46) already follows QMT lifecycle `init(ContextInfo)`, `handlebar(ContextInfo)`, `stop(ContextInfo)`.
- [qmt/etf_momentum.py](/Users/udyrli/github.com/stock-backtrader-webapp/qmt/etf_momentum.py:121) currently calls `ContextInfo.get_market_data_ex(...)` directly.
- [utils/processing.py](/Users/udyrli/github.com/stock-backtrader-webapp/utils/processing.py:18) currently fetches Web-app data via AkShare.
- [app.py](/Users/udyrli/github.com/stock-backtrader-webapp/app.py:15) currently assumes the sidebar returns AkShare params and `gen_stock_df()` returns Chinese-column OHLCV data.
- [pyproject.toml](/Users/udyrli/github.com/stock-backtrader-webapp/pyproject.toml:11) has no web API framework dependency; because project guidance says no new dependencies without explicit request, the first implementation should use Python stdlib `http.server` unless a later execution task explicitly approves FastAPI/Flask.

QMT API facts from local `qmt-api` reference:
- `ContextInfo.get_history_data(len, period, field, dividend_type=0, skip_paused=True)` requires `ContextInfo.set_universe()` first and returns `{stockcode.market: list}`.
- `ContextInfo.get_market_data(fields, stock_code=[], start_time='', end_time='', skip_paused=True, period='1d', dividend_type='none', count=-1)` returns different shapes depending on requested fields/stocks/time range.
- `ContextInfo.get_market_data_ex(fields=[], stock_code=[], period='follow', start_time='', end_time='', count=-1, dividend_type='follow', fill_data=True, subscribe=True)` returns `{code: pd.DataFrame}`.
- `ContextInfo.get_full_tick(stock_code=[])` returns latest tick dicts by code.
- `ContextInfo.get_local_data(stock_code, start_time='', end_time='', period='1d', divid_type='none', count=-1)` returns local historical data keyed by timetag.
- `ContextInfo.subscribe_quote(stock_code, period='follow', dividend_type='follow', callback=None)` returns a subscription id; streaming/push should be a later phase unless explicitly needed.

## Recommended Design

Use a three-layer bridge:

1. `qmt/data_gateway.py`
   - QMT-side HTTP server module.
   - Starts in `init(ContextInfo)` and stops in `stop(ContextInfo)`.
   - Owns endpoint routing, request validation, response normalization, and server lifecycle.
   - Uses stdlib `ThreadingHTTPServer` and `BaseHTTPRequestHandler` to avoid new dependencies.

2. `qmt/data_adapter.py`
   - Thin adapter around `ContextInfo`.
   - Provides methods named after supported QMT calls:
     - `get_history_data`
     - `get_market_data`
     - `get_market_data_ex`
     - `get_full_tick`
     - `get_local_data`
   - Centralizes allowed parameter names so HTTP input cannot call arbitrary attributes.

3. `utils/qmt_data_client.py`
   - Normal Python client used by strategy/backtest code outside QMT.
   - Uses stdlib `urllib.request` initially.
   - Returns `pd.DataFrame` for kline-like endpoints where possible, and raw dicts for tick/local-data shapes.

Default network posture:
- Bind to `127.0.0.1` only.
- Require a simple bearer token or shared secret from env/config even for local calls.
- Add request size and timeout limits.
- Do not expose trading APIs such as `passorder`, `order_target_percent`, `cancel`, or account callbacks in this service.

## API Shape

Minimal endpoints:

- `GET /health`
  - Confirms server is alive and whether `ContextInfo` has been registered.

- `POST /v1/market-data-ex`
  - Wraps `ContextInfo.get_market_data_ex`.
  - Body:
    ```json
    {
      "fields": ["open", "high", "low", "close", "volume"],
      "stock_code": ["510300.SH"],
      "period": "1d",
      "start_time": "20240101",
      "end_time": "20241231",
      "count": -1,
      "dividend_type": "front",
      "fill_data": true,
      "subscribe": false
    }
    ```
  - Response:
    ```json
    {
      "ok": true,
      "data": {
        "510300.SH": {
          "columns": ["time", "open", "high", "low", "close", "volume"],
          "records": [
            {"time": "20240102", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 1000}
          ]
        }
      }
    }
    ```

- `POST /v1/market-data`
  - Wraps `ContextInfo.get_market_data`.
  - Must preserve the flexible return shapes but tag them:
    - `{"type": "scalar", "value": ...}`
    - `{"type": "series", "records": ...}`
    - `{"type": "dataframe", "records": ...}`
    - `{"type": "dict", "data": ...}`

- `POST /v1/history-data`
  - Wraps `ContextInfo.get_history_data`.
  - Because QMT requires `set_universe()` for this method, either:
    - require `stock_code` and call `ContextInfo.set_universe(stock_code)` inside a guarded section before fetching, or
    - document that the endpoint uses the strategy's current universe.
  - Recommended first implementation: require explicit `stock_code` and call `set_universe()` only if this service owns a separate data-universe setting.

- `POST /v1/full-tick`
  - Wraps `ContextInfo.get_full_tick`.

- `POST /v1/local-data`
  - Wraps `ContextInfo.get_local_data`.

Deferred endpoint:
- `POST /v1/subscribe-quote`
  - Subscription callbacks need long-running state and push delivery semantics. Do not include in v1 unless a consuming strategy actually needs streaming.

## Implementation Steps

1. Add tests first with a fake QMT context.
   - Create `tests/qmt_data_gateway_test.py`.
   - Fake `ContextInfo` implements the five planned data methods and records received params.
   - Test allowed params, rejected unknown methods/params, JSON normalization for scalar/Series/DataFrame/dict, and auth failure.

2. Implement QMT adapter.
   - Add `qmt/data_adapter.py`.
   - Expose only explicitly supported methods.
   - Use exact QMT parameter names from the docs:
     - `get_history_data(len, period, field, dividend_type=0, skip_paused=True)`
     - `get_market_data(fields, stock_code=[], start_time='', end_time='', skip_paused=True, period='1d', dividend_type='none', count=-1)`
     - `get_market_data_ex(fields=[], stock_code=[], period='follow', start_time='', end_time='', count=-1, dividend_type='follow', fill_data=True, subscribe=True)`
     - `get_full_tick(stock_code=[])`
     - `get_local_data(stock_code, start_time='', end_time='', period='1d', divid_type='none', count=-1)`
   - Keep method whitelist separate from endpoint routing.

3. Implement JSON normalization.
   - Add helpers in `qmt/data_gateway.py` or `qmt/serialization.py`.
   - Convert:
     - `pd.DataFrame`: reset index into `time` or `index`, replace NaN with null, return records.
     - `pd.Series`: return dict/records with field names.
     - `numpy` scalar types: convert to Python scalars.
     - `dict[str, pd.DataFrame]`: recursively normalize each value.
   - Preserve QMT code keys such as `510300.SH`.

4. Implement local HTTP server lifecycle.
   - `start_qmt_data_service(ContextInfo, host='127.0.0.1', port=8765, token=None)`.
   - `stop_qmt_data_service()`.
   - Run server in a daemon thread.
   - Return startup metadata and log port/token status without printing the token.
   - Guard against double-start when QMT reloads the strategy.

5. Wire a small QMT strategy example.
   - Add `qmt/data_service_strategy.py` with `# coding: gbk`.
   - In `init(ContextInfo)`, call `start_qmt_data_service(ContextInfo, ...)`.
   - In `stop(ContextInfo)`, call `stop_qmt_data_service()`.
   - Keep the file ASCII-only, matching the existing QMT file style.

6. Add a client for normal strategy code.
   - Add `utils/qmt_data_client.py`.
   - Provide `QmtDataClient(base_url, token)` with methods mirroring the supported endpoints.
   - Add `get_market_data_ex_df(...)` convenience method for one symbol -> DataFrame.
   - Add `to_backtrader_ohlcv(df)` helper if needed to map QMT fields to `date/open/high/low/close/volume`.

7. Optionally integrate into Streamlit after the bridge is proven.
   - Add a data-source selector in [frames/sidebar.py](/Users/udyrli/github.com/stock-backtrader-webapp/frames/sidebar.py:8) only after tests pass.
   - Add schema models in [utils/schemas.py](/Users/udyrli/github.com/stock-backtrader-webapp/utils/schemas.py:7) for QMT service params.
   - Split [utils/processing.py](/Users/udyrli/github.com/stock-backtrader-webapp/utils/processing.py:18) into provider-specific fetch functions:
     - `gen_akshare_stock_df`
     - `gen_qmt_stock_df`
     - common normalization to Backtrader columns.
   - Keep the current AkShare path as default to avoid breaking existing UI behavior.

8. Document the operating flow.
   - Add `docs/qmt_data_service.md`.
   - Include QMT strategy startup, local endpoint examples, security notes, and known limits.

## Acceptance Criteria

- `qmt/data_adapter.py` exposes only whitelisted QMT data methods.
- HTTP service can start and stop idempotently from QMT lifecycle methods.
- `POST /v1/market-data-ex` accepts QMT documented params and returns normalized JSON for `{code: pd.DataFrame}`.
- Unknown endpoint, unknown method, unknown parameter, malformed JSON, and missing/invalid token all return controlled 4xx responses.
- Client can request one symbol of OHLCV data and return a `pd.DataFrame`.
- Existing AkShare Streamlit path keeps working unchanged unless QMT UI integration is explicitly implemented.
- Tests pass without requiring a real QMT terminal by using fake `ContextInfo`.

## Risks and Mitigations

- Risk: QMT `ContextInfo` may not be thread-safe when called from an HTTP server thread.
  - Mitigation: v1 should keep endpoints read-only, local-only, and simple. If QMT runtime shows thread issues, change the gateway to enqueue requests and service them from `handlebar(ContextInfo)` or from a QMT-safe polling loop.

- Risk: `get_market_data()` return shape varies by argument combination.
  - Mitigation: tag response types and make `get_market_data_ex()` the preferred OHLCV endpoint.

- Risk: `get_history_data()` mutates/depends on universe.
  - Mitigation: document universe semantics and avoid using it for arbitrary multi-symbol client queries until behavior is tested in QMT.

- Risk: subscriptions require push semantics.
  - Mitigation: defer `subscribe_quote()` until there is a concrete streaming consumer; start with request/response data reads.

- Risk: exposing QMT data over HTTP may leak local market/account context.
  - Mitigation: bind `127.0.0.1`, require token, never expose trading/account/order endpoints.

## Verification Steps

Run:

```bash
uv run pytest -s tests/qmt_data_gateway_test.py
uv run pytest -s
```

Manual QMT verification:

1. Start `qmt/data_service_strategy.py` inside QMT.
2. Call `/health` locally and verify `ContextInfo` is registered.
3. Call `/v1/market-data-ex` for one ETF with `period='1d'`, `count=5`, `subscribe=false`.
4. Confirm returned rows have time/index plus requested OHLCV fields.
5. Stop/reload the QMT strategy and confirm the server releases the port.

## ADR

Decision:
- Build a local QMT-side HTTP data gateway using Python stdlib first, plus a normal Python client for consumers.

Drivers:
- QMT data methods require `ContextInfo`, which exists inside the QMT strategy lifecycle.
- The current Web app is AkShare-first and should not be broken by adding QMT data access.
- Project guidance prohibits adding new dependencies without explicit request.
- Strategy consumers need stable data shapes despite QMT's flexible return types.

Alternatives considered:
- Add FastAPI immediately: rejected because it adds dependencies and may not be available in QMT's Python runtime.
- Call QMT APIs directly from the Streamlit process: rejected because `ContextInfo` is not available there.
- Expose all `ContextInfo` methods dynamically: rejected because it creates a broad unsafe surface and could accidentally expose trading/account operations.
- Start with `subscribe_quote()` streaming: rejected because request/response OHLCV access is simpler and covers the current `get_market_data_ex()` usage.

Why chosen:
- A local HTTP gateway preserves QMT lifecycle constraints while decoupling strategy/backtest code from direct `ContextInfo` calls.
- The stdlib implementation is portable and reversible.
- A whitelist adapter keeps the first version narrow and safer.

Consequences:
- The service must run inside QMT before external code can query it.
- Real QMT thread-safety must be validated manually.
- Streaming subscriptions remain a second-phase design.

Follow-ups:
- After v1 is verified in QMT, decide whether to integrate QMT as a selectable Streamlit data provider.
- If multiple clients or streaming are required, revisit whether FastAPI/WebSocket dependencies are worth adding.
