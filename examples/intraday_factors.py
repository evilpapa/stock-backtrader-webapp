"""通过 DataHub 获取单个股票单日分钟数据并计算报告核心因子。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.strategy.intraday_factors import daily_factors


def minute_end_bars(bars: pd.DataFrame, source: str, bar_time: str | None) -> pd.DataFrame:
    """按显式指定的 XtQuant 时间语义转换为分钟末时间。"""
    if source == 'xtquant' and bar_time is None:
        raise ValueError('XtQuant 时间语义尚未实测确认，请指定 --bar-time start 或 end')
    result = bars.copy()
    if source == 'xtquant' and bar_time == 'start':
        result['datetime'] = result['datetime'] + pd.Timedelta(minutes=1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', required=True, help='例如 600000.SH')
    parser.add_argument('--date', required=True, help='交易日 YYYY-MM-DD')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--data-source', choices=('tushare', 'xtquant'), default='tushare')
    parser.add_argument('--bar-time', choices=('start', 'end'), help='XtQuant 分钟 K 线时间是开始还是结束；必须先核验')
    parser.add_argument('--no-download', action='store_true', help='XtQuant 仅读取本地缓存，不下载')
    args = parser.parse_args()
    if args.data_source == 'xtquant' and args.bar_time is None:
        parser.error('使用 xtquant 时必须通过 --bar-time 指定已核验的分钟时间语义')
    service = create_service()
    # 显式来源只允许该 Provider，避免发生静默切换。
    service.router.providers.pop('xtquant' if args.data_source == 'tushare' else 'tushare', None)
    try:
        day = pd.Timestamp(args.date)
        end = (day + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).strftime('%Y%m%d%H%M%S')
        bars = service.get_minute(DataRequest(symbols=(args.symbol,), start=args.date,
                                               end=end, frequency='1m', adjust='none',
                                               options={'download': not args.no_download, 'fill_data': False}))
        factors = daily_factors(minute_end_bars(bars, args.data_source, args.bar_time))
        if factors.empty:
            raise ValueError(f'数据不足一个完整交易日，返回 {len(bars)} 行；未生成因子')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        factors.to_csv(args.output, index=False)
        metadata = {key: bars.attrs.get(key) for key in ('source', 'data_kind', 'data_version', 'timestamp_semantics')}
        metadata.update({'symbol': args.symbol, 'date': args.date, 'frequency': '1m', 'adjust': 'none', 'rows': len(bars),
                         'input_bar_time': args.bar_time if args.data_source == 'xtquant' else 'end',
                         'factor_bar_time': 'end', 'fill_data': False})
        args.output.with_suffix(args.output.suffix + '.metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'已保存 {len(factors)} 行因子至 {args.output}')
    finally:
        service.close()


if __name__ == '__main__':
    main()
