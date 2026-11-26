"""46-factor target weights -> shared portfolios -> paper/QMT order execution."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.datahub.bootstrap import create_service
from src.datahub.providers.qmt_trading import QmtTradingProvider
from src.trading.execution import ExecutionEngine
from src.trading.market import live_quotes
from src.trading.portfolio import PortfolioLedger
from src.trading.replay import read_targets, run_replay
from src.trading.targets import target_weights

SHANGHAI = ZoneInfo("Asia/Shanghai")
BASE = Path("examples/intraday_factors/refresh_20261124/backtest")


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), flush=True)


def export_state(output, engine, quotes):
    output.mkdir(parents=True, exist_ok=True)
    state = engine.snapshot(quotes)
    pd.DataFrame(state["positions"]).to_csv(output / "holdings.csv", index=False)
    pd.DataFrame(engine.ledger.orders(engine.account_id, engine.strategy_id)).to_csv(output / "orders.csv", index=False)
    state["positions"] = len(state["positions"])
    (output / "account.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return state


def main(argv=None, *, default_strategy="intraday46", default_targets=BASE / "targets.csv",
         output_root=Path("examples/intraday_factors/execution")):
    parser = argparse.ArgumentParser(description="策略目标权重的回放、模拟与QMT执行")
    parser.add_argument("command", choices=["backtest", "paper", "plan", "execute", "watch", "status", "cancel"])
    parser.add_argument("--targets", type=Path, default=default_targets)
    parser.add_argument("--reference-dir", type=Path,
                        default=Path("data/intraday_factors/refresh_20261124/reference_data") if default_strategy else None)
    parser.add_argument("--output-dir", type=Path, help="defaults to a separate directory for each command")
    parser.add_argument("--ledger", type=Path, default=Path("data/trading/portfolios.sqlite"))
    parser.add_argument("--strategy", default=default_strategy, required=default_strategy is None)
    parser.add_argument("--account", help="must match the configured QMT account; no auto adoption of positions")
    parser.add_argument("--capital", type=float, default=1_000_000.)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--trade-date", help="choose a target execution date; default latest date in the input")
    parser.add_argument("--datahub-config", type=Path, default=Path("src/datahub/config/trading.yaml"))
    parser.add_argument("--enable-orders", action="store_true", help="allow dispatch to QMT; never changes the server switch")
    parser.add_argument("--seconds", type=float, default=0., help="watch duration; execute also resumes sells->buys")
    parser.add_argument("--interval", type=float, default=2.)
    parser.add_argument("--client-id", help="owned durable order id to cancel")
    args = parser.parse_args(argv)
    if args.output_dir is None:
        args.output_dir = output_root / args.strategy / args.command if default_strategy is None else output_root / args.command
    if args.command in {"backtest", "paper", "plan", "execute"}:
        if args.targets is None:
            parser.error("this command requires --targets")
        targets = read_targets(args.targets)
        if "strategy_id" in targets and (targets.strategy_id.isna().any()
                or set(targets.strategy_id) != {args.strategy}):
            parser.error("target strategy_id must match --strategy")
    if args.seconds < 0 or not 0 < args.interval <= 60:
        parser.error("seconds must be nonnegative; interval must be in (0,60]")
    if args.command in {"backtest", "paper"} and args.reference_dir is None:
        parser.error("backtest/paper requires --reference-dir with raw daily execution prices")
    if args.command == "backtest":
        dump(run_replay(args.targets, args.reference_dir, args.output_dir, initial_cash=args.capital,
                        strategy_id=args.strategy, start=args.start, end=args.end))
        return
    if args.command == "status":
        if not args.ledger.exists() or not args.account:
            parser.error("status needs an existing --ledger and explicit --account")
        ledger = PortfolioLedger(args.ledger)
        try:
            dump({"wallet": ledger.wallet(args.account, args.strategy),
                  "positions": ledger.positions(args.account, args.strategy),
                  "orders": ledger.orders(args.account, args.strategy)})
        finally:
            ledger.close()
        return
    if args.command == "paper":
        day = args.trade_date or targets.trade_date.max()
        group = targets[targets.trade_date.eq(day)]
        if group.empty:
            parser.error("no targets for requested date")
        # Single-rebalance paper test uses the same DataHub historical replay.
        dump(run_replay(args.targets, args.reference_dir, args.output_dir, initial_cash=args.capital,
                        strategy_id=args.strategy, start=day, end=day))
        return
    if args.command in {"execute", "cancel"} and not args.enable_orders:
        parser.error("dispatch is disabled; use plan/watch or explicitly pass --enable-orders")
    broker = QmtTradingProvider(args.account, enable_orders=args.enable_orders)
    ledger = PortfolioLedger(args.ledger)
    service = None
    engine = None
    try:
        now = datetime.now(SHANGHAI)
        if args.command == "watch":
            # Listening needs no initialized strategy wallet and never sends.
            engine = ExecutionEngine(ledger, broker, args.strategy)
            deadline = time.monotonic() + args.seconds
            while True:
                events = engine.sync()
                dump({"time": datetime.now(SHANGHAI).isoformat(), "events": events,
                      "orders": ledger.orders(broker.account_id, args.strategy),
                      "unresolved": len(ledger.unresolved(broker.account_id, args.strategy))})
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(args.interval, max(0., deadline - time.monotonic())))
            return
        if args.command == "cancel":
            if not args.client_id:
                parser.error("cancel requires --client-id")
            engine = ExecutionEngine(ledger, broker, args.strategy)
            engine.sync()
            engine.cancel(args.client_id)
            dump(ledger.order(args.client_id))
            return
        day = args.trade_date or targets.trade_date.max()
        group = targets[targets.trade_date.eq(day)]
        if group.empty:
            raise ValueError("no target portfolio on requested date")
        signal = group.signal_date.iloc[0]
        weights = target_weights(group)
        # Never backdate a real wallet to an old research target.
        ledger.create_portfolio(broker.account_id, args.strategy, args.capital, now.date().isoformat())
        service = create_service(config_path=args.datahub_config)
        engine = ExecutionEngine(ledger, broker, args.strategy)
        engine.sync()
        symbols = set(weights) | set(ledger.positions(broker.account_id, args.strategy))
        quotes = live_quotes(service, symbols, now)
        if args.command == "plan":
            snapshot = engine.snapshot(quotes)
            planned = []
            held = ledger.positions(broker.account_id, args.strategy)
            for symbol in sorted(symbols):
                q = quotes[symbol]
                desired = q.buy_quantity(snapshot["equity"] * weights.get(symbol, 0.) / q.price)
                planned.append({"symbol": symbol, "current_quantity": held.get(symbol, {}).get("quantity", 0),
                                "target_quantity": desired, "price": q.price,
                                "target_weight": weights.get(symbol, 0.), "quote_time": q.timestamp.isoformat()})
            result = {"mode": "plan_only_no_dispatch", "signal_date": signal, "requested_trade_date": day,
                      "now": now.isoformat(), "stale_target": day != now.date().isoformat(),
                      "reconciliation": ledger.reconciliation(broker.account_id, broker.snapshot()),
                      "positions_adopted_from_account": False, "planned_positions": planned}
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "qmt_plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            dump(result)
            return
        deadline = time.monotonic() + args.seconds
        while True:
            now = datetime.now(SHANGHAI)
            quotes = live_quotes(service, symbols, now)
            result = engine.rebalance(weights, quotes, signal_date=signal, trade_date=day, now=now)
            dump({**result, **export_state(args.output_dir, engine, quotes)})
            if result["status"] in {"completed", "completed_with_deviation", "incomplete", "unknown", "rejected"} or time.monotonic() >= deadline:
                break
            time.sleep(min(args.interval, max(0., deadline - time.monotonic())))
    finally:
        if engine:
            engine.close()
        else:
            broker.close()
        ledger.close()
        if service:
            service.close()


if __name__ == "__main__":
    main()
