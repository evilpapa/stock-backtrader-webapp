"""Durable virtual portfolios; broker account positions never imply ownership.

All balances, reservations and fills are changed under SQLite BEGIN IMMEDIATE.
One database must be shared by all strategies trading the same physical account.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.datahub.ticker import TickerMapper
from src.trading.models import BrokerEvent, OrderRequest, TERMINAL, iso_day, positive
from src.utils.commission import ChinaStockCommission


class PortfolioLedger:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.commission = ChinaStockCommission()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS wallets(
          account TEXT, strategy TEXT, cash REAL NOT NULL, initial_cash REAL NOT NULL,
          day TEXT NOT NULL, PRIMARY KEY(account,strategy));
        CREATE TABLE IF NOT EXISTS positions(
          account TEXT, strategy TEXT, symbol TEXT, quantity INTEGER NOT NULL,
          sellable INTEGER NOT NULL, cost REAL NOT NULL, PRIMARY KEY(account,strategy,symbol));
        CREATE TABLE IF NOT EXISTS batches(
          id TEXT PRIMARY KEY, account TEXT, strategy TEXT, signal_date TEXT, trade_date TEXT,
          digest TEXT, payload TEXT, UNIQUE(account,strategy,trade_date));
        CREATE TABLE IF NOT EXISTS orders(
          client_id TEXT PRIMARY KEY, account TEXT, strategy TEXT, batch_id TEXT, symbol TEXT,
          side TEXT, quantity INTEGER, limit_price REAL, trade_date TEXT, status TEXT,
          broker_id TEXT DEFAULT '', filled INTEGER DEFAULT 0, reported INTEGER DEFAULT 0,
          notional REAL DEFAULT 0, fee REAL DEFAULT 0, detail TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS fills(
          account TEXT, trade_date TEXT, trade_id TEXT, client_id TEXT, quantity INTEGER,
          price REAL, fee REAL, symbol TEXT, PRIMARY KEY(account,trade_date,symbol,trade_id));
        CREATE TABLE IF NOT EXISTS events(
          id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS adjustments(
          id TEXT PRIMARY KEY, account TEXT, strategy TEXT, day TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS cancel_requests(
          client_id TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT DEFAULT '');
        """)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def fee(self, notional: float) -> float:
        return self.commission.getcommission(1, notional) if notional > 0 else 0.

    def create_portfolio(self, account: str, strategy: str, cash: float, day: str):
        positive(cash, "initial_cash")
        if not account or not strategy:
            raise ValueError("account and strategy are required")
        day = iso_day(day)
        with self.transaction():
            existing = self.db.execute("SELECT * FROM wallets WHERE account=? AND strategy=?", (account, strategy)).fetchone()
            if existing:
                if not math.isclose(existing["initial_cash"], cash, abs_tol=1e-8):
                    raise ValueError("existing portfolio capital differs; use a new portfolio")
                return
            self.db.execute("INSERT INTO wallets VALUES(?,?,?,?,?)", (account, strategy, cash, cash, day))

    def wallet(self, account, strategy):
        row = self.db.execute("SELECT * FROM wallets WHERE account=? AND strategy=?", (account, strategy)).fetchone()
        if row is None:
            raise ValueError("portfolio not initialized")
        return dict(row)

    def positions(self, account, strategy):
        return {r["symbol"]: dict(r) for r in self.db.execute(
            "SELECT * FROM positions WHERE account=? AND strategy=? AND quantity>0", (account, strategy))}

    def orders(self, account, strategy):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM orders WHERE account=? AND strategy=? ORDER BY rowid", (account, strategy))]

    @staticmethod
    def pending(row):
        # Terminal order pushes can arrive before the matching trade push.
        return max(0, (row["reported"] if row["status"] in TERMINAL else row["quantity"]) - row["filled"])

    def available_cash(self, account, strategy):
        cash = self.wallet(account, strategy)["cash"]
        for r in self._pending_orders(account, strategy):
            remaining = self.pending(r)
            if remaining and r["side"] == "buy":
                amount = remaining * r["limit_price"]
                cash -= amount + max(0., self.fee(r["notional"] + amount) - r["fee"])
        return cash

    def available_shares(self, account, strategy, symbol):
        position = self.positions(account, strategy).get(symbol, {})
        pending = sum(self.pending(r) for r in self._pending_orders(account, strategy)
                      if r["symbol"] == symbol and r["side"] == "sell")
        return max(0, position.get("sellable", 0) - pending)

    def unresolved(self, account, strategy):
        return self._pending_orders(account, strategy)

    def _pending_orders(self, account, strategy):
        return [dict(r) for r in self.db.execute(
            """SELECT * FROM orders WHERE account=? AND strategy=? AND
               (status NOT IN ('filled','canceled','rejected') OR reported>filled)""", (account, strategy))]

    def advance_day(self, account, strategy, day):
        day = iso_day(day)
        with self.transaction():
            old = self.wallet(account, strategy)["day"]
            if day < old:
                raise ValueError("portfolio time cannot go backwards")
            if day > old:
                if self.unresolved(account, strategy):
                    raise RuntimeError("previous-day orders unresolved; reconcile before rollover")
                self.db.execute("UPDATE positions SET sellable=quantity WHERE account=? AND strategy=?", (account, strategy))
                self.db.execute("UPDATE wallets SET day=? WHERE account=? AND strategy=?", (day, account, strategy))

    def seed_position(self, account, strategy, symbol, quantity, sellable, cost):
        """Explicit migration only; never infer strategy ownership from a snapshot."""
        symbol = TickerMapper.normalize(symbol)
        if not isinstance(quantity, int) or not 0 <= sellable <= quantity or quantity <= 0:
            raise ValueError("invalid seed quantity")
        positive(cost, "position cost")
        with self.transaction():
            self.wallet(account, strategy)
            self.db.execute("INSERT INTO positions VALUES(?,?,?,?,?,?)",
                            (account, strategy, symbol, quantity, sellable, cost))

    def create_batch(self, account, strategy, signal_date, trade_date, payload):
        signal_date, trade_date = iso_day(signal_date), iso_day(trade_date)
        if signal_date >= trade_date:
            raise ValueError("signal must precede execution date")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        batch_id = hashlib.sha256(f"{account}|{strategy}|{trade_date}".encode()).hexdigest()[:24]
        with self.transaction():
            self.wallet(account, strategy)
            row = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if row and (row["digest"] != digest or row["signal_date"] != signal_date):
                raise ValueError("different rebalance already exists for this strategy/date")
            if not row:
                self.db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?,?)",
                                (batch_id, account, strategy, signal_date, trade_date, digest, encoded))
        return batch_id

    def get_batch(self, account, strategy, trade_date):
        row = self.db.execute("SELECT * FROM batches WHERE account=? AND strategy=? AND trade_date=?",
                              (account, strategy, iso_day(trade_date))).fetchone()
        return dict(row) if row else None

    def reserve(self, order: OrderRequest):
        """Return False for an existing identity; never send it again after restart."""
        if order.side not in {"buy", "sell"} or type(order.quantity) is not int or order.quantity <= 0:
            raise ValueError("invalid order")
        positive(order.limit_price, "limit price")
        with self.transaction():
            existing = self.order(order.client_id)
            if existing:
                self.validate_identity(order, existing)
                return False
            if self.wallet(order.account_id, order.strategy_id)["day"] != order.trade_date:
                raise ValueError("order date differs from portfolio date")
            if order.side == "buy":
                required = order.quantity * order.limit_price + self.fee(order.quantity * order.limit_price)
                if required > self.available_cash(order.account_id, order.strategy_id) + 1e-7:
                    raise ValueError("insufficient strategy cash")
            elif order.quantity > self.available_shares(order.account_id, order.strategy_id, order.symbol):
                raise ValueError("insufficient settled strategy shares")
            self.db.execute("""INSERT INTO orders(client_id,account,strategy,batch_id,symbol,side,quantity,
              limit_price,trade_date,status) VALUES(?,?,?,?,?,?,?,?,?,'sending')""",
              (order.client_id, order.account_id, order.strategy_id, order.batch_id, order.symbol,
               order.side, order.quantity, order.limit_price, order.trade_date))
        return True

    @staticmethod
    def validate_identity(order, existing):
        expected = (order.account_id, order.strategy_id, order.batch_id, order.symbol,
                    order.side, order.quantity, order.limit_price, order.trade_date)
        actual = tuple(existing[k] for k in ("account", "strategy", "batch_id", "symbol",
                                             "side", "quantity", "limit_price", "trade_date"))
        if actual != expected:
            raise ValueError("client_id reused with different order parameters")

    def claim_cancel(self, client_id, account, strategy):
        """Durably claim one cancellation before making any remote request."""
        with self.transaction():
            row = self.order(client_id)
            if not row or row["account"] != account or row["strategy"] != strategy:
                raise ValueError("order is not owned by this strategy")
            if row["status"] in TERMINAL:
                return False
            if not row["broker_id"]:
                raise RuntimeError("unknown broker id; reconcile rather than cancel blindly")
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO cancel_requests(client_id,state) VALUES(?,'sending')",
                (client_id,)).rowcount
            if inserted:
                self.db.execute("UPDATE orders SET status='cancel_pending' WHERE client_id=?", (client_id,))
            return bool(inserted)

    def cancel_result(self, client_id, state, detail=""):
        with self.transaction():
            self.db.execute("UPDATE cancel_requests SET state=?,detail=? WHERE client_id=?",
                            (state, detail, client_id))

    def cancellation(self, client_id):
        row = self.db.execute("SELECT * FROM cancel_requests WHERE client_id=?", (client_id,)).fetchone()
        return dict(row) if row else None

    def order(self, client_id):
        row = self.db.execute("SELECT * FROM orders WHERE client_id=?", (client_id,)).fetchone()
        return dict(row) if row else None

    def update_status(self, client_id, status, broker_id="", reported=0, detail=""):
        with self.transaction():
            row = self.order(client_id)
            if row is None:
                return
            if not 0 <= reported <= row["quantity"]:
                raise ValueError("invalid reported fill quantity")
            if row["broker_id"] and broker_id and broker_id != row["broker_id"]:
                raise ValueError("conflicting broker identity")
            if row["status"] in TERMINAL and status != "filled":
                status = row["status"]
            elif row["status"] in {"partial", "cancel_pending"} and status == "submitted":
                status = row["status"]  # A delayed acknowledgement cannot undo progress.
            if row["filled"] == row["quantity"]:
                status = "filled"
            self.db.execute("UPDATE orders SET status=?,broker_id=?,reported=?,detail=? WHERE client_id=?",
                            (status, broker_id or row["broker_id"], max(reported, row["reported"], row["filled"]),
                             detail or row["detail"], client_id))

    def resolve_event(self, event: BrokerEvent):
        row = self.order(event.client_id) if event.client_id else None
        if row is None and event.broker_id:
            # Broker order ids may repeat across days: constrain by event day.
            rows = list(self.db.execute("SELECT * FROM orders WHERE account=? AND broker_id=? AND trade_date=?",
                        (event.account_id, event.broker_id, event.timestamp.date().isoformat())))
            row = dict(rows[0]) if len(rows) == 1 else None
        if row and (row["account"] != event.account_id or
                    (event.symbol and row["symbol"] != event.symbol) or
                    (event.side and row["side"] != event.side) or
                    row["trade_date"] != event.timestamp.date().isoformat()):
            raise ValueError("event identity differs from durable order")
        return row

    def record_event(self, event: BrokerEvent):
        payload = json.dumps(asdict(event), sort_keys=True, default=str, allow_nan=False)
        key = hashlib.sha256(payload.encode()).hexdigest()
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?)", (key, payload))

    def apply_fill(self, event: BrokerEvent, client_id: str):
        if not event.trade_id or type(event.quantity) is not int or event.quantity <= 0:
            raise ValueError("fill needs a stable trade id and positive integer quantity")
        positive(event.price, "fill price")
        day = event.timestamp.date().isoformat()
        with self.transaction():
            existing = self.db.execute("SELECT * FROM fills WHERE account=? AND trade_date=? AND symbol=? AND trade_id=?",
                                       (event.account_id, day, event.symbol, event.trade_id)).fetchone()
            if existing:
                if existing["client_id"] != client_id or existing["quantity"] != event.quantity or existing["price"] != event.price:
                    raise ValueError("same trade id has conflicting fill payload")
                return False
            row = self.order(client_id)
            if (row is None or row["account"] != event.account_id or row["trade_date"] != day
                    or row["symbol"] != event.symbol or row["side"] != event.side):
                raise ValueError("fill has no matching order/date")
            if self.wallet(row["account"], row["strategy"])["day"] != day:
                raise RuntimeError("late fill after rollover; explicit reconciliation required")
            qty, px = event.quantity, event.price
            if row["filled"] + qty > row["quantity"]:
                raise ValueError("overfill")
            if (row["side"] == "buy" and px > row["limit_price"] + 1e-7 or
                    row["side"] == "sell" and px < row["limit_price"] - 1e-7):
                raise ValueError("fill violates limit price")
            amount = qty * px
            fee = self.fee(row["notional"] + amount) - row["fee"]
            account, strategy, symbol = row["account"], row["strategy"], row["symbol"]
            p = self.positions(account, strategy).get(symbol, {"quantity": 0, "sellable": 0, "cost": 0.})
            cash_delta = -amount - fee if row["side"] == "buy" else amount - fee
            if self.wallet(account, strategy)["cash"] + cash_delta < -1e-7:
                raise ValueError("fill would create negative cash")
            if row["side"] == "buy":
                cost = (p["cost"] * p["quantity"] + amount + fee) / (p["quantity"] + qty)
                new_qty, sellable = p["quantity"] + qty, p["sellable"]
            else:
                if qty > p["sellable"]:
                    raise ValueError("fill exceeds settled strategy ownership")
                new_qty, sellable, cost = p["quantity"] - qty, p["sellable"] - qty, p["cost"]
            self.db.execute("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?)",
                            (account, strategy, symbol, new_qty, sellable, cost))
            self.db.execute("UPDATE wallets SET cash=cash+? WHERE account=? AND strategy=?", (cash_delta, account, strategy))
            filled = row["filled"] + qty
            status = "filled" if filled == row["quantity"] else (row["status"] if row["status"] in TERMINAL else "partial")
            self.db.execute("""UPDATE orders SET filled=?,reported=MAX(reported,?),notional=notional+?,
                            fee=fee+?,status=? WHERE client_id=?""", (filled, filled, amount, fee, status, client_id))
            self.db.execute("INSERT INTO fills VALUES(?,?,?,?,?,?,?,?)", (account, day, event.trade_id, client_id, qty, px, fee, symbol))
        return True

    def corporate_action_proxy(self, account, strategy, day, ratios: dict[str, tuple[float, float]]):
        """Research-only value preserving share conversion, never applied to QMT.

        ratios maps symbol to (last raw close, today's pre_close). Remainders
        become simulated cash. This is NOT a real dividend/corporate-action book.
        """
        day = iso_day(day)
        with self.transaction():
            if self.unresolved(account, strategy):
                raise RuntimeError("cannot adjust positions with pending orders")
            for symbol, (previous, reference) in ratios.items():
                positive(previous, "previous close"); positive(reference, "pre close")
                key = f"proxy:{account}:{strategy}:{day}:{symbol}"
                if abs(previous - reference) <= .0051 or self.db.execute("SELECT 1 FROM adjustments WHERE id=?", (key,)).fetchone():
                    continue
                p = self.positions(account, strategy).get(symbol)
                if not p:
                    continue
                exact = p["quantity"] * previous / reference
                quantity = math.floor(exact + 1e-9)
                cash_delta = (exact - quantity) * reference
                self.db.execute("UPDATE positions SET quantity=?,sellable=?,cost=? WHERE account=? AND strategy=? AND symbol=?",
                                (quantity, quantity, p["cost"] * p["quantity"] / max(quantity, 1), account, strategy, symbol))
                self.db.execute("UPDATE wallets SET cash=cash+? WHERE account=? AND strategy=?", (cash_delta, account, strategy))
                self.db.execute("INSERT INTO adjustments VALUES(?,?,?,?,?)",
                                (key, account, strategy, day, json.dumps({"ratio": previous/reference, "cash": cash_delta})))

    def reconciliation(self, account, snapshot):
        if snapshot.get("account_id") != account:
            raise ValueError("broker account mismatch")
        allocated_cash = self.db.execute("SELECT COALESCE(SUM(cash),0) FROM wallets WHERE account=?", (account,)).fetchone()[0]
        actual = {p["symbol"]: p for p in snapshot["positions"]}
        allocated = {r["symbol"]: int(r["quantity"]) for r in self.db.execute(
            "SELECT symbol,SUM(quantity) AS quantity FROM positions WHERE account=? GROUP BY symbol", (account,))}
        shortage = {s: qty - actual.get(s, {}).get("quantity", 0) for s, qty in allocated.items()
                    if qty > actual.get(s, {}).get("quantity", 0)}
        extra = {s: p["quantity"] - allocated.get(s, 0) for s, p in actual.items() if p["quantity"] > allocated.get(s, 0)}
        available = {}
        for r in self.db.execute("SELECT DISTINCT strategy FROM wallets WHERE account=?", (account,)):
            for symbol in self.positions(account, r["strategy"]):
                available[symbol] = available.get(symbol, 0) + self.available_shares(account, r["strategy"], symbol)
        sellable_shortage = {s: qty - actual.get(s, {}).get("sellable", 0) for s, qty in available.items()
                            if qty > actual.get(s, {}).get("sellable", 0)}
        capacity = snapshot["cash"] + snapshot.get("frozen_cash", 0.)
        unknown = [o for o in snapshot.get("orders", []) if o["status"] not in TERMINAL and not self.resolve_event(o["event"])]
        return {"ok": not shortage and not sellable_shortage and allocated_cash <= capacity + .02 and not unknown,
                "position_shortages": shortage, "unallocated_positions": extra,
                "sellable_shortages": sellable_shortage,
                "allocated_cash": allocated_cash, "broker_cash_and_frozen": capacity,
                "unmanaged_open_orders": len(unknown)}

    def close(self):
        self.db.close()
