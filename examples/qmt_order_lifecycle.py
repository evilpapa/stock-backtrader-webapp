"""One QMT limit order, status recovery and cancellation through the shared engine.

Read-only preparation:
  python -m examples.qmt_order_lifecycle
One authorized 100-share buy, then cancel any remaining quantity:
  python -m examples.qmt_order_lifecycle --execute --enable-orders

The example submits at most once. A timeout never triggers a replacement order.
All strategies can call ExecutionEngine.submit_order/order_status/cancel directly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.datahub.bootstrap import create_service
from src.datahub.providers.qmt_trading import QmtTradingProvider
from src.trading import ExecutionEngine, PortfolioLedger
from src.trading.market import live_quotes
from src.trading.models import TERMINAL

SHANGHAI = ZoneInfo("Asia/Shanghai")


def redact(value, account):
    """Keep full account identifiers in the private ledger only."""
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    return text.replace(account, "***" + account[-4:])


def exit_code(report):
    """Expose unknown/rejected outcomes to shell automation, not only JSON."""
    if report["mode"] != "execute":
        return 0
    state = report.get("final_order", {})
    if state.get("failed"):
        return 2
    if not state.get("settled"):
        return 3
    return 0 if report.get("reconciliation", {}).get("ok") else 4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--enable-orders", action="store_true")
    parser.add_argument("--ledger", type=Path, default=Path("data/trading/portfolios.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("examples/trading/qmt_lifecycle_20261118"))
    parser.add_argument("--strategy", default="qmt_lifecycle_demo")
    parser.add_argument("--capital", type=float, default=1000.)
    parser.add_argument("--passive-ticks", type=int, default=20,
                        help="buy limit below latest price, in exchange price ticks")
    parser.add_argument("--seconds", type=float, default=30.)
    args = parser.parse_args(argv)
    if args.execute and not args.enable_orders:
        parser.error("--execute requires --enable-orders")
    if not 1 <= args.passive_ticks <= 100 or not 0 < args.seconds <= 60:
        parser.error("passive-ticks must be 1..100; seconds must be (0,60]")
    broker = QmtTradingProvider(enable_orders=args.execute and args.enable_orders)
    service, ledger, engine = None, None, None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"mode": "execute" if args.execute else "preflight", "symbol": "510300.SH",
              "side": "buy", "quantity": 100, "strategy_id": args.strategy, "observations": []}

    def save():
        name = "execution.json" if args.execute else "preflight.json"
        (args.output_dir / name).write_text(redact(report, broker.account_id) + "\n", encoding="utf-8")

    try:
        now = datetime.now(SHANGHAI)
        health = broker.health()
        if health.get("account_type") != "STOCK":
            raise ValueError("this example requires an ordinary cash STOCK account")
        report["health"] = health
        before = broker.snapshot()
        # Validate order/trade query and timestamp contracts before any dispatch.
        report["preflight_event_count"] = len(broker.poll())
        service = create_service(config_path="src/datahub/config/trading.yaml")
        quote = live_quotes(service, ["510300.SH"], now)["510300.SH"]
        price = round((round(quote.price / quote.price_tick) - args.passive_ticks) * quote.price_tick, 8)
        if not quote.tradable or not quote.lower_limit < price < quote.upper_limit:
            raise ValueError("no valid passive price or current continuous-trading quote")
        report.update({"prepared_at": now.isoformat(), "quote": asdict(quote), "limit_price": price,
                       "notional_cap": round(price * 100, 8),
                       "before": {"cash": before["cash"], "frozen_cash": before["frozen_cash"],
                                  "positions": [p for p in before["positions"] if p["symbol"] == quote.symbol],
                                  "order_count": len(before["orders"])}})
        save()
        if not args.execute:
            print(redact(report, broker.account_id))
            return report
        if health.get("allow_order_methods") is not True:
            raise ValueError("server order methods are disabled")
        ledger = PortfolioLedger(args.ledger)
        ledger.create_portfolio(broker.account_id, args.strategy, args.capital, now.date().isoformat())
        engine = ExecutionEngine(ledger, broker, args.strategy)
        engine.sync()
        identity = f"{broker.account_id}|{args.strategy}|{now.date()}|510300.SH|buy|100"
        client_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        report["client_id"] = client_id
        existing = ledger.order(client_id)
        if existing:
            # Recovery uses the saved price, never a newly generated identity.
            price = existing["limit_price"]
        # Re-read a fresh quote AFTER listener setup and all preparation.
        now = datetime.now(SHANGHAI)
        quote = live_quotes(service, ["510300.SH"], now)["510300.SH"]
        report["dispatch_quote"] = asdict(quote)
        report["limit_price"] = price
        report["notional_cap"] = round(price * 100, 8)
        save()
        state = engine.submit_order(client_id=client_id, symbol=quote.symbol, side="buy",
                                    quantity=100, limit_price=price, quote=quote, now=now)
        report["observations"].append({"time": datetime.now(SHANGHAI).isoformat(), **state})
        save()
        deadline = time.monotonic() + args.seconds
        cancel_attempted = bool(ledger.cancellation(client_id))
        while True:
            try:
                state = engine.order_status(client_id, refresh=True)
                if state["broker_id"] and state["status"] not in TERMINAL and not cancel_attempted:
                    cancel_attempted = True
                    state = engine.cancel(client_id)
                report["observations"].append({"time": datetime.now(SHANGHAI).isoformat(), **state})
                report["final_order"] = state
                save()
                if state["settled"] or time.monotonic() >= deadline:
                    break
            except Exception as exc:
                report.setdefault("monitor_errors", []).append(str(exc))
                save()
                if time.monotonic() >= deadline:
                    break
            time.sleep(min(1., max(0., deadline - time.monotonic())))
        state = engine.order_status(client_id)
        report["final_order"] = state
        report["workflow_completed"] = state["settled"]
        report["strategy_wallet"] = ledger.wallet(broker.account_id, args.strategy)
        report["strategy_positions"] = ledger.positions(broker.account_id, args.strategy)
        report["available_cash"] = ledger.available_cash(broker.account_id, args.strategy)
        after = broker.snapshot()
        report["after"] = {"cash": after["cash"], "frozen_cash": after["frozen_cash"],
                           "positions": [p for p in after["positions"] if p["symbol"] == quote.symbol],
                           "order_count": len(after["orders"])}
        report["reconciliation"] = ledger.reconciliation(broker.account_id, after)
        save()
        print(redact(report, broker.account_id))
        return report
    except Exception as exc:
        report["error"] = str(exc)
        save()
        raise
    finally:
        if engine:
            engine.close()
        else:
            broker.close()
        if ledger:
            ledger.close()
        if service:
            service.close()


if __name__ == "__main__":
    raise SystemExit(exit_code(main()))
