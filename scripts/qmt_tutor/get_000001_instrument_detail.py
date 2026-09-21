"""使用原生 ``xtquant.xtdata.get_instrument_detail`` 查询 000001 股票概况。

运行前请先启动本机 MiniQmt：

    uv run python -m scripts.qmt_tutor.get_000001_instrument_detail

默认使用 ``is_detail=True`` 获取完整合约信息；如需查看基础字段，可增加
``--brief``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.utils.bigqmt_client import QmtDataClient, QmtDataError, normalize_qmt_symbol


DEFAULT_SYMBOL = "000001.SZ"


def fetch_instrument_detail(
    symbol: str = DEFAULT_SYMBOL,
    *,
    is_detail: bool = True,
    timeout: float = 30.0,
    xtdata_client: Any | None = None,
) -> dict[str, Any]:
    """通过兼容 ``xtdata.get_instrument_detail`` 获取合约概况。"""
    qmt_symbol = normalize_qmt_symbol(symbol)
    try:
        detail = QmtDataClient(timeout=timeout, xtdata_client=xtdata_client).instrument_detail(
            qmt_symbol,
            is_detail=is_detail,
        )
    except Exception as exc:
        raise QmtDataError(f"QMT get_instrument_detail 请求失败: {exc}") from exc
    if not isinstance(detail, dict):
        raise QmtDataError(f"未找到合约概况: {qmt_symbol}")
    return detail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="使用 Big QMT get_instrument_detail 获取 000001.SZ 股票概况")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="证券代码，默认 000001.SZ；输入 000001 会自动补 .SZ")
    parser.add_argument("--brief", action="store_true", help="只请求基础合约字段，即 is_detail=False")
    parser.add_argument("--account-id", help="覆盖 BIGQMT_ACCOUNT_ID")
    parser.add_argument("--timeout", type=float, default=30.0, help="RPC 超时秒数")
    parser.add_argument("--output", type=Path, help="可选 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    symbol = normalize_qmt_symbol(args.symbol)
    try:
        detail = fetch_instrument_detail(
            symbol,
            is_detail=not args.brief,
        )
        payload = {
            "stock_code": symbol,
            "is_detail": not args.brief,
            "detail": detail,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
            print(f"已保存：{args.output}")
        else:
            print(text)
        return 0
    except Exception as exc:
        print(f"获取股票概况失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
