"""使用 Big QMT ``get_local_data`` 读取 000001.SZ 的本地缓存行情。

该接口只读取 QMT 本地保存的数据，不会触发历史数据下载。运行前请启动
Big QMT Redis RPC 桥接服务，并设置 ``BIGQMT_ACCOUNT_ID``：

    uv run python -m scripts.qmt_tutor.get_000001_local_data

如需将原始 RPC 返回保存为 JSON：

    uv run python -m scripts.qmt_tutor.get_000001_local_data \
        --output data/000001.SZ_local_data.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from src.utils.bigqmt_client import BigQmtApiError, get_xtdata, normalize_qmt_symbol

from scripts.qmt_tutor.fetch_000001_history import parse_date


DEFAULT_SYMBOL = "000001.SZ"
DEFAULT_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
DEFAULT_START = "19900101"


def get_local_data(
    symbol: str = DEFAULT_SYMBOL,
    *,
    fields: list[str] | None = None,
    period: str = "1d",
    start: str = DEFAULT_START,
    end: str | None = None,
    count: int = -1,
    dividend_type: str = "none",
    fill_data: bool = False,
    data_dir: str | None = None,
    account_id: str | None = None,
    timeout: float = 30.0,
    xtdata_client: Any | None = None,
) -> dict[str, Any]:
    """通过 ``xtquant_compat.xtdata.get_local_data`` 返回本地缓存行情。"""
    qmt_symbol = normalize_qmt_symbol(symbol)
    configured_account = account_id or os.getenv("BIGQMT_ACCOUNT_ID", "")
    if not configured_account:
        raise BigQmtApiError("请设置 BIGQMT_ACCOUNT_ID，或通过 --account-id 传入资金账号")

    params: dict[str, Any] = {
        "field_list": fields or DEFAULT_FIELDS,
        "stock_list": [qmt_symbol],
        "period": period,
        "start_time": start,
        "end_time": end or date.today().strftime("%Y%m%d"),
        "count": count,
        "dividend_type": dividend_type,
        "fill_data": fill_data,
    }
    if data_dir:
        params["data_dir"] = data_dir

    xtdata = xtdata_client or get_xtdata(account_id=configured_account, timeout=timeout)
    try:
        data = xtdata.get_local_data(**params)
    except Exception as exc:
        raise BigQmtApiError(f"Big QMT get_local_data 请求失败: {exc}") from exc
    if data is None or (isinstance(data, (dict, list, tuple, set)) and not data):
        raise BigQmtApiError(f"本地缓存没有返回 {qmt_symbol} 的数据")
    return {"stock_code": qmt_symbol, "params": params, "data": data}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 Big QMT get_local_data 读取 000001.SZ 本地行情")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="证券代码，默认 000001.SZ；输入 000001 会自动补 .SZ")
    parser.add_argument("--fields", default=",".join(DEFAULT_FIELDS), help="字段列表，逗号分隔")
    parser.add_argument("--period", default="1d", help="周期，如 1d、1m、5m、tick")
    parser.add_argument("--start", type=parse_date, default=DEFAULT_START, help="开始日期，默认 19900101")
    parser.add_argument("--end", type=parse_date, help="结束日期，默认今天")
    parser.add_argument("--count", type=int, default=-1, help="返回数量，-1 表示全部")
    parser.add_argument("--dividend-type", choices=["none", "front", "back"], default="none", help="复权方式")
    parser.add_argument("--fill-data", action="store_true", help="填充缺失行情")
    parser.add_argument("--data-dir", help="QMT userdata_mini 目录；默认使用 QMT 配置")
    parser.add_argument("--account-id", help="覆盖 BIGQMT_ACCOUNT_ID")
    parser.add_argument("--timeout", type=float, default=30.0, help="RPC 超时秒数")
    parser.add_argument("--output", type=Path, help="可选 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = get_local_data(
            args.symbol,
            fields=[field.strip() for field in args.fields.split(",") if field.strip()],
            period=args.period,
            start=args.start,
            end=args.end,
            count=args.count,
            dividend_type=args.dividend_type,
            fill_data=args.fill_data,
            data_dir=args.data_dir,
            account_id=args.account_id,
            timeout=args.timeout,
        )
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
            print(f"已保存：{args.output}")
        else:
            print(text)
        return 0
    except Exception as exc:
        print(f"读取本地行情失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
