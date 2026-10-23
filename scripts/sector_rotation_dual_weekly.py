"""双轮配置行业 ETF 策略：每周调仓信号脚本（只出目标仓位，不下单）。

用法（建议周一开盘前、Tushare 份额 8:30 入库后运行）::

    uv run python scripts/sector_rotation_dual_weekly.py                 # 试算，不更新持仓状态
    uv run python scripts/sector_rotation_dual_weekly.py --commit        # 确认执行后写入状态
    uv run python scripts/sector_rotation_dual_weekly.py --asof 2026-10-23
    uv run python scripts/sector_rotation_dual_weekly.py --refresh-pool  # 重建 ETF 池（建议每月/季度）

信号日 = 最近一个已结束周的最后一个交易日；目标仓位用于**下一交易日开盘价**调仓（与回测一致）。
热度因子固定使用 ths_hot ETF 榜（Tushare 可得的部分替代，约 2023-08 起，之前仅净申赎）。
输出目录：examples/sector_rotation_dual/live/（pool.csv、state.json、target_<信号日>.csv）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.strategy.sector_rotation_dual import SectorRotationDualStrategy, TushareSectorRotationLoader  # noqa: E402
from src.constants import INITIAL_CASH  # noqa: E402
from src.utils.datahub_client import DataHubClient  # noqa: E402

LIVE = ROOT / "examples" / "sector_rotation_dual" / "live"
POOL_REFRESH_DAYS = 45  # 池文件超过该天数时提示刷新


def _ensure_token() -> None:
	"""未设置环境变量时，从项目 .env 读取 TUSHARE_TOKEN（不打印）。"""
	if os.getenv("TUSHARE_TOKEN"):
		return
	env = ROOT / ".env"
	if env.exists():
		m = re.search(r"^TUSHARE_TOKEN\s*=\s*[\"']?([^\"'\s#]+)", env.read_text(), re.M)
		if m:
			os.environ["TUSHARE_TOKEN"] = m.group(1)


def load_state() -> dict:
	p = LIVE / "state.json"
	return json.loads(p.read_text()) if p.exists() else {"signal_date": None, "holdings": {}}


def diff_orders(prev: dict[str, float], target: dict[str, float], min_delta: float) -> pd.DataFrame:
	"""目标与当前持仓的权重差；|Δ|<min_delta 的小调整标记为忽略。"""
	rows = []
	for code in sorted(set(prev) | set(target)):
		p, t = prev.get(code, 0.0), target.get(code, 0.0)
		d = t - p
		action = "买入" if d > 0 else "卖出" if d < 0 else "持有"
		if 0 < abs(d) < min_delta:
			action += "(小额,可忽略)"
		rows.append({"etf": code, "当前权重": p, "目标权重": t, "调整": d, "动作": action})
	return pd.DataFrame(rows)


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--asof", help="信号日 YYYY-MM-DD，须为某周最后一个交易日；默认=最近已结束周的最后交易日")
	ap.add_argument("--history-start", default="2022-01-01", help="因子/配置层历史起点（越早越慢，DTW 库固定 2015 起）")
	ap.add_argument("--refresh-pool", action="store_true", help="重建 ETF 池（调用较多，约十几分钟）")
	ap.add_argument("--top-k", type=int, default=3, help="每个中信一级行业保留的指数数量")
	ap.add_argument("--no-dtw", action="store_true", help="关闭 DTW 信号（更快，偏离报告）")
	ap.add_argument("--shares-lag", type=int, default=0, help="份额滞后交易日数；周一 8:30 后运行时份额已到信号日，默认 0")
	ap.add_argument("--cash", type=float, default=INITIAL_CASH, help="账户规模（元），用于按 commission.py 估算手续费（含最低 5 元）")
	ap.add_argument("--min-delta", type=float, default=0.01, help="小于该权重差的调整标记为可忽略")
	ap.add_argument("--commit", action="store_true", help="写入 state.json，作为下周比较的“当前持仓”")
	args = ap.parse_args()

	_ensure_token()
	LIVE.mkdir(parents=True, exist_ok=True)
	loader = TushareSectorRotationLoader(DataHubClient())
	asof = pd.Timestamp(args.asof) if args.asof else loader.last_completed_week_end()
	end = asof.strftime("%Y%m%d")
	print(f"信号日：{asof.date()}（{['周一','周二','周三','周四','周五','周六','周日'][asof.weekday()]}）")

	# --- ETF 池 ---
	pool_path = LIVE / "pool.csv"
	if args.refresh_pool or not pool_path.exists():
		pool = loader.build_pool(end, top_k_per_industry=args.top_k)
		pool.to_csv(pool_path, index=False)
		print(f"已重建 ETF 池：{len(pool)} 只 / {pool['industry'].nunique()} 个行业")
	else:
		pool = pd.read_csv(pool_path)
		age = (pd.Timestamp.today() - pd.Timestamp(pool_path.stat().st_mtime, unit="s")).days
		print(f"使用已有 ETF 池：{len(pool)} 只（{age} 天前生成）" + ("，建议 --refresh-pool" if age > POOL_REFRESH_DAYS else ""))

	# --- 数据（热度固定 ths_etf）---
	data = loader.load(pool, args.history_start.replace("-", ""), end, heat="ths_etf")
	if data.close.index[-1] != asof:
		print(f"错误：行情最后日期 {data.close.index[-1].date()} != 信号日 {asof.date()}，Tushare 数据可能尚未更新", file=sys.stderr)
		return 2
	missing = data.close.iloc[-1].isna()
	if missing.any():
		print(f"警告：{int(missing.sum())} 只 ETF 信号日无收盘价（停牌/未上市），已自动排除：{list(missing[missing].index)}")
	if data.shares.iloc[-1].isna().all() or data.shares.iloc[-1].equals(data.shares.iloc[-2]):
		print("警告：信号日份额与前一日完全相同，etf_share_size 可能尚未入库（8:30 后更新），净申赎因子当日为 0")
	print("数据来源标识：")
	for k, v in data.source_flags.items():
		print(f"  [{k}] {v}")

	# --- 信号 ---
	strat = SectorRotationDualStrategy(use_dtw=not args.no_dtw, shares_lag=args.shares_lag, initial_cash=args.cash)
	res = strat.latest_target(data)
	sg = res["signals"]
	names = loader._call("etf_basic", list_status="L").set_index("ts_code")["csname"].to_dict()
	ind = data.industry

	def fmt(x):
		return "NaN" if pd.isna(x) else f"{x:.3f}"

	print(
		f"\n正向权重 w = {res['w']:.3f}（反向 {1 - res['w']:.3f}）"
		f" | TZ25={fmt(sg['tz25'])} G12={fmt(sg['g12'])} D_pos={fmt(sg['d_pos'])}"
		f" | DTW有效={bool(sg['dtw_valid'])} 热度覆盖={sg['heat_active']:.0%}"
	)
	if not args.no_dtw and not sg["dtw_valid"]:
		print("  提示：本周 DTW 弃权（无相似样本），权重由 TZ25 与 G12 决定")
	if sg["heat_active"] < 0.5:
		print("  提示：本周热度覆盖不足，反向篮子主要由净申赎决定")
	for label, key in (("正向篮子（趋势）", "pos"), ("反向篮子（双冷门）", "rev")):
		print(f"{label}：" + "、".join(f"{c} {names.get(c, '')}[{ind.get(c, '')}]" for c in res[key]))

	# --- 目标 & 调仓单 ---
	target = res["target"]
	state = load_state()
	orders = diff_orders(state["holdings"], target, args.min_delta)
	orders.insert(1, "名称", orders["etf"].map(names))
	orders.insert(2, "行业", orders["etf"].map(ind))
	pd.options.display.float_format = "{:.3f}".format
	pd.options.display.width = 200
	prev_date = state["signal_date"] or "无（首次）"
	print(f"\n调仓单（对比上期状态 {prev_date}）：")
	print(orders.to_string(index=False))
	turnover = orders["调整"].abs().sum()
	fee = strat._fee_ratio(state["holdings"], target, args.cash)
	print(f"单边换手约 {turnover / 2:.1%}（买卖合计 {turnover:.1%}），按 commission.py 估算手续费约 {fee * args.cash:.2f} 元（{fee:.4%}，账户 {args.cash:,.0f} 元）")

	out = LIVE / f"target_{asof.strftime('%Y%m%d')}.csv"
	orders.to_csv(out, index=False)
	print(f"\n已保存：{out}")
	if args.commit:
		(LIVE / "state.json").write_text(
			json.dumps({"signal_date": str(asof.date()), "w": res["w"], "holdings": target}, ensure_ascii=False, indent=1)
		)
		print("已更新 state.json（视为已按目标仓位调仓）")
	else:
		print("试算模式：未更新 state.json；确认已调仓后加 --commit 重跑（数据有缓存，很快）")
	return 0


if __name__ == "__main__":
	sys.exit(main())
