"""Replay historical target weights using the SAME order/portfolio machinery."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.datahub import DataRequest
from src.datahub.models import DataKind
from src.datahub.research_daily_repository import ResearchDailyRepository
from src.datahub.router import DataRouter
from src.datahub.service import MarketDataService
from src.datahub.ticker import TickerMapper
from src.strategy_evaluation import evaluate_returns
from .execution import ExecutionEngine
from .market import stock_lot
from .models import Quote
from .paper import PaperBroker
from .portfolio import PortfolioLedger
from .targets import target_weights, validate_targets

SHANGHAI = ZoneInfo("Asia/Shanghai")


def read_targets(path):
    return validate_targets(pd.read_csv(path, dtype={"symbol": str}))


def run_replay(target_path, reference_dir, output_dir, *, initial_cash=1_000_000.,
               strategy_id="intraday46", start=None, end=None):
    targets = read_targets(target_path)
    if "strategy_id" in targets and set(targets.strategy_id) != {strategy_id}:
        raise ValueError("target strategy_id differs from replay portfolio")
    if start:
        targets = targets[targets.trade_date.ge(start)]
    if end:
        targets = targets[targets.trade_date.le(end)]
    if targets.empty:
        raise ValueError("no target dates in requested range")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "portfolio.sqlite"
    if ledger_path.exists():
        raise ValueError("replay output already has a ledger; use a new output directory")
    start, end = targets.trade_date.min(), end or targets.trade_date.max()
    source = Path(reference_dir) / "raw/daily"
    days = sorted(p for p in source.glob("*.parquet") if p.stem.isdigit()
                  and start.replace("-", "") <= p.stem <= end.replace("-", ""))
    if not days:
        raise ValueError("no cached daily prices")
    schedules = {day: group for day, group in targets.groupby("trade_date", sort=True)}
    symbols = tuple(sorted(s for s in targets.symbol.unique() if s))
    service = MarketDataService(DataRouter({}), repository=ResearchDailyRepository(reference_dir))
    ledger = PortfolioLedger(ledger_path)
    # Historical replay is rebuildable. Live ledgers retain SQLite FULL
    # durability; disabling per-fill fsync here avoids thousands of disk waits.
    ledger.db.execute("PRAGMA synchronous=NORMAL")
    ledger.create_portfolio("backtest", strategy_id, initial_cash, start)
    broker = PaperBroker("backtest")
    engine = ExecutionEngine(ledger, broker, strategy_id)
    nav, provenance, batches = [], [], []
    last_close = {}
    last_quotes = {}
    print(f"replaying {len(days)} days, {len(schedules)} target portfolios", flush=True)
    try:
        for i, path in enumerate(days):
            day = datetime.strptime(path.stem, "%Y%m%d").date().isoformat()
            now = datetime.combine(datetime.fromisoformat(day).date(), time(9, 30), SHANGHAI)
            ledger.advance_day("backtest", strategy_id, day)
            raw = service.get_cached(DataKind.DAILY_BULK, DataRequest(
                symbols=symbols, start=day, end=day, adjust="none"))
            if raw is None or raw.ts_code.duplicated().any():
                raise ValueError(f"missing/duplicate daily input: {day}")
            provenance.append({"date": day, "source": raw.attrs["source"], "frequency": "1d",
                               "adjust": "none", "data_version": raw.attrs["data_version"]})
            daily = raw.set_index("ts_code")
            owned = ledger.positions("backtest", strategy_id)
            ratios = {s: (last_close[s], float(daily.loc[s, "pre_close"]))
                      for s in owned if s in daily.index and s in last_close
                      and pd.notna(daily.loc[s, "pre_close"]) and daily.loc[s, "pre_close"] > 0}
            ledger.corporate_action_proxy("backtest", strategy_id, day, ratios)
            quotes = {}
            group = schedules.get(day)
            required = set(owned) | (set(group.symbol) - {""} if group is not None else set())
            for symbol in required:
                row = daily.loc[symbol] if symbol in daily.index else None
                price = float(row.open) if row is not None and pd.notna(row.open) else 0.
                tradable = math.isfinite(price) and price > 0
                if not tradable:
                    price = last_close.get(symbol, 0.)
                if price <= 0:
                    # A missing target price is observable; exclude it from
                    # today's plan rather than introducing a future quote.
                    continue
                pre = float(row.pre_close) if row is not None and pd.notna(row.pre_close) else 0.
                band = .20 if symbol.startswith(("688", "300", "301")) else .30 if TickerMapper.to_exchange(symbol) == "BJ" else .10
                upper, lower = (round(pre * (1 + band) + 1e-9, 2), round(pre * (1 - band) + 1e-9, 2)) if pre > 0 else (None, None)
                lot, step = stock_lot(symbol)
                quotes[symbol] = Quote(symbol, price, now, "research_daily", lot, step,
                                       .01, upper, lower, tradable)
            if set(ledger.positions("backtest", strategy_id)) - set(quotes):
                raise ValueError(f"no mark for owned position on {day}")
            broker.set_quotes(quotes)
            if group is not None:
                weights = {s: w for s, w in target_weights(group).items() if s in quotes}
                result = engine.rebalance(weights, quotes, signal_date=group.signal_date.iloc[0], trade_date=day, now=now)
                batches.append({"date": day, **result, "missing_target_prices": int((group.symbol.ne("") & ~group.symbol.isin(quotes)).sum())})
                # DAY orders expire in this daily-bar simulator, with a real
                # cancel event; a request acknowledgement alone never releases.
                for order in ledger.unresolved("backtest", strategy_id):
                    engine.cancel(order["client_id"])
                if ledger.unresolved("backtest", strategy_id):
                    raise RuntimeError("paper DAY orders failed to reach a terminal state")
            state = engine.snapshot(quotes)
            nav.append({"date": day, "cash": state["cash"], "equity": state["equity"],
                        "positions": len(state["positions"]), "rebalance": group is not None,
                        "stale_positions": sum(not quotes[s].tradable for s in ledger.positions("backtest", strategy_id))})
            for symbol, row in daily.iterrows():
                if pd.notna(row.close) and row.close > 0:
                    last_close[symbol] = float(row.close)
            last_quotes = quotes
            if (i + 1) % 200 == 0:
                print(f"replayed {i + 1}/{len(days)} days, equity={state['equity']:.2f}", flush=True)
        frame = pd.DataFrame(nav)
        frame["nav"] = frame.equity / initial_cash
        returns = frame.nav.pct_change(fill_method=None)
        returns.iloc[0] = frame.nav.iloc[0] - 1
        evaluation = evaluate_returns(returns)
        final = engine.snapshot(last_quotes)
        orders = ledger.orders("backtest", strategy_id)
        metrics = {
            "mode": "historical_paper_execution", "strategy": strategy_id,
            "first_trade_date": frame.date.iloc[0], "end_date": frame.date.iloc[-1],
            "rebalance_count": len(batches), "initial_cash": initial_cash, "final_equity": final["equity"],
            "total_commission": sum(r["fee"] for r in orders), "orders": len(orders),
            "fills": ledger.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0],
            "final_holdings": len(final["positions"]), "final_cash": final["cash"],
            "unresolved_orders": len(ledger.unresolved("backtest", strategy_id)),
            "targets_sha256": hashlib.sha256(Path(target_path).read_bytes()).hexdigest(),
            "execution_code_sha256": {
                name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                for name in ("src/trading/models.py", "src/trading/portfolio.py",
                             "src/trading/execution.py", "src/trading/paper.py", "src/trading/replay.py")},
            "limitations": "Replays saved point-in-time targets, not a new factor fit. Raw open valuation; "
            "cash A-share lots/T+1; immediate full limit fills assumed; board price bands approximate, "
            "not official historical limits; no slippage, stamp duty or transfer fees. "
            "Company actions use a value-preserving pre-close proxy, not actual dividends. "
            "Fees use ChinaStockCommission, minimum once per order across partial fills. "
            "Missing target marks omitted without renormalizing remaining weights."
        } | evaluation.metrics | evaluation.scoring
        pd.DataFrame(orders).to_csv(output / "orders.csv", index=False)
        pd.read_sql_query("SELECT * FROM fills", ledger.db).to_csv(output / "fills.csv", index=False)
        pd.read_sql_query("SELECT * FROM adjustments", ledger.db).to_csv(output / "corporate_action_proxies.csv", index=False)
        frame.to_csv(output / "nav.csv", index=False)
        pd.DataFrame(final["positions"]).to_csv(output / "latest_holdings.csv", index=False)
        pd.DataFrame(batches).to_csv(output / "rebalances.csv", index=False)
        (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
        (output / "data_versions.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
        return metrics
    finally:
        engine.close()
        ledger.close()
        service.close()
