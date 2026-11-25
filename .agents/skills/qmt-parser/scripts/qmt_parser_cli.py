#!/usr/bin/env python3
"""qmt-parser 统一 CLI。

通过命令行直接读取 QMT 本地数据文件，默认输出 JSON，便于大模型解析；
加 ``--table`` 输出人类可读表格。

用法示例：

    python qmt_parser_cli.py tick /path/to/000001-20250529-tick.dat --head 3
    python qmt_parser_cli.py min /path/to/000001-1m.dat --head 3
    python qmt_parser_cli.py day /path/to/000001-1d.dat --start 20230101 --end 20231231 --head 3
    python qmt_parser_cli.py finance /path/to/002419_7001.DAT --head 3
    python qmt_parser_cli.py finance /path/to/002419_7006.DAT --head 1
    python qmt_parser_cli.py dividend-value <hex>
    python qmt_parser_cli.py schema 7001
    python qmt_parser_cli.py datadir /mnt/gjzq_qmt/datadir --tick 000001.SZ 20250529
"""

import argparse
import json
import os
import sys

# 包查找顺序：已安装 -> QMTPARSER_PYTHON 环境变量 -> 项目仓库内 python/ 目录
_candidates = [
    os.environ.get("QMTPARSER_PYTHON"),
    "/data1/qmt-parser/python",
]
for _cand in _candidates:
    if _cand and os.path.isdir(os.path.join(_cand, "qmt_parser")):
        sys.path.insert(0, os.path.abspath(_cand))
        break

import qmt_parser as qp  # noqa: E402


def _dump(obj, table: bool):
    if table:
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            keys = obj[0].keys()
            print("\t".join(keys))
            for row in obj:
                print("\t".join(str(row.get(k, "")) for k in keys))
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                print(f"{k}\t{v}")
            return
    print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))


def _head(items, n):
    if n is None:
        return items
    return items[:n]


def cmd_tick(args):
    ticks = qp.parse_ticks_to_structs(args.path)
    rows = [
        {
            "symbol": t.symbol,
            "date": t.date,
            "market": t.market,
            "raw_qmt_timestamp": t.raw_qmt_timestamp,
            "market_phase_status": t.market_phase_status,
            "last_price": t.last_price,
            "last_close": t.last_close,
            "amount": t.amount,
            "volume": t.volume,
            "ask_prices": t.ask_prices,
            "ask_vols": t.ask_vols,
            "bid_prices": t.bid_prices,
            "bid_vols": t.bid_vols,
        }
        for t in _head(ticks, args.head)
    ]
    return {"ok": True, "total": len(ticks), "rows": rows}


def cmd_min(args):
    rows = list(qp.parse_min_to_structs(args.path))
    out = [
        {
            "timestamp_ms": r.timestamp_ms,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "amount": r.amount,
            "open_interest": r.open_interest,
            "pre_close": r.pre_close,
        }
        for r in _head(rows, args.head)
    ]
    return {"ok": True, "total": len(rows), "rows": out}


def cmd_day(args):
    if args.start and args.end:
        rows = qp.parse_daily_to_structs(args.path, args.start, args.end)
    else:
        rows = qp.parse_daily_file_to_structs(args.path)
    out = [
        {
            "timestamp_ms": r.timestamp_ms,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "amount": r.amount,
            "open_interest": r.open_interest,
            "file_pre_close": r.file_pre_close,
        }
        for r in _head(rows, args.head)
    ]
    return {"ok": True, "total": len(rows), "rows": out}


def _finance_record_to_dict(rec):
    out = {
        "file_type": rec.file_type.name,
        "type_id": rec.file_type.value,
        "report_date": rec.report_date.isoformat(),
        "announce_date": rec.announce_date.isoformat(),
    }
    data = rec.data
    if isinstance(data, qp.ReportData):
        out["columns"] = data.columns
    elif isinstance(data, qp.RatiosData):
        out["ratios"] = data.ratios
    elif isinstance(data, qp.CapitalData):
        out["capital"] = {
            "total_share": data.total_share,
            "flow_share": data.flow_share,
            "restricted": data.restricted,
            "free_float_share": data.free_float_share,
        }
    elif isinstance(data, qp.HolderCountData):
        out["holders"] = {
            "total": data.total_holders,
            "a": data.a_holders,
            "b": data.b_holders,
            "h": data.h_holders,
            "float": data.float_holders,
            "other": data.other_holders,
        }
    elif isinstance(data, qp.TopHolderData):
        out["holders"] = [
            {
                "name": h.name,
                "holder_type": h.holder_type,
                "hold_amount": h.hold_amount,
                "change_reason": h.change_reason,
                "hold_ratio": h.hold_ratio,
                "share_type": h.share_type,
                "rank": h.rank,
            }
            for h in data.holders
        ]
    return out


def cmd_finance(args):
    records = qp.FinanceReader.read_file(args.path)
    if args.named:
        # 只输出报表类/比率类的 列名->数值
        rows = []
        for rec in _head(records, args.head):
            nv = rec.named_values()
            rows.append(
                {
                    "report_date": rec.report_date.isoformat(),
                    "values": {k: v for k, v in nv} if nv else None,
                }
            )
        return {"ok": True, "total": len(records), "rows": rows}
    return {
        "ok": True,
        "total": len(records),
        "rows": [_finance_record_to_dict(r) for r in _head(records, args.head)],
    }


def cmd_dividend_value(args):
    record = qp.parse_dividend_value(bytes.fromhex(args.hex))
    return {
        "ok": True,
        "record": {
            "ex_dividend_date": record.ex_dividend_date.isoformat(),
            "record_date": record.record_date.isoformat() if record.record_date else None,
            "interest": record.interest,
            "stock_bonus": record.stock_bonus,
            "stock_gift": record.stock_gift,
            "allot_num": record.allot_num,
            "allot_price": record.allot_price,
            "gugai": record.gugai,
            "unknown64_raw": record.unknown64_raw,
            "adjust_factor": record.adjust_factor,
            "timestamp_raw": record.timestamp_raw,
        },
    }


def cmd_schema(args):
    file_type = qp.FileType.from_id(int(args.type_id))
    names = qp.FinanceReader.column_names(file_type)
    return {"ok": True, "type_id": args.type_id, "columns": names}


def cmd_datadir(args):
    qmt = qp.QmtDataDir(args.root)
    result = {"ok": True, "root": qmt.root}

    if args.code:
        market, symbol = qp.parse_security_code(args.code)
        result["market"] = market.value
        result["symbol"] = symbol

        if args.tick:
            ticks = qmt.parse_ticks_to_structs(market, symbol, args.tick)
            result["tick_total"] = len(ticks)
            result["tick"] = [
                {
                    "date": t.date,
                    "last_price": t.last_price,
                    "volume": t.volume,
                    "ask_prices": t.ask_prices,
                    "bid_prices": t.bid_prices,
                }
                for t in _head(ticks, args.head)
            ]
        if args.min:
            mins = qmt.parse_min_to_structs(market, symbol)
            result["min_total"] = len(mins)
            result["min"] = [
                {"timestamp_ms": r.timestamp_ms, "close": r.close, "volume": r.volume}
                for r in _head(mins, args.head)
            ]
        if args.day:
            days = qmt.parse_daily_file_to_structs(market, symbol)
            result["day_total"] = len(days)
            result["day"] = [
                {"timestamp_ms": r.timestamp_ms, "close": r.close, "volume": r.volume}
                for r in _head(days, args.head)
            ]

    if args.holidays:
        try:
            result["holidays"] = qmt.load_holidays()
        except qp.MetadataParseError as exc:
            result["holidays_error"] = str(exc)

    return result


def main():
    parser = argparse.ArgumentParser(description="qmt-parser CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tick", help="解析 tick 分笔文件")
    p.add_argument("path")
    p.add_argument("--head", type=int)
    p.set_defaults(func=cmd_tick)

    p = sub.add_parser("min", help="解析 1 分钟 K 线文件")
    p.add_argument("path")
    p.add_argument("--head", type=int)
    p.set_defaults(func=cmd_min)

    p = sub.add_parser("day", help="解析日线文件")
    p.add_argument("path")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--head", type=int)
    p.set_defaults(func=cmd_day)

    p = sub.add_parser("finance", help="解析财务 .DAT 文件")
    p.add_argument("path")
    p.add_argument("--head", type=int)
    p.add_argument("--named", action="store_true", help="输出 列名->数值")
    p.set_defaults(func=cmd_finance)

    p = sub.add_parser("dividend-value", help="解码单条分红 LevelDB value (hex)")
    p.add_argument("hex")
    p.set_defaults(func=cmd_dividend_value)

    p = sub.add_parser("schema", help="输出财务文件类型的列名")
    p.add_argument("type_id")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("datadir", help="从 datadir 根目录自动发现并解析")
    p.add_argument("root")
    p.add_argument("--code", help="证券代码，如 000001.SZ")
    p.add_argument("--tick", help="tick 日期 YYYYMMDD")
    p.add_argument("--min", action="store_true", help="解析 1 分钟线")
    p.add_argument("--day", action="store_true", help="解析日线")
    p.add_argument("--holidays", action="store_true", help="加载节假日")
    p.add_argument("--head", type=int)
    p.set_defaults(func=cmd_datadir)

    parser.add_argument("--table", action="store_true", help="表格输出")
    args = parser.parse_args()

    try:
        result = args.func(args)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": type(exc).__name__, "detail": str(exc)}
        print(json.dumps(result, ensure_ascii=False, default=str))
        sys.exit(1)

    _dump(result, args.table)


if __name__ == "__main__":
    main()
