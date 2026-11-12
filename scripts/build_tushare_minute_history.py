"""限速准备 Tushare 1 分钟历史行情；按历史股票池和交易日分块，可断点续跑。"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.datahub import DataRequest, create_service
from src.datahub.minute_batch_repository import MinuteBatchRepository
from src.datahub.models import DataKind
from src.datahub.router import RoutePolicy


def make_plan(start, end, chunk_days=32):
    """以快照滞后 31 天近似股票池；向后看五个交易日只扩大取数集合以便预热。"""
    if not 1 <= chunk_days <= 32:
        raise ValueError('每段最多 32 个交易日，避免 8000 行上限')
    root = Path('data/micro_cap_timing_plus/raw/daily')
    dates = sorted(pd.Timestamp(p.stem) for p in root.glob('*.parquet')
                   if len(p.stem) == 8 and p.stem.isdigit() and pd.Timestamp(start) <= pd.Timestamp(p.stem) <= pd.Timestamp(end))
    if not dates:
        raise ValueError('所选范围无日线文件，无法推断交易日')
    snapshots = pd.read_parquet('data/intraday_factors/csi500/snapshots.parquet').copy()
    snapshots['available'] = pd.to_datetime(snapshots.trade_date.astype(str), format='%Y%m%d') + pd.Timedelta(days=31)
    available = sorted(snapshots.available.unique())
    if not available:
        raise ValueError('没有历史成分快照')
    tasks = []
    for offset in range(0, len(dates), chunk_days):
        segment = dates[offset:offset+chunk_days]
        # Including nearby future members is solely a data acquisition choice;
        # it must not be used as a signal-date universe.
        latest = dates[min(len(dates)-1, offset+len(segment)-1+5)]
        earlier = [pd.Timestamp(x) for x in available if pd.Timestamp(x) <= segment[0]]
        first = max(earlier) if earlier else pd.Timestamp(available[0])
        used = [pd.Timestamp(x) for x in available if first <= pd.Timestamp(x) <= latest]
        symbols = sorted(snapshots.loc[snapshots.available.isin(used), 'con_code'].dropna().unique())
        if not symbols: raise ValueError(f'无法确定 {segment[0]} 股票集合')
        for symbol in symbols:
            tasks.append((segment[0].strftime('%Y%m%d'), segment[-1].strftime('%Y%m%d'), symbol))
    return dates, tasks


def pause_until(deadline):
    while (remaining := deadline - time.time()) > 0:
        time.sleep(min(remaining, 20))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2021-01-01')
    p.add_argument('--end', default='2025-12-31')
    p.add_argument('--output-dir', type=Path, default=Path('data/intraday_factors/tushare_minute_history'))
    p.add_argument('--interval', type=float, default=3665, help='请求间隔，默认按实测每小时 1 次留余量；不得低于 65 秒')
    p.add_argument('--chunk-days', type=int, default=32)
    p.add_argument('--max-requests', type=int, default=0, help='本次成功或空响应的最大请求数，0 表示不限')
    p.add_argument('--plan-only', action='store_true')
    args = p.parse_args()
    if pd.Timestamp(args.start) > pd.Timestamp(args.end) or args.interval < 65 or args.max_requests < 0:
        p.error('日期、间隔或请求数参数无效')
    dates, tasks = make_plan(args.start, args.end, args.chunk_days)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = {'start':args.start, 'end':args.end, 'trading_days':len(dates), 'segments':len(set((x[0],x[1]) for x in tasks)),
            'requests':len(tasks), 'symbols':len({x[2] for x in tasks}), 'interval_seconds':args.interval,
            'minimum_days':round(len(tasks)*args.interval/86400,1),
            'pool':'月末权重快照滞后31自然日，仅作近似；每段增加未来5个交易日的潜在成分用于因子预热，不能作为信号日股票池',
            'calendar':'本地日线缓存文件日期；应与正式交易日历核对',
            'source':'tushare','frequency':'1m','adjust':'none'}
    (args.output_dir/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(plan,ensure_ascii=False),flush=True)
    if args.plan_only: return
    with (args.output_dir/'worker.lock').open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('下载任务已在运行')
        state_path = args.output_dir/'rate_state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        service = create_service(repository=MinuteBatchRepository(args.output_dir/'batches',source='tushare'))
        service.router.policies[DataKind.MINUTE] = RoutePolicy(('tushare',),fallback_on_empty=False)
        completed = 0
        try:
            for i,(begin,finish,symbol) in enumerate(tasks,1):
                req = DataRequest(symbols=(symbol,),start=begin,end=finish,frequency='1m',adjust='none')
                if service.get_cached(DataKind.MINUTE,req,source='tushare') is not None:
                    continue
                failures = 0
                while True:
                    pause_until(float(state.get('last_request_at',0))+args.interval)
                    state = {'last_request_at':time.time(),'start':begin,'end':finish,'symbol':symbol}
                    temp = state_path.with_suffix('.json.tmp')
                    temp.write_text(json.dumps(state),encoding='utf-8'); os.replace(temp,state_path)
                    try:
                        bars = service.get_minute(req,use_cache=False,persist=True)
                        if bars.attrs.get('source') != 'tushare': raise ValueError('分钟行情来源不是 Tushare')
                        completed += 1
                        print(f'{i}/{len(tasks)} {begin}-{finish} {symbol} rows={len(bars)} source=tushare',flush=True)
                        break
                    except Exception as exc:
                        failures += 1
                        print(f'请求失败 {type(exc).__name__}: {str(exc)[:500]}',flush=True)
                        if '频率超限' in str(exc) and ('小时' in str(exc) or '每天' in str(exc) or '每月' in str(exc)):
                            raise RuntimeError('触发小时或更长周期限额，停止任务；核实额度后调整间隔并续跑') from exc
                        if '频率超限' not in str(exc) or failures >= 3:
                            raise
                if args.max_requests and completed >= args.max_requests: break
        finally:
            service.close()


if __name__ == '__main__': main()
