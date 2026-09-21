"""Synchronise QMT market data into selectable DuckDB and KDB-X targets.

Examples::

    python -m scripts.duckdb.sync check
    python -m scripts.duckdb.sync list-sectors
    python -m scripts.duckdb.sync sync --targets duckdb --period 1d
    python -m scripts.duckdb.sync sync --targets kdb --period 1m
"""

from __future__ import annotations

import argparse
import json
import socket
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.logs import logger  # noqa: E402

from .config import SyncConfig, load_sector_map  # noqa: E402
from .fetcher import fetch_batches  # noqa: E402
from src.utils.bigqmt_client import QmtDataClient  # noqa: E402
from .store import DuckDBStore  # noqa: E402
from .universe import UniverseDiscovery  # noqa: E402
from ..kdb.store import KdbStore  # noqa: E402
from ..targets import MarketDataTarget, parse_targets  # noqa: E402


def parse_date(value: str) -> date:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return date.fromisoformat(value) if fmt == "%Y-%m-%d" else date.fromisoformat(
                f"{value[:4]}-{value[4:6]}-{value[6:8]}"
            )
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"日期格式应为 YYYYMMDD 或 YYYY-MM-DD: {value}")


def probe_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def command_check(config: SyncConfig) -> int:
    payload = {
        "duckdb_cli": shutil.which("duckdb") or "未找到",
        "duckdb_version": None,
        "duckdb_path": str(config.duckdb_path),
        "duckdb_path_exists": config.duckdb_path.exists(),
        "kdb_x_port": f"{config.kdb_host}:{config.kdb_port}",
        "kdb_x_port_reachable": probe_port(config.kdb_host, config.kdb_port),
    }
    if payload["duckdb_cli"] != "未找到":
        import subprocess

        result = subprocess.run([payload["duckdb_cli"], "--version"], capture_output=True, text=True, check=False)
        payload["duckdb_version"] = result.stdout.strip() or result.stderr.strip()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_qmt(config: SyncConfig) -> QmtDataClient:
    return QmtDataClient(
        timeout=config.timeout,
    )


def command_list_sectors(config: SyncConfig) -> int:
    qmt = build_qmt(config)
    print("\n".join(qmt.sector_list(allow_fallback=True)))
    return 0


def command_sync(args: argparse.Namespace, config: SyncConfig) -> int:
    target_names = parse_targets(args.targets)
    period = args.period
    if period != "1d" and "duckdb" in target_names:
        raise ValueError("DuckDB 目标只支持 1d；分钟/tick 数据请使用 --targets kdb 或仅保留 kdb")
    asset_types = {item.strip() for item in args.asset_types.split(",") if item.strip()} if args.asset_types else None
    sector_map = load_sector_map(args.sector_config)
    qmt = build_qmt(config)
    discovery = UniverseDiscovery(config.timeout, qmt_client=qmt)
    instruments, universe_failures = discovery.discover(
        sector_map,
        asset_types=asset_types,
        limit=args.limit,
    )
    if universe_failures and not args.allow_partial:
        for failure in universe_failures:
            logger.warning(
                "标的发现失败 asset_type={} sector={} error={}",
                failure.get("asset_type", ""),
                failure.get("sector", ""),
                failure.get("error", ""),
            )
        raise RuntimeError(
            "QMT 标的池发现不完整，请修正 universe.yaml 或使用 --allow-partial：\n"
            + json.dumps(universe_failures, ensure_ascii=False)
        )
    for failure in universe_failures:
        logger.warning(
            "标的发现失败 asset_type={} sector={} error={}",
            failure.get("asset_type", ""),
            failure.get("sector", ""),
            failure.get("error", ""),
        )
    if instruments.empty:
        raise RuntimeError("没有发现任何可同步标的")

    targets: list[MarketDataTarget] = []
    duckdb_store: DuckDBStore | None = None
    try:
        if "duckdb" in target_names:
            duckdb_store = DuckDBStore(config.duckdb_path)
            targets.append(duckdb_store)
        if "kdb" in target_names:
            targets.append(KdbStore(
                config.kdb_host,
                config.kdb_port,
                username=config.kdb_username,
                password=config.kdb_password,
                timeout=config.timeout,
            ))
    except Exception:
        for target in targets:
            target.close()
        raise

    run_id = ""
    errors: list[dict[str, str]] = [
        {"symbol": "", "error_type": "universe", "error": json.dumps(item, ensure_ascii=False)}
        for item in universe_failures
    ]
    bars_by_target = {target.name: 0 for target in targets}
    try:
        for target in targets:
            try:
                target.initialize()
                target.upsert_instruments(instruments)
                logger.info(
                    "标的元数据导入成功 target={} count={}",
                    target.name,
                    len(instruments),
                )
            except Exception as exc:
                for symbol in instruments["symbol"].tolist():
                    logger.warning(
                        "标的元数据导入失败 target={} symbol={} error={}",
                        target.name,
                        symbol,
                        exc,
                    )
                raise
        end_date = args.end or date.today()
        start_date = args.start or parse_date(config.qmt_start_date)
        if args.incremental:
            latest_values = []
            for target in targets:
                latest = target.latest_bar_time(period)
                if latest is not None:
                    latest_values.append(pd.Timestamp(latest).date())
            if latest_values:
                start_date = max(start_date, max(latest_values) - timedelta(days=config.overlap_days))
        if duckdb_store is not None:
            run_id = duckdb_store.start_run(start_date, end_date, args.dividend_type or config.dividend_type)
            duckdb_store.record_errors(run_id, errors)
        if not args.dry_run:
            for batch_result in fetch_batches(
                qmt,
                instruments,
                start_date,
                end_date,
                batch_size=max(1, args.batch_size or config.batch_size),
                period=period,
                dividend_type=args.dividend_type or config.dividend_type,
                download_missing=args.download_missing,
            ):
                for item in batch_result.errors:
                    logger.warning(
                        "行情同步失败 symbol={} type={} error={}",
                        item.get("symbol", ""),
                        item.get("error_type", "unknown"),
                        item.get("error", ""),
                    )
                errors.extend(batch_result.errors)
                if duckdb_store is not None:
                    duckdb_store.record_errors(run_id, batch_result.errors)

                symbol_counts = (
                    batch_result.bars.groupby("symbol", sort=False).size().to_dict()
                    if not batch_result.bars.empty
                    else {}
                )
                for target in targets:
                    if not symbol_counts:
                        continue
                    try:
                        written = target.write_bars(batch_result.bars, period=period)
                    except Exception as exc:
                        write_errors = []
                        for symbol, count in symbol_counts.items():
                            logger.warning(
                                "行情导入失败 target={} symbol={} period={} bars={} error={}",
                                target.name,
                                symbol,
                                period,
                                count,
                                exc,
                            )
                            write_errors.append({
                                "symbol": symbol,
                                "error_type": "target_write",
                                "error": f"{target.name}: {exc}",
                            })
                        errors.extend(write_errors)
                        if duckdb_store is not None and target.name != duckdb_store.name:
                            duckdb_store.record_errors(run_id, write_errors)
                        continue

                    expected = sum(symbol_counts.values())
                    bars_by_target[target.name] += written
                    if written != expected:
                        logger.warning(
                            "行情导入数量异常 target={} period={} expected={} written={}",
                            target.name,
                            period,
                            expected,
                            written,
                        )
                        continue
                    for symbol, count in symbol_counts.items():
                        logger.info(
                            "行情导入成功 target={} symbol={} period={} bars={}",
                            target.name,
                            symbol,
                            period,
                            count,
                        )
        status = "success" if not errors else "partial"
        if duckdb_store is not None:
            duckdb_store.finish_run(
                run_id,
                status=status,
                instrument_count=len(instruments),
                bar_count=bars_by_target["duckdb"],
                error_count=len(errors),
                message="存在未返回数据或板块失败" if errors else "",
            )
    except Exception as exc:
        if run_id and duckdb_store is not None:
            duckdb_store.finish_run(
                run_id,
                status="failed",
                instrument_count=len(instruments),
                bar_count=bars_by_target["duckdb"],
                error_count=len(errors) + 1,
                message=str(exc),
            )
        raise
    finally:
        for target in targets:
            target.close()

    print(json.dumps({
        "ok": not errors,
        "targets": target_names,
        "period": period,
        "run_id": run_id or None,
        "instrument_count": len(instruments),
        "bars_by_target": bars_by_target,
        "error_count": len(errors),
        "database": str(config.duckdb_path),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }, ensure_ascii=False, indent=2))
    return 2 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 Big QMT 行情同步到可选的 DuckDB/KDB-X 目标")
    parser.add_argument("--duckdb-path", help="DuckDB 文件路径，默认读取 DUCKDB_PATH 或 data/market.duckdb")
    parser.add_argument("--account-id", help="覆盖 BIGQMT_ACCOUNT_ID")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="检查 DuckDB 文件、CLI 和 KDB-X 预留端口")
    subparsers.add_parser("list-sectors", help="读取 QMT 可用板块名")

    sync = subparsers.add_parser("sync", help="同步行情数据")
    sync.add_argument("--targets", default="duckdb", help="同步目标，逗号分隔：duckdb、kdb；默认 duckdb")
    sync.add_argument("--period", choices=["1d", "1m", "5m", "15m", "30m", "60m", "tick"], default="1d", help="QMT 数据周期")
    sync.add_argument("--start", type=parse_date, help="开始日期，默认 20000101")
    sync.add_argument("--end", type=parse_date, help="结束日期，默认今天")
    sync.add_argument("--incremental", action="store_true", help="从数据库最新日期附近增量同步")
    sync.add_argument("--asset-types", help="逗号分隔：stock,index,fund,bond,repo,warrant,etf")
    sync.add_argument("--sector-config", default=str(Path(__file__).with_name("universe.yaml")))
    sync.add_argument("--batch-size", type=int, help="QMT 每批代码数量")
    sync.add_argument("--limit", type=int, help="仅同步前 N 个标的，用于冒烟测试")
    sync.add_argument("--dividend-type", choices=["none", "front", "back"], help="复权方式，默认 none 不复权")
    sync.add_argument("--download-missing", action="store_true", help="空数据时先调用 QMT 历史下载接口")
    sync.add_argument("--allow-partial", action="store_true", help="允许部分板块或标的失败")
    sync.add_argument("--dry-run", action="store_true", help="只发现标的并写入 instrument_master，不拉行情")
    return parser


def report_error(exc: Exception) -> None:
    message = str(exc)
    print(f"同步命令失败: {message}", file=sys.stderr)
    if "BIGQMT_ACCOUNT_ID" in message:
        print("请设置 BIGQMT_ACCOUNT_ID，或使用 --account-id 传入资金账号。", file=sys.stderr)
    if "127.0.0.1:6379" in message or "Redis" in message:
        print("请确认 Big QMT Redis 桥接服务已启动，并检查 BIGQMT_REDIS_HOST/PORT/DB/PASSWORD。", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = SyncConfig.from_env(duckdb_path=args.duckdb_path)
    if args.account_id:
        config = SyncConfig(**{**config.__dict__, "account_id": args.account_id})
    try:
        if args.command == "check":
            return command_check(config)
        if args.command == "list-sectors":
            return command_list_sectors(config)
        return command_sync(args, config)
    except Exception as exc:
        report_error(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
