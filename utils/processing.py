import logging

import backtrader as bt
import backtrader.analyzers as btanalyzers
import numpy as np
import pandas as pd
import streamlit as st

from .logs import logger
from .schemas import BacktraderParams, DataParams, StrategyBase
from .xtdata_client import fetch_history_ohlcv, to_chinese_ohlcv

logging.getLogger("streamlit.runtime.scriptrunner_utils").setLevel(logging.ERROR)


model_hash_func = lambda x: x.model_dump()


@st.cache_data(hash_funcs={DataParams: model_hash_func})
def gen_stock_df(data_params: DataParams) -> pd.DataFrame:
    """生成股票数据

    Args:
        data_params (DataParams): AKShare 数据参数

    Returns:
        pd.DataFrame: 股票历史数据
    """
    df = fetch_history_ohlcv(
        symbol=data_params.symbol,
        period=data_params.period,
        start_date=data_params.start_date,
        end_date=data_params.end_date,
        dividend_type=data_params.dividend_type,
    )
    if not df.empty:
        return to_chinese_ohlcv(df)
    return pd.DataFrame()


@st.cache_data(hash_funcs={StrategyBase: model_hash_func, BacktraderParams: model_hash_func})
def run_backtrader(stock_df: pd.DataFrame, strategy: StrategyBase, bt_params: BacktraderParams) -> pd.DataFrame:
    """运行回测

    Args:
        stock_df (pd.DataFrame): 股票数据
        strategy (StrategyBase): 策略名称和参数
        bt_params (BacktraderParams): 回测参数

    Returns:
        pd.DataFrame: 回测结果
    """
    # 设置日期索引
    stock_df.index = pd.to_datetime(stock_df["date"])

    # 创建数据源
    data = bt.feeds.PandasData(dataname=stock_df, fromdate=bt_params.start_date, todate=bt_params.end_date)

    # 初始化回测引擎
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.broker.setcash(bt_params.start_cash)
    cerebro.broker.setcommission(commission=bt_params.commission_fee)
    cerebro.addsizer(bt.sizers.FixedSize, stake=bt_params.stake)

    # 添加分析器
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(btanalyzers.Returns, _name="returns")

    # 动态导入策略类
    try:
        strategy_cli = getattr(__import__("strategy"), f"{strategy.name}Strategy")
        cerebro.optstrategy(strategy_cli, **strategy.params)
    except (ImportError, AttributeError) as e:
        logger.error(f"策略导入失败: {e}")
        raise ValueError(f"无法找到策略: {strategy.name}Strategy")

    # 运行回测
    back = cerebro.run(maxcpus=1)

    # 处理回测结果
    par_list = []
    for x in back:
        # 收集策略参数
        par = []
        for param in strategy.params.keys():
            par.append(x[0].params._getkwargs()[param])

        returns_analysis = x[0].analyzers.returns.get_analysis()
        annual_return_pct = returns_analysis["rnorm100"]
        max_drawdown_pct = x[0].analyzers.drawdown.get_analysis()["max"]["drawdown"]
        total_return = np.expm1(returns_analysis.get("rtot", np.nan))
        calmar = (
            (annual_return_pct / 100.0) / (max_drawdown_pct / 100.0)
            if max_drawdown_pct
            else np.nan
        )

        # 添加性能指标
        par.extend(
            [
                annual_return_pct,
                total_return,
                max_drawdown_pct,
                x[0].analyzers.sharpe.get_analysis()["sharperatio"],
                calmar,
            ]
        )
        par_list.append(par)

    # 创建结果数据框
    columns = list(strategy.params.keys())
    columns.extend(["return", "total_return", "dd", "sharpe", "calmar"])
    par_df = pd.DataFrame(par_list, columns=columns)
    return par_df

