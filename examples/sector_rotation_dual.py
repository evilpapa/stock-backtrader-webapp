"""双轮配置行业 ETF 策略：Tushare 真实数据回测。

运行：``uv run python -m examples.sector_rotation_dual [--no-dtw]``

关注热度因子 Tushare 无法提供（见 docs/sector_rotation_dual/data.md），
本示例通过 --heat 选择 Tushare 可得的替代来源（默认 ths_etf，约 2023-08 起，之前逐格退化为仅净申赎）。
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.strategy.sector_rotation_dual import SectorRotationDualStrategy, TushareSectorRotationLoader, summarize
from src.utils.datahub_client import DataHubClient

OUT = Path(__file__).parent / "sector_rotation_dual"


def _ensure_token() -> None:
	"""未设置环境变量时，从项目 .env 读取 TUSHARE_TOKEN（不打印）。"""
	if os.getenv("TUSHARE_TOKEN"):
		return
	env = Path(".env")
	if env.exists():
		m = re.search(r"^TUSHARE_TOKEN\s*=\s*[\"']?([^\"'\s#]+)", env.read_text(), re.M)
		if m:
			os.environ["TUSHARE_TOKEN"] = m.group(1)


def main() -> None:
	p = argparse.ArgumentParser()
	p.add_argument("--start", default="2017-09-01")
	p.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
	p.add_argument("--top-k", type=int, default=3, help="每个中信一级行业保留的指数数量（近似报告的定性筛选）")
	p.add_argument("--no-dtw", action="store_true")
	p.add_argument("--refresh-pool", action="store_true", help="重建 ETF 池（否则复用 pool.csv）")
	p.add_argument("--heat", default="ths_etf", choices=["none", "ths_etf", "ths_stock", "etf_amount", "index_amount"],
		help="热度来源；Tushare 无报告口径热度，none=仅净申赎")
	args = p.parse_args()

	_ensure_token()
	OUT.mkdir(exist_ok=True)
	loader = TushareSectorRotationLoader(DataHubClient())
	pool_path = OUT / "pool.csv"
	if args.refresh_pool or not pool_path.exists():
		pool = loader.build_pool(args.end, top_k_per_industry=args.top_k)
		pool.to_csv(pool_path, index=False)
	else:
		pool = pd.read_csv(pool_path)
	print(f"ETF 池：{len(pool)} 只，覆盖 {pool['industry'].nunique()} 个行业")

	data = loader.load(pool, args.start.replace("-", ""), args.end.replace("-", ""),
		heat=None if args.heat == "none" else args.heat)
	print("数据来源标识：")
	for k, v in data.source_flags.items():
		print(f"  [{k}] {v}")

	res = SectorRotationDualStrategy(use_dtw=not args.no_dtw, allow_missing_heat=args.heat == "none").run(data)
	table = summarize(res)
	pd.options.display.float_format = "{:.3f}".format
	print(table)
	w = res.weights
	print(f"DTW 有效周占比 {w['dtw_valid'].mean():.1%}；w 均值 {w['w'].mean():.3f}，贴边(0.2/0.8)占比 {(w['w'].isin([0.2, 0.8])).mean():.1%}；"
		f"热度覆盖>50% 的周占比 {(w['heat_active'] > 0.5).mean():.1%}")
	table.to_csv(OUT / "summary.csv")
	res.weights.to_csv(OUT / "weights.csv")

	fig, ax = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
	pd.DataFrame({"combo": res.nav, "pos": res.pos_nav, "rev": res.rev_nav, "bench": res.benchmark_nav}).plot(ax=ax[0])
	res.weights["w"].plot(ax=ax[1], title="positive weight w")
	fig.savefig(OUT / "nav.png", dpi=120)


if __name__ == "__main__":
	main()
