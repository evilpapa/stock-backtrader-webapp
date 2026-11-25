"""QMT order Adapter. This is the only new module importing the broker SDK.

Use an independent trader instance (no process-wide configure singleton).
Callbacks enqueue normalized events; polling repairs missed pub/sub messages.
"""
from __future__ import annotations

import math
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from src.datahub.ticker import TickerMapper
from src.trading.models import BrokerEvent, OrderDisabled, OrderRequest

SHANGHAI = ZoneInfo("Asia/Shanghai")
STATUSES = {48: "submitted", 49: "submitted", 50: "submitted", 51: "cancel_pending",
            52: "cancel_pending", 53: "canceled", 54: "canceled", 55: "partial",
            56: "filled", 57: "rejected", 255: "unknown"}


def field(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


class QmtTradingProvider:
    requires_fresh_quotes = True

    def __init__(self, account_id: str | None = None, *, enable_orders=False, trader=None, clock=None):
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.enable_orders = enable_orders
        if trader is None:
            from bigqmt_signal_trader.xtquant_compat import BigQmtXtTrader
            trader = BigQmtXtTrader()
        self.trader = trader
        configured = str(trader.client.account_id or "")
        if not configured or account_id and account_id != configured:
            raise ValueError("configured QMT account differs from requested account")
        self.account_id = configured
        # StockAccount is only a value object; no SDK calls escape this Adapter.
        self.account = SimpleNamespace(account_id=configured, account_type="STOCK")
        self.callback = None
        self.started = False

    def health(self):
        """Read-only deployment check; never enables trading or reloads QMT."""
        result = self.trader.client.call("ping")
        if not isinstance(result, dict) or not result.get("pong"):
            raise RuntimeError("QMT did not return a valid ping")
        if str(result.get("account_id", "")) != self.account_id:
            raise ValueError("QMT ping account mismatch")
        return result

    def deployment_info(self):
        """Read-only location/version diagnostics; does not deploy or reload."""
        return self.trader.client.call("get_deployment_info") or {}

    def _time(self, obj, kind):
        value = field(obj, "traded_time" if kind == "trade" else "order_time", 0)
        if not value and kind == "trade":
            value = field(obj, "traded_at")
        if value:
            try:
                if isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit():
                    number = float(value)
                    return datetime.fromtimestamp(number / 1000 if number > 1e11 else number, SHANGHAI)
                parsed = datetime.fromisoformat(str(value))
                return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)
            except (ValueError, OverflowError, OSError) as exc:
                raise ValueError("invalid broker event time") from exc
        if kind == "trade":
            raise ValueError("trade has no execution time; cannot safely deduplicate by trading day")
        return self.clock()

    def normalize(self, kind, obj):
        account = str(field(obj, "account_id", "") or "")
        if account != self.account_id:
            raise ValueError("broker event account mismatch")
        raw_symbol = field(obj, "stock_code", "") or ""
        symbol = TickerMapper.normalize(raw_symbol) if raw_symbol else ""
        raw_side = field(obj, "order_type")
        if raw_side not in (None, 23, 24):
            raise ValueError("only ordinary cash stock buy/sell are supported")
        side = {23: "buy", 24: "sell"}.get(raw_side, "")
        status = STATUSES.get(int(field(obj, "order_status", field(obj, "status", 255))), "unknown")
        broker_id = str(field(obj, "order_sysid", "") or field(obj, "order_sys_id", "") or field(obj, "order_id", "") or "")
        detail = str(field(obj, "error_msg", "") or field(obj, "status_msg", "") or "")
        if kind == "order_error" and (not broker_id or "order not found in system" in detail.lower()):
            # The bridge synthesizes status 57 after a settlement lookup timeout.
            # That is not proof the counter rejected it: retain the reservation.
            status = "unknown"
        filled = int(field(obj, "traded_volume", 0) or 0) if kind == "order" else 0
        if kind == "order" and status == "filled":
            filled = max(filled, int(field(obj, "order_volume", 0) or 0))
        return BrokerEvent(
            kind, account, self._time(obj, kind),
            str(field(obj, "order_remark", "") or ""),
            broker_id,
            symbol, side, status,
            int(field(obj, "traded_volume", 0) or 0) if kind == "trade" else 0,
            float(field(obj, "traded_price", 0.) or 0.) if kind == "trade" else 0.,
            str(field(obj, "trade_id", "") or field(obj, "traded_id", "") or ""),
            filled, detail)

    def start(self, callback):
        if self.started:
            raise RuntimeError("adapter already has an event consumer")
        self.callback = callback
        self.trader.client.call("ping")  # Read only; deliberately no auto-sync/connect deployment.
        owner = self

        class Callback:
            def emit(self, kind, value):
                try:
                    callback(owner.normalize(kind, value))
                except Exception as exc:
                    callback(BrokerEvent("adapter_error", owner.account_id, owner.clock(), detail=str(exc)))

            def on_stock_order(self, order): self.emit("order", order)
            def on_stock_trade(self, trade): self.emit("trade", trade)
            def on_order_error(self, error): self.emit("order_error", error)
            def on_cancel_error(self, error): self.emit("cancel_error", error)
            def on_account_status(self, status): pass
            def on_disconnected(self): callback(BrokerEvent("adapter_error", owner.account_id, owner.clock(), detail="broker disconnected"))

        self.trader.register_callback(Callback())
        self.trader.start()
        try:
            self.trader.subscribe(self.account)
        except Exception:
            self.trader.stop()
            raise
        self.started = True

    def submit(self, order: OrderRequest) -> str:
        if not self.enable_orders:
            raise OrderDisabled("client order dispatch disabled")
        if order.account_id != self.account_id:
            raise ValueError("order account mismatch")
        if order.side not in {"buy", "sell"} or type(order.quantity) is not int or order.quantity <= 0:
            raise ValueError("invalid cash order side/quantity")
        if not math.isfinite(order.limit_price) or order.limit_price <= 0:
            raise ValueError("invalid limit price")
        try:
            # Structured result retains the actual broker string id across restart.
            result = self.trader.order_stock_result(
                self.account, TickerMapper.to_xtquant(order.symbol), 23 if order.side == "buy" else 24,
                order.quantity, 11, order.limit_price, order.strategy_id, order.client_id)
        except Exception as exc:
            if "ORDER_DISABLED" in str(exc) or "rpc method is not allowed" in str(exc):
                raise OrderDisabled("server order dispatch disabled") from exc
            raise  # Timeout is unknown; never resubmit.
        broker_id = result.get("order_sys_id") if isinstance(result, dict) else None
        if not broker_id or str(broker_id) in {"0", "-1"}:
            raise RuntimeError("QMT returned no confirmed broker order id; reconcile by remark")
        return str(broker_id)

    def cancel(self, order, broker_id):
        if not self.enable_orders:
            raise OrderDisabled("client cancel dispatch disabled")
        if order.account_id != self.account_id:
            raise ValueError("cancel account mismatch")
        result = self.trader.cancel_order_stock_sysid(self.account, TickerMapper.to_exchange(order.symbol), broker_id)
        if isinstance(result, bool) or result != 0:
            raise RuntimeError("QMT did not acknowledge cancellation")

    def poll(self):
        orders = self.trader.query_stock_orders(self.account, cancelable_only=False, strategy_name="")
        trades = self.trader.query_stock_trades(self.account, strategy_name="")
        if orders is None or trades is None:
            raise RuntimeError("incomplete broker query")
        return [self.normalize("order", o) for o in orders] + [self.normalize("trade", t) for t in trades]

    def snapshot(self):
        asset = self.trader.query_stock_asset(self.account)
        positions = self.trader.query_stock_positions(self.account)
        orders = self.trader.query_stock_orders(self.account, cancelable_only=False, strategy_name="")
        if asset is None or positions is None or orders is None or str(field(asset, "account_id")) != self.account_id:
            raise RuntimeError("incomplete or mismatched account snapshot")
        cash = float(field(asset, "cash"))
        frozen = float(field(asset, "frozen_cash", 0.) or 0.)
        if not math.isfinite(cash) or not math.isfinite(frozen) or cash < 0 or frozen < 0:
            raise ValueError("invalid account cash")
        normalized_positions = []
        for p in positions:
            quantity, sellable = int(field(p, "volume")), int(field(p, "can_use_volume"))
            if str(field(p, "account_id")) != self.account_id or not 0 <= sellable <= quantity:
                raise ValueError("invalid broker position")
            normalized_positions.append({"symbol": TickerMapper.normalize(field(p, "stock_code")),
                                         "quantity": quantity, "sellable": sellable})
        return {"account_id": self.account_id, "cash": cash, "frozen_cash": frozen,
                "positions": normalized_positions,
                "orders": [{"status": STATUSES.get(int(field(o, "order_status", 255)), "unknown"),
                            "event": self.normalize("order", o)} for o in orders]}

    def close(self):
        self.trader.stop()
        self.started = False
