import logging

import backtrader as bt
import backtrader.analyzers as btanalyzers
import numpy as np
import pandas as pd
import streamlit as st

from .logs import logger
from .bigqmt_client import QmtDataClient, to_chinese_ohlcv
from .schemas import BacktraderParams, MarketDataParams, StrategyBase

logging.getLogger("streamlit.runtime.scriptrunner_utils").setLevel(logging.ERROR)


# 为 Streamlit 缓存提供 Pydantic 模型的稳定哈希输入。
model_hash_func = lambda x: x.model_dump()


@st.cache_data(hash_funcs={MarketDataParams: model_hash_func})
def gen_stock_df(market_data_params: MarketDataParams) -> pd.DataFrame:
    """根据行情参数从 Big QMT 拉取并转换股票历史数据。

    Args:
        market_data_params (MarketDataParams): Big QMT RPC 参数

    Returns:
        pd.DataFrame: 股票历史数据
    """
    df = QmtDataClient(timeout=market_data_params.bigqmt_timeout).history_ohlcv(
        symbol=market_data_params.symbol,
        period=market_data_params.period,
        start_date=market_data_params.start_date,
        end_date=market_data_params.end_date,
        dividend_type=market_data_params.dividend_type,
    )
    if not df.empty:
        return to_chinese_ohlcv(df)
    return pd.DataFrame()


@st.cache_data(hash_funcs={StrategyBase: model_hash_func, BacktraderParams: model_hash_func})
def run_backtrader(stock_df: pd.DataFrame, strategy: StrategyBase, bt_params: BacktraderParams) -> pd.DataFrame:
    """运行 Backtrader 参数寻优回测并汇总关键绩效指标。

    Args:
        stock_df (pd.DataFrame): 股票数据
        strategy (StrategyBase): 策略名称和参数
        bt_params (BacktraderParams): 回测参数

    Returns:
        pd.DataFrame: 回测结果
    """
    # Backtrader 需要以日期作为数据源索引。
    stock_df.index = pd.to_datetime(stock_df["date"])

    # 将页面上传入的行情 DataFrame 包装为 Backtrader 数据源。
    data = bt.feeds.PandasData(dataname=stock_df, fromdate=bt_params.start_date, todate=bt_params.end_date)

    # 初始化回测引擎并设置资金、佣金与固定手数。
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.broker.setcash(bt_params.start_cash)
    cerebro.broker.setcommission(commission=bt_params.commission_fee)
    cerebro.addsizer(bt.sizers.FixedSize, stake=bt_params.stake)

    # 分析器负责输出收益、回撤、夏普等后续展示指标。
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name="sharpe", riskfreerate=0.0)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(btanalyzers.Returns, _name="returns")

    # 策略名称来自配置和表单，需要在运行时解析到具体策略类。
    try:
        strategy_cli = getattr(__import__("strategy"), f"{strategy.name}Strategy")
        cerebro.optstrategy(strategy_cli, **strategy.params)
    except (ImportError, AttributeError) as e:
        logger.error(f"策略导入失败: {e}")
        raise ValueError(f"无法找到策略: {strategy.name}Strategy")

    # 固定单进程执行，避免 Streamlit 缓存环境下的多进程序列化问题。
    back = cerebro.run(maxcpus=1)

    # 汇总每组优化参数对应的分析器输出。
    par_list = []
    for x in back:
        # 保留参数值，便于页面表格对比不同参数组合。
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

        # 统一附加绩效指标列，供图表和表格直接消费。
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

    # 结果列顺序保持为策略参数在前、绩效指标在后。
    columns = list(strategy.params.keys())
    columns.extend(["return", "total_return", "dd", "sharpe", "calmar"])
    par_df = pd.DataFrame(par_list, columns=columns)
    return par_df
