"""Small2 的 Tushare 数据装配与 Backtrader 回测入口。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import backtrader as bt
import pandas as pd

from examples.backtest_common import build_return_metrics, read_result_detail, restore_metric_scores
from src.strategy.small_cap import SmallCapPandasData, SmallCapStrategy
from src.strategy_evaluation import evaluate_returns
from src.utils.commission import ChinaStockCommission
from src.utils.schemas import DataSourceParams

from .datahub_universe import DatahubUniverseClient, StockUniverseSnapshot

STRATEGY_NAME = "小市值策略(Small2)"
DEFAULT_CODES = ["000001.SZ", "600000.SH", "600036.SH", "600016.SH", "000651.SZ"]
DEFAULT_OUTPUT_DIR = Path("examples") / "small_cap"
DEFAULT_START_DATE = "2026-05-06"


@dataclass(frozen=True)
class SmallCapFrames:
	"""Small2 小市值策略页面展示与保存的结果表集合。"""

	metrics: pd.DataFrame
	returns: pd.DataFrame
	cumulative: pd.DataFrame
	drawdown: pd.DataFrame
	universe_snapshot: pd.DataFrame
	rebalance_history: pd.DataFrame


def build_small_cap_snapshots(
    client: DatahubUniverseClient,
    rebalance_dates: list[date | str | pd.Timestamp],
    sector_name: str = "沪深A股",
    codes: list[str] | None = None,
) -> dict[pd.Timestamp, StockUniverseSnapshot]:
    """按调仓日构建并返回股票池快照。

    ``codes`` 可限制为研究样本；传入 ``None`` 时读取完整板块股票池。调用方可将
    快照持久化以复用高成本的 Tushare 全市场元数据请求。
    """
    return {
        pd.Timestamp(day).normalize(): client.snapshot(day, sector_name, codes=codes)
        for day in rebalance_dates
    }


def prepare_small_cap_price_data(
    client: DatahubUniverseClient,
    snapshots: dict[pd.Timestamp, StockUniverseSnapshot],
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    lookback_days: int = 100,
    index_codes: tuple[str, str] = ("000852.SH", "000300.SH"),
) -> dict[str, pd.DataFrame]:
    """读取所有快照中的候选股票及市场指数日线，保留 ``amount`` 列。"""
    codes = set(index_codes)
    for snapshot in snapshots.values():
        codes.update(snapshot.stocks["code"].dropna().astype(str))
    start = pd.Timestamp(start_date).normalize() - timedelta(days=lookback_days * 2)
    return client.daily_bars(sorted(codes), start, end_date)


def run_small_cap_backtest(
    price_data: dict[str, pd.DataFrame],
    snapshots: dict[pd.Timestamp, StockUniverseSnapshot],
    initial_cash: float,
    strategy_params: dict[str, Any] | None = None,
    market_factors: pd.DataFrame | None = None,
    backtest_start_date: Any | None = None,
) -> SmallCapStrategy:
    """使用已下载的行情与快照运行 Small2，返回策略实例供读取调仓记录。

    行情数据可以包含策略指标所需的预热区间；实际调仓从 ``backtest_start_date`` 开始。
    """
    if not snapshots:
        raise ValueError("Small2 回测至少需要一个股票池快照")
    cerebro = bt.Cerebro()
    for code, frame in price_data.items():
        required = {"date", "open", "high", "low", "close", "volume", "amount"}
        if not required.issubset(frame.columns):
            continue
        data_frame = frame.copy().set_index(pd.to_datetime(frame["date"]))
        cerebro.adddata(SmallCapPandasData(dataname=data_frame), name=code)
    if not cerebro.datas:
        raise ValueError("Small2 回测没有可用的含 amount 日线数据")
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.addcommissioninfo(ChinaStockCommission())
    params = dict(strategy_params or {})
    params.update({
        "universe_snapshots": snapshots,
        "market_factors": market_factors,
        "backtest_start_date": backtest_start_date,
    })
    cerebro.addstrategy(SmallCapStrategy, **params)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="daily_returns", timeframe=bt.TimeFrame.Days)
    result = cerebro.run()[0]
    returns = pd.Series(result.analyzers.daily_returns.get_analysis(), dtype=float)
    returns.index = pd.to_datetime(returns.index)
    if backtest_start_date is not None and not returns.empty:
        returns = returns.loc[pd.Timestamp(backtest_start_date).normalize():]
    result.daily_returns = returns
    result.evaluation = evaluate_returns(returns)
    return result


def _format_rebalance_records(records: list[dict]) -> pd.DataFrame:
    """将 Small2 调仓记录格式化为展示表格。"""
    rows = []
    for item in records:
        selected = item.get("selected_names") or []
        rows.append(
            {
                "调仓日期": str(item.get("date", "")),
                "持仓数量": len(selected),
                "入选标的": ", ".join(str(code) for code in selected),
                "目标仓位": item.get("exposure"),
            }
        )
    return pd.DataFrame(rows)


def _load_rebalance_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return pd.DataFrame()
    if not isinstance(raw, list) or not raw:
        return pd.DataFrame()
    return _format_rebalance_records(raw)


def load_small_cap_results(output_dir: Path = DEFAULT_OUTPUT_DIR) -> SmallCapFrames | None:
    """加载已保存的 Small2 回测结果；兼容仅有快照和调仓历史的目录。"""
    metrics_path = output_dir / "performance_metrics.csv"
    snapshot_path = output_dir / "universe_snapshot.csv"
    rebalance_path = output_dir / "rebalance_history.json"
    if not any(path.exists() for path in (metrics_path, snapshot_path, rebalance_path)):
        return None

    returns_path = output_dir / "daily_returns.csv"
    cumulative_path = output_dir / "cumulative_returns.csv"
    drawdown_path = output_dir / "drawdowns.csv"

    returns = pd.read_csv(returns_path, encoding="utf-8-sig") if returns_path.exists() else pd.DataFrame()
    metrics = pd.read_csv(metrics_path, encoding="utf-8-sig") if metrics_path.exists() else pd.DataFrame()
    if not metrics.empty and "策略" not in metrics.columns:
        metrics.insert(0, "策略", STRATEGY_NAME)
    if not metrics.empty and not returns.empty:
        metrics = restore_metric_scores(metrics, returns)

    return SmallCapFrames(
        metrics=metrics,
        returns=returns,
        cumulative=pd.read_csv(cumulative_path, encoding="utf-8-sig") if cumulative_path.exists() else pd.DataFrame(),
        drawdown=pd.read_csv(drawdown_path, encoding="utf-8-sig") if drawdown_path.exists() else pd.DataFrame(),
        universe_snapshot=read_result_detail(snapshot_path) if snapshot_path.exists() else pd.DataFrame(),
        rebalance_history=_load_rebalance_history(rebalance_path),
    )


def run_small_cap_page_backtest(
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    initial_cash: float = 1_000_000.0,
    codes: list[str] | None = None,
    full_universe: bool = False,
    sector_name: str = "沪深A股",
    stock_num: int = 3,
    pool_num: int = 100,
    rebalance_days: int = 10,
    min_cap: float = 5.0,
    max_cap: float = 5_000.0,
    listing_days: int = 375,
    avoid_months: tuple[int, ...] = (),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    data_source_params: DataSourceParams | None = None,
    price_data: dict[str, pd.DataFrame] | None = None,
    snapshots: dict[pd.Timestamp, StockUniverseSnapshot] | None = None,
) -> SmallCapFrames:
    """运行 Small2 小市值回测并输出可供 Streamlit 展示与复用的完整结果表。"""
    end_str = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    if snapshots is None:
        token = (data_source_params.tushare_token if data_source_params else "").strip() or None
        timeout = float(data_source_params.tushare_timeout) if data_source_params else 30.0
        client = DatahubUniverseClient(token=token, timeout=timeout)
        snapshot_codes = None if full_universe else (codes or list(DEFAULT_CODES))
        raw_snapshots = build_small_cap_snapshots(
            client,
            [start_date],
            sector_name=sector_name,
            codes=snapshot_codes,
        )
        snapshot = next(iter(raw_snapshots.values()))
        eligible = snapshot.eligible_codes(listing_days, min_cap, max_cap)
        if not eligible:
            raise RuntimeError("当前快照没有满足 Small2 基础条件的股票")
        snapshot = StockUniverseSnapshot(
            snapshot.as_of,
            snapshot.stocks[snapshot.stocks["code"].isin(eligible)].reset_index(drop=True),
        )
        snapshots = {snapshot.as_of: snapshot}
        if price_data is None:
            price_data = prepare_small_cap_price_data(client, snapshots, start_date, end_str)
    else:
        snapshot = next(iter(snapshots.values()))
        eligible = snapshot.eligible_codes(listing_days, min_cap, max_cap)
        if not eligible:
            eligible = snapshot.stocks["code"].dropna().astype(str).tolist()
        if price_data is None:
            raise ValueError("提供 snapshots 时需同时提供 price_data")

    strategy = run_small_cap_backtest(
        price_data,
        snapshots,
        initial_cash,
        strategy_params={
            "stock_num": min(int(stock_num), max(len(eligible), 1)),
            "pool_num": int(pool_num),
            "min_cap": float(min_cap),
            "max_cap": float(max_cap),
            "listing_days": int(listing_days),
            "rebalance_days": int(rebalance_days),
            "market_guard": False,
            "avoid_months": avoid_months,
        },
        backtest_start_date=start_date,
    )

    daily_returns = strategy.daily_returns.dropna()
    nav = (1.0 + daily_returns).cumprod()
    drawdown = nav / nav.cummax() - 1.0

    metrics = pd.DataFrame(
        [
            {"策略": STRATEGY_NAME}
            | build_return_metrics(daily_returns)
            | {
                "合格标的数": len(eligible),
                "调仓次数": len(strategy.rebalance_history),
                "期末资产": float(strategy.broker.getvalue()),
            }
        ]
    )
    date_labels = daily_returns.index.strftime("%Y-%m-%d")
    returns_df = pd.DataFrame({"Date": date_labels, STRATEGY_NAME: daily_returns.values})
    cumulative_df = pd.DataFrame({"Date": date_labels, STRATEGY_NAME: nav.values})
    drawdown_df = pd.DataFrame({"Date": date_labels, STRATEGY_NAME: drawdown.values})
    rebalance_df = _format_rebalance_records(strategy.rebalance_history)

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
    returns_df.to_csv(output_dir / "daily_returns.csv", index=False, encoding="utf-8-sig")
    cumulative_df.to_csv(output_dir / "cumulative_returns.csv", index=False, encoding="utf-8-sig")
    drawdown_df.to_csv(output_dir / "drawdowns.csv", index=False, encoding="utf-8-sig")
    snapshot.stocks.to_csv(output_dir / "universe_snapshot.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(strategy.rebalance_history).to_json(
        output_dir / "rebalance_history.json",
        orient="records",
        force_ascii=False,
        indent=2,
    )

    return SmallCapFrames(
        metrics=metrics,
        returns=returns_df,
        cumulative=cumulative_df,
        drawdown=drawdown_df,
        universe_snapshot=snapshot.stocks,
        rebalance_history=rebalance_df,
    )
