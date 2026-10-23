"""关注热度候选因子的数据可得性与 RankIC 评估（Tushare）。

运行：``uv run python -m examples.sector_rotation_dual_heat``
各候选均按报告口径构造 5 日均值/250 日均值，取负号后评估与未来 5 日收益的截面 RankIC
（报告：iFinD 热度因子 RankIC 2.28%，t=1.93）。
"""

from __future__ import annotations

import argparse

import pandas as pd

from examples.sector_rotation_dual import OUT, _ensure_token
from src.strategy.sector_rotation_dual import TushareSectorRotationLoader
from src.strategy.sector_rotation_dual import factors as fct
from src.strategy.sector_rotation_dual import heat as H
from src.utils.datahub_client import DataHubClient

HOT_START = "20230801"


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("--skip-turnover", action="store_true", help="跳过全市场换手率（逐日拉取，耗时数小时）")
	ap.add_argument("--turnover-start", default="20230101", help="换手率拉取起点（逐日拉取，越早越慢）")
	ap.add_argument("--skip-hot", action="store_true", help="跳过热榜（逐日拉取）")
	args = ap.parse_args()
	_ensure_token()
	end = pd.Timestamp.today().strftime("%Y%m%d")
	loader = TushareSectorRotationLoader(DataHubClient())
	pool = pd.read_csv(OUT / "pool.csv")
	data = loader.load(pool, "20170901", end)
	days, close = data.close.index, data.close
	cons = loader.constituents(pool, end)

	cand: dict[str, pd.DataFrame] = {}
	etf_amt, idx_amt = loader.amount_panels(pool, "20150101", end)
	cand["ETF成交额(PROXY)"] = etf_amt.reindex(days)
	cand["指数成交额(PROXY)"] = idx_amt.reindex(days)
	if not args.skip_turnover:
		turn = loader.daily_turnover(args.turnover_start, end)
		cand["成分股换手率中位数(PROXY)"] = H.turnover_heat(turn, cons, pool).reindex(days)
	for api, mk, label, fn in () if args.skip_hot else (
		("ths_hot", "热股", "THS热股榜-成分股热度和(PARTIAL)", None),
		("ths_hot", "ETF", "THS ETF榜-ETF热度(PARTIAL)", "etf"),
	):
		hot = loader.hot_rank(api, mk, HOT_START, end)
		cand[label] = (
			H.etf_hot_list_heat(hot, pool, days) if fn == "etf" else H.hot_list_heat(hot, cons, pool, days)
		)

	if not args.skip_hot:
		cand["THS板块榜→中信行业(PARTIAL)"] = loader.build_heat("ths_board", pool, days, end)

	rows = []
	for name, heat in cand.items():
		ratio = fct.attention_heat_ratio(heat)
		valid = ratio.notna().any(axis=1)
		row = {"候选": name, "有效起点": ratio.index[valid][0].date() if valid.any() else None}
		for tag, since in (("全样本", None), ("2024-09起", "2024-09-01")):
			r = ratio if since is None else ratio.loc[since:]
			s = H.ic_summary(H.rank_ic(-r, close))
			row.update({f"{tag}n": s["n"], f"{tag}IC": s["IC均值"], f"{tag}t": s["t值"]})
		rows.append(row)
	res = pd.DataFrame(rows)
	pd.options.display.float_format = "{:.4f}".format
	pd.options.display.width = 200
	print(res.to_string(index=False))
	res.to_csv(OUT / "heat_ic.csv", index=False)


if __name__ == "__main__":
	main()
