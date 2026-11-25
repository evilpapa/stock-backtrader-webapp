"""All-strategy signal export and shared paper/QMT execution.

Examples:
  python -m examples.strategy_execution list
  python -m examples.strategy_execution generate --strategy ma --input manifest.json \
      --calendar calendar.csv --output targets.csv
  python -m examples.strategy_execution plan --strategy ma --targets targets.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trading.strategies import (
    STRATEGIES, dual_rotation_latest_target, dual_rotation_targets, run_backtrader_signals, strategy_spec,
    timing_targets, trading_calendar, weight_targets,
)
from src.trading.targets import validate_targets, write_targets


def read_calendar(path):
    frame = pd.read_csv(path, dtype=str)
    column = "trade_date" if "trade_date" in frame else "date"
    if column not in frame:
        raise ValueError("calendar needs date or trade_date")
    if "is_open" in frame:
        frame = frame[pd.to_numeric(frame.is_open, errors="raise").eq(1)]
    return trading_calendar(pd.to_datetime(frame[column]))


def read_weights(path):
    """Native long-format close-time weights; empty symbol/zero means cash."""
    frame = pd.read_csv(path, dtype={"symbol": str})
    if {"date", "symbol", "weight"} - set(frame):
        raise ValueError("native weights need date,symbol,weight columns")
    frame["date"] = pd.to_datetime(frame.date).dt.normalize()
    frame["symbol"] = frame.symbol.fillna("")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("duplicate native weight/date")
    weights = {}
    for day, group in frame.groupby("date", sort=True):
        if group.symbol.eq("").any():
            if len(group) != 1 or float(group.weight.iloc[0]) != 0:
                raise ValueError("invalid native cash marker")
            weights[day] = {}
        else:
            weights[day] = dict(zip(group.symbol, pd.to_numeric(group.weight, errors="raise")))
    return weights


def generate(args):
    spec = strategy_spec(args.strategy)
    days = read_calendar(args.calendar)
    if spec.kind == "weights":
        signals = weight_targets(args.strategy, read_weights(args.input), days)
    elif spec.kind == "targets":
        frame = validate_targets(pd.read_csv(args.input, dtype={"symbol": str}))
        if "strategy_id" in frame and set(frame.strategy_id) != {args.strategy}:
            raise ValueError("input strategy_id differs from --strategy")
        # Validate against the supplied actual exchange calendar as well.
        if not pd.to_datetime(frame.trade_date).isin(days).all():
            raise ValueError("execution dates are not in calendar")
        frame["strategy_id"] = args.strategy
        args.output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.output, index=False)
        return frame
    else:
        manifest = json.loads(args.input.read_text(encoding="utf-8"))
        root = args.input.resolve().parent

        def read_frame(name):
            path = root / manifest[name]
            if path.suffix == ".parquet":
                return pd.read_parquet(path)
            return pd.read_csv(path)

        if spec.kind == "backtrader":
            prices = {}
            for name, relative_path in manifest["prices"].items():
                path = root / relative_path
                prices[name] = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
            params = dict(manifest.get("params", {}))
            if args.strategy == "small_cap":
                from src.utils.datahub_universe import StockUniverseSnapshot
                snapshots = {}
                for day, relative_path in manifest["universe_snapshots"].items():
                    stocks = pd.read_csv(root / relative_path, dtype={"code": str})
                    snapshots[pd.Timestamp(day)] = StockUniverseSnapshot(
                        as_of=pd.Timestamp(day), stocks=stocks)
                params["universe_snapshots"] = snapshots
                if "market_factors" in manifest:
                    factors = read_frame("market_factors")
                    params["market_factors"] = factors.set_index(pd.to_datetime(factors.pop("date")))
            signals = run_backtrader_signals(args.strategy, prices, days, params=params,
                initial_cash=args.capital, stake=args.stake, symbol_map=manifest.get("symbol_map"))
        elif spec.kind == "timing":
            from src.strategy.micro_cap_timing_plus import (
                MicroCapTimingParams, build_positions, compute_signals,
            )
            index, factors = read_frame("index"), read_frame("factors")
            gap = read_frame("style_gap")
            for frame in (index, factors, gap):
                frame.index = pd.to_datetime(frame.pop("date"))
            if not index.index.equals(factors.index) or not index.index.equals(gap.index):
                raise ValueError("timing inputs must have identical dates")
            params = MicroCapTimingParams(**manifest.get("params", {}))
            positions = build_positions(compute_signals(index, factors, gap["style_gap"], params), params)
            constituents = read_weights(root / manifest["constituents"])
            signals = timing_targets(positions, constituents, days)
        else:
            from src.strategy.sector_rotation_dual import SectorRotationDualStrategy
            from src.strategy.sector_rotation_dual.data import SectorRotationData

            def panel(name):
                frame = read_frame(name)
                frame.index = pd.to_datetime(frame.pop("date"))
                return frame

            industry_frame = read_frame("industry")
            industry = industry_frame.set_index("symbol")["industry"]
            data = SectorRotationData(open=panel("open"), close=panel("close"), shares=panel("shares"),
                industry=industry, index_heat=panel("index_heat") if "index_heat" in manifest else None)
            strategy = SectorRotationDualStrategy(**manifest.get("params", {}))
            if manifest.get("latest", False):
                signals = [dual_rotation_latest_target(strategy, data, days,
                                                       symbol_map=manifest.get("symbol_map"))]
            else:
                signals = dual_rotation_targets(strategy.run(data), days, symbol_map=manifest.get("symbol_map"))
    return write_targets(signals, args.output)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"backtest", "paper", "plan", "execute", "watch", "status", "cancel"}:
        # Parse strategy identity before any broker is constructed.
        identity = argparse.ArgumentParser(add_help=False)
        identity.add_argument("--strategy", choices=list(STRATEGIES))
        identity.parse_known_args(argv[1:])
        from examples.intraday_execution import main as execution_main
        return execution_main(argv, default_strategy=None, default_targets=None,
                              output_root=Path("examples/trading"))
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出全部已接入策略")
    export = commands.add_parser("generate", help="从原策略数据/权重导出统一交易信号")
    export.add_argument("--strategy", required=True, choices=list(STRATEGIES))
    export.add_argument("--input", required=True, type=Path, help="manifest JSON; FCF uses native date,symbol,weight CSV")
    export.add_argument("--calendar", required=True, type=Path, help="actual open sessions, including next execution date")
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--capital", type=float, default=1_000_000.)
    export.add_argument("--stake", type=int, default=100, help="original MA fixed-size order quantity")
    for command in ("backtest", "paper", "plan", "execute", "watch", "status", "cancel"):
        commands.add_parser(command, help="公共交易命令，使用该命令 --help 查看参数", add_help=False)
    args = parser.parse_args(argv)
    if args.command == "list":
        for spec in STRATEGIES.values():
            print(f"{spec.strategy_id:26} {spec.kind:12} {spec.title}")
        return
    frame = generate(args)
    print(f"{args.strategy}: {frame.trade_date.nunique()} target portfolios -> {args.output}")


if __name__ == "__main__":
    main()
