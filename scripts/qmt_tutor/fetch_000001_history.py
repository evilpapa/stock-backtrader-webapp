"""连接 Big QMT，获取 000001.SZ 的全部历史日线并保存为 CSV。

运行前请先启动 Big QMT Redis RPC 桥接服务，并设置 ``BIGQMT_ACCOUNT_ID``：

    uv run python -m scripts.qmt_tutor.fetch_000001_history

如果 QMT 本地尚未下载历史数据，可以显式增加 ``--download-missing``，脚本会
先请求 QMT 下载，再重新读取行情：

    uv run python -m scripts.qmt_tutor.fetch_000001_history --download-missing

导出为 HDF5：

    uv run python -m scripts.qmt_tutor.fetch_000001_history \
        --output data/000001.SZ_history.h5
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from src.utils.bigqmt_client import BigQmtApiError, normalize_qmt_symbol

from scripts.duckdb.qmt import QmtRpc


DEFAULT_SYMBOL = "000001.SZ"
DEFAULT_START = "19900101"
DEFAULT_OUTPUT = Path("data/000001.SZ_history.csv")
HDF5_SUFFIXES = {".h5", ".hdf5"}


def parse_date(value: str) -> str:
    """校验并返回 QMT 使用的 YYYYMMDD 日期字符串。"""
    try:
        parsed = date.fromisoformat(value) if "-" in value else date.fromisoformat(
            f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期格式应为 YYYYMMDD 或 YYYY-MM-DD: {value}") from exc
    return parsed.strftime("%Y%m%d")


def fetch_history(
    symbol: str = DEFAULT_SYMBOL,
    *,
    start: str = DEFAULT_START,
    end: str | None = None,
    dividend_type: str = "none",
    download_missing: bool = False,
    account_id: str | None = None,
    timeout: float = 30.0,
    qmt: QmtRpc | None = None,
) -> pd.DataFrame:
    """通过 Big QMT 获取指定标的的全部日线历史数据。

    ``count=-1`` 由 ``QmtRpc.daily_bars`` 设置；最终数据范围由 start/end
    控制，QMT 会返回该范围内实际存在的全部交易日。
    """
    qmt_symbol = normalize_qmt_symbol(symbol)
    qmt_client = qmt
    if qmt_client is None:
        configured_account = account_id or os.getenv("BIGQMT_ACCOUNT_ID", "")
        if not configured_account:
            raise BigQmtApiError("请设置 BIGQMT_ACCOUNT_ID，或通过 --account-id 传入资金账号")
        qmt_client = QmtRpc(
            configured_account,
            timeout=timeout,
        )

    result = qmt_client.daily_bars(
        [qmt_symbol],
        start,
        end or date.today().strftime("%Y%m%d"),
        dividend_type=dividend_type,
        download_missing=download_missing,
    )

    frame = result.get(qmt_symbol, pd.DataFrame()).copy()
    if frame.empty:
        raise BigQmtApiError(
            f"Big QMT 未返回 {qmt_symbol} 的历史数据；可确认代码/账号，或重试并增加 --download-missing"
        )
    return frame.sort_values("date").reset_index(drop=True)


def export_history(frame: pd.DataFrame, output: Path, output_format: str = "auto") -> str:
    """将历史数据导出为 CSV 或 HDF5，并返回实际使用的格式。"""
    selected_format = output_format
    if selected_format == "auto":
        selected_format = "hdf5" if output.suffix.lower() in HDF5_SUFFIXES else "csv"
    if selected_format == "csv":
        frame.to_csv(output, index=False)
        return selected_format
    if selected_format == "hdf5":
        try:
            import tables  # noqa: F401  # pandas.to_hdf 的可选引擎
        except ImportError as exc:
            raise BigQmtApiError("HDF5 导出需要 PyTables，请执行 uv sync 安装 tables") from exc
        frame.to_hdf(output, key="history", mode="w", format="table", data_columns=["date"])
        return selected_format
    raise ValueError(f"不支持的导出格式: {output_format}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="连接 Big QMT 获取 000001.SZ 全部历史日线")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="证券代码，默认 000001.SZ；输入 000001 会自动补 .SZ")
    parser.add_argument("--start", type=parse_date, default=DEFAULT_START, help="开始日期，默认 19900101")
    parser.add_argument("--end", type=parse_date, help="结束日期，默认今天")
    parser.add_argument("--dividend-type", choices=["none", "front", "back"], default="none", help="复权方式")
    parser.add_argument("--download-missing", action="store_true", help="本地无历史数据时先请求 QMT 下载")
    parser.add_argument("--account-id", help="覆盖 BIGQMT_ACCOUNT_ID")
    parser.add_argument("--timeout", type=float, default=30.0, help="RPC 超时秒数")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出路径；.h5/.hdf5 自动使用 HDF5")
    parser.add_argument("--output-format", choices=["auto", "csv", "hdf5"], default="auto", help="输出格式，默认按扩展名自动判断")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        frame = fetch_history(
            args.symbol,
            start=args.start,
            end=args.end,
            dividend_type=args.dividend_type,
            download_missing=args.download_missing,
            account_id=args.account_id,
            timeout=args.timeout,
        )
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output_format = export_history(frame, output, args.output_format)
        print(f"已获取 {normalize_qmt_symbol(args.symbol)} 历史数据 {len(frame)} 条")
        print(f"日期范围：{frame['date'].min()} ~ {frame['date'].max()}")
        print(f"导出格式：{output_format}")
        print(f"已保存：{output}")
        return 0
    except Exception as exc:
        print(f"获取历史数据失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
