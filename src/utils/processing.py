import logging
from importlib import import_module

import backtrader as bt
import backtrader.analyzers as btanalyzers
import pandas as pd
import streamlit as st

from src.strategy_evaluation import SCORE_COLUMNS, SCORE_VERSION, evaluate_returns

from .logs import logger
from .datahub_client import DataHubClient, to_chinese_ohlcv
from .schemas import BacktraderParams, MarketDataParams, StrategyBase

logging.getLogger("streamlit.runtime.scriptrunner_utils").setLevel(logging.ERROR)


# 为 Streamlit 缓存提供 Pydantic 模型的稳定哈希输入。
model_hash_func = lambda x: x.model_dump()
BACKTRADER_METRIC_COLUMNS = ("return", "total_return", "dd", "sharpe", "calmar", "annual_volatility")
BACKTRADER_PERIODS = {
    "1d": (bt.TimeFrame.Days, 252),
    "1w": (bt.TimeFrame.Weeks, 52),
    "1mon": (bt.TimeFrame.Months, 12),
}


@st.cache_data(hash_funcs={MarketDataParams: model_hash_func})
def gen_stock_df(market_data_params: MarketDataParams) -> pd.DataFrame:
    """根据行情参数通过 DataHub 拉取并转换股票历史数据。

    Args:
        market_data_params (MarketDataParams): 统一行情请求参数

    Returns:
        pd.DataFrame: 股票历史数据
    """
    df = DataHubClient(
        token=market_data_params.tushare_token or None,
        timeout=market_data_params.tushare_timeout,
    ).history_ohlcv(
        symbol=market_data_params.symbol,
        period=market_data_params.period,
        start_date=market_data_params.start_date,
        end_date=market_data_params.end_date,
        dividend_type=market_data_params.dividend_type,
    )
    if not df.empty:
        return to_chinese_ohlcv(df)
    return pd.DataFrame()


def run_backtrader(
    stock_df: pd.DataFrame, strategy: StrategyBase, bt_params: BacktraderParams, *, period: str = "1d"
) -> pd.DataFrame:
    """运行参数寻优并为每组回测参数生成评分。"""
    return _run_backtrader(stock_df, strategy, bt_params, period, SCORE_VERSION)


@st.cache_data(hash_funcs={StrategyBase: model_hash_func, BacktraderParams: model_hash_func})
def _run_backtrader(
    stock_df: pd.DataFrame, strategy: StrategyBase, bt_params: BacktraderParams, period: str, score_version: str
) -> pd.DataFrame:
    timeframe, periods_per_year = BACKTRADER_PERIODS[period]
    # Backtrader 需要以日期作为数据源索引。
    stock_df = stock_df.set_index(pd.to_datetime(stock_df["date"]))

    # 将页面上传入的行情 DataFrame 包装为 Backtrader 数据源。
    data = bt.feeds.PandasData(
        dataname=stock_df, fromdate=bt_params.start_date, todate=bt_params.end_date, timeframe=timeframe
    )

    # 初始化回测引擎并设置资金、佣金与固定手数。
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.broker.setcash(bt_params.start_cash)
    cerebro.broker.setcommission(commission=bt_params.commission_fee)
    cerebro.addsizer(bt.sizers.FixedSize, stake=bt_params.stake)

    cerebro.addanalyzer(btanalyzers.TimeReturn, _name="period_returns", timeframe=timeframe)

    # 策略名称来自配置和表单，需要在运行时解析到具体策略类。
    try:
        strategy_cli = getattr(import_module("src.strategy"), f"{strategy.name}Strategy")
        cerebro.optstrategy(strategy_cli, **strategy.params)
    except (ImportError, AttributeError) as e:
        logger.error(f"策略导入失败: {e}")
        raise ValueError(f"无法找到策略: {strategy.name}Strategy")

    # 固定单进程执行，避免 Streamlit 缓存环境下的多进程序列化问题。
    back = cerebro.run(maxcpus=1)

    rows = []
    for result, in back:
        returns = list(result.analyzers.period_returns.get_analysis().values())
        evaluation = evaluate_returns(returns, periods_per_year)
        metrics = evaluation.metrics
        annual, drawdown = metrics["annual_return"], metrics["max_drawdown"]
        rows.append(
            {name: result.params._getkwargs()[name] for name in strategy.params}
            | {
                "return": annual * 100 if annual is not None else None,
                "total_return": metrics["total_return"],
                "dd": abs(drawdown) * 100 if drawdown is not None else None,
                "sharpe": metrics["sharpe"],
                "calmar": metrics["calmar"],
                "annual_volatility": metrics["annual_volatility"],
            }
            | evaluation.scoring
            | {"score_version": score_version}
        )
    return pd.DataFrame(rows, columns=[*strategy.params, *BACKTRADER_METRIC_COLUMNS, *SCORE_COLUMNS])
