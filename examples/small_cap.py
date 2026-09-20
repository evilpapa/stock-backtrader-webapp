"""Small Cap 小市值选股策略回测示例。

默认使用少量主板股票验证 QMT → 股票池快照 → 日线 → Backtrader 的完整链路：

    uv run python examples/small_cap.py

完整沪深 A 股股票池会逐只请求合约和历史 ST 信息，耗时较长；仅在确认后执行：

    uv run python examples/small_cap.py --full-universe

本脚本仅查询行情与基础信息、执行本地回测，不会下单。
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.strategy import SmallCapStrategy
from src.utils.qmt_universe import QmtUniverseClient, StockUniverseSnapshot
from src.utils.small_cap_backtest import (
    build_small_cap_snapshots,
    prepare_small_cap_price_data,
    run_small_cap_backtest,
)

DEFAULT_CODES = ["000001.SZ", "600000.SH", "600036.SH", "600016.SH", "000651.SZ"]
DEFAULT_OUTPUT_DIR = Path("examples") / "small_cap"
DEFAULT_START_DATE = "2026-05-06"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析 Small Cap 回测范围、QMT 连接和策略参数。"""
    parser = argparse.ArgumentParser(description="运行 Small Cap 小市值策略回测")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="回测开始日期 YYYY-MM-DD")
    parser.add_argument(
        "--end-date",
        default=(datetime.now().astimezone().date() - timedelta(days=1)).isoformat(),
        help="回测结束日期 YYYY-MM-DD",
    )
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--codes", nargs="+", default=DEFAULT_CODES, help="受限股票池代码；默认用于冒烟回测")
    parser.add_argument("--full-universe", action="store_true", help="使用沪深 A 股完整股票池，耗时较长")
    parser.add_argument("--sector", default="沪深A股", help="全市场模式使用的 QMT 板块名称")
    parser.add_argument("--stock-num", type=int, default=3, help="最终持仓股票数量")
    parser.add_argument("--pool-num", type=int, default=100, help="候选股票池数量上限")
    parser.add_argument("--rebalance-days", type=int, default=10, help="调仓间隔（交易日）")
    parser.add_argument("--min-cap", type=float, default=5.0, help="流通市值下限（亿元）")
    parser.add_argument("--max-cap", type=float, default=5_000.0, help="流通市值上限（亿元）")
    parser.add_argument("--market-factors", type=Path, help="可选市场因子 CSV，需含 date、nhnl、limit_up_count 列")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="结果输出目录")
    parser.add_argument("--bigqmt-account-id", default=os.getenv("BIGQMT_ACCOUNT_ID", ""), help="Big QMT 资金账号")
    parser.add_argument(
        "--bigqmt-timeout",
        type=float,
        default=float(os.getenv("BIGQMT_RPC_TIMEOUT_SECONDS", "30")),
        help="Big QMT RPC 超时秒数",
    )
    return parser.parse_args(argv)


def load_market_factors(path: Path | None) -> pd.DataFrame | None:
    """读取可选的市场风控因子 CSV；未提供时关闭 Small Cap 市场门控。"""
    if path is None:
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "nhnl", "limit_up_count"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"市场因子文件缺少列: {', '.join(sorted(missing))}")
    return frame.set_index("date")[["nhnl", "limit_up_count"]]


def main(argv: Sequence[str] | None = None) -> SmallCapStrategy:
    """构建 QMT 股票池快照、下载日线，并执行 Small Cap 本地回测。"""
    args = parse_args(argv)
    if not args.bigqmt_account_id:
        raise ValueError("请传入 --bigqmt-account-id 或设置 BIGQMT_ACCOUNT_ID")
    if args.full_universe and args.codes != DEFAULT_CODES:
        raise ValueError("--full-universe 与自定义 --codes 不能同时使用")

    snapshot_codes = None if args.full_universe else args.codes
    client = QmtUniverseClient(args.bigqmt_account_id, timeout=args.bigqmt_timeout)
    snapshots = build_small_cap_snapshots(
        client,
        [args.start_date],
        sector_name=args.sector,
        codes=snapshot_codes,
    )
    snapshot = next(iter(snapshots.values()))
    eligible = snapshot.eligible_codes(375, args.min_cap, args.max_cap)
    if not eligible:
        raise RuntimeError("当前快照没有满足 Small Cap 基础条件的股票")
    # 全市场快照只用于基础筛选；后续仅下载合格候选池和风控指数日线，
    # 避免对数千只不符合市值/状态条件的股票发起无用行情请求。
    snapshot = StockUniverseSnapshot(
        snapshot.as_of,
        snapshot.stocks[snapshot.stocks["code"].isin(eligible)].reset_index(drop=True),
    )
    snapshots = {snapshot.as_of: snapshot}

    price_data = prepare_small_cap_price_data(client, snapshots, args.start_date, args.end_date)
    market_factors = load_market_factors(args.market_factors)
    strategy = run_small_cap_backtest(
        price_data,
        snapshots,
        args.initial_cash,
        strategy_params={
            "stock_num": min(args.stock_num, len(eligible)),
            "pool_num": args.pool_num,
            "min_cap": args.min_cap,
            "max_cap": args.max_cap,
            "rebalance_days": args.rebalance_days,
            "market_guard": market_factors is not None,
            "avoid_months": (),
        },
        market_factors=market_factors,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot.stocks.to_csv(args.output_dir / "universe_snapshot.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(strategy.rebalance_history).to_json(
        args.output_dir / "rebalance_history.json",
        orient="records",
        force_ascii=False,
        indent=2,
    )
    print(f"股票池快照: {len(snapshot.stocks)} 只，合格标的: {len(eligible)} 只")
    print(f"调仓次数: {len(strategy.rebalance_history)}")
    if strategy.rebalance_history:
        print(f"最后一次调仓: {strategy.rebalance_history[-1]}")
    print(f"期末资产: {strategy.broker.getvalue():,.2f}")
    print(f"结果已保存到: {args.output_dir}")
    return strategy


if __name__ == "__main__":
    main()
