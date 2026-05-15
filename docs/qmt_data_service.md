# QMT Data Service

This project can expose selected QMT `ContextInfo` data methods through a local HTTP service. The service must run inside a QMT strategy process because `ContextInfo` is only available there.

## Start In QMT

Use `qmt/data_service_strategy.py` as a QMT strategy. The example starts the service in `init(ContextInfo)` and stops it in `stop(ContextInfo)`.

The example strategy reads these environment variables:

- `QMT_DATA_SERVICE_HOST`, default `127.0.0.1`
- `QMT_DATA_SERVICE_PORT`, default `8765`
- `QMT_DATA_SERVICE_TOKEN`, default empty

Keep the host on `127.0.0.1` unless you have a separate network security boundary.

## Supported Methods

The gateway only exposes read-only market data methods:

- `ContextInfo.get_history_data(len, period, field, dividend_type=0, skip_paused=True)`
- `ContextInfo.get_market_data(fields, stock_code=[], start_time='', end_time='', skip_paused=True, period='1d', dividend_type='none', count=-1)`
- `ContextInfo.get_market_data_ex(fields=[], stock_code=[], period='follow', start_time='', end_time='', count=-1, dividend_type='follow', fill_data=True, subscribe=True)`
- `ContextInfo.get_full_tick(stock_code=[])`
- `ContextInfo.get_local_data(stock_code, start_time='', end_time='', period='1d', divid_type='none', count=-1)`

Trading and account methods are intentionally not exposed.

## Example Request

```bash
curl -s http://127.0.0.1:8765/v1/market-data-ex \
  -H 'Authorization: Bearer your-token' \
  -H 'Content-Type: application/json' \
  -d '{
    "fields": ["open", "high", "low", "close", "volume"],
    "stock_code": ["510300.SH"],
    "period": "1d",
    "count": 5,
    "dividend_type": "front",
    "subscribe": false
  }'
```

## Python Client

```python
from utils.qmt_data_client import QmtDataClient, to_backtrader_ohlcv

client = QmtDataClient("http://127.0.0.1:8765", token="your-token")
df = client.get_market_data_ex_df(
    "510300.SH",
    fields=["open", "high", "low", "close", "volume"],
    period="1d",
    count=30,
    dividend_type="front",
    subscribe=False,
)
stock_df = to_backtrader_ohlcv(df)
```

## Notes

- `get_market_data_ex` is the preferred endpoint for OHLCV-style data because QMT returns `{code: pd.DataFrame}`.
- `get_market_data` can return scalar, Series, DataFrame, or dict shapes depending on params; the gateway tags normalized pandas payloads with `type`.
- `get_history_data` can optionally accept `stock_code`; the gateway calls `ContextInfo.set_universe(stock_code)` before fetching.
- Quote subscription is not exposed yet. It needs a separate push or polling design.
