"""
ETF动量轮动策略 (Python版本)
基于风险调整动量的多资产轮动策略

原始策略来源: strategy/etf_momentum/strategy.r
R包到Python包的映射:
- quantmod → yfinance/akshare (金融数据获取)
- PerformanceAnalytics → empyrical + 自定义计算 (绩效分析)
- dplyr/tidyr → pandas (数据处理)
- ggplot2/patchwork → matplotlib (绘图)

策略逻辑:
1. 计算每个ETF的20日动量（平均收益率）
2. 计算20日波动率（标准差）
3. 计算风险调整动量 = 动量 / 波动率
4. 只选择风险调整动量 > 0 的ETF
5. 按风险调整动量大小分配权重（归一化）
"""

import backtrader as bt
import numpy as np

from .base import BaseStrategy


class EtfMomentumStrategy(BaseStrategy):
    """
    ETF动量轮动策略
    
    基于风险调整动量的多资产轮动策略，适用于多ETF回测。
    策略会根据每个ETF的风险调整动量动态分配权重。
    
    Parameters:
    - momentum_window: 动量计算窗口（默认20天）
    - rebalance_days: 再平衡频率（默认每日）
    - printlog: 是否打印日志
    """
    
    _name = "EtfMomentum"
    params = (
        ("momentum_window", 20),  # 动量计算窗口
        ("rebalance_days", 1),     # 再平衡频率（天）
        ("printlog", False),
    )
    
    def __init__(self):
        super().__init__()
        
        # 追踪所有数据源
        self.dataclose = [d.close for d in self.datas]
        
        # 订单追踪
        self.order = None
        self.rebalance_counter = 0
        
        # 为每个数据源计算收益率
        self.returns = []
        for data in self.datas:
            # 计算日收益率
            ret = bt.indicators.PctChange(data.close, period=1)
            self.returns.append(ret)
        
        # 用于存储每个数据源的指标
        self.momentum = []      # 动量（平均收益率）
        self.volatility = []    # 波动率（收益率标准差）
        self.adj_momentum = []  # 风险调整动量
        
        for ret in self.returns:
            # 计算滚动平均收益率（动量）
            momentum = bt.indicators.SimpleMovingAverage(
                ret, period=self.params.momentum_window
            )
            self.momentum.append(momentum)
            
            # 计算滚动标准差（波动率）
            volatility = bt.indicators.StandardDeviation(
                ret, period=self.params.momentum_window
            )
            self.volatility.append(volatility)
        
        self.log("ETF动量策略初始化完成", doprint=True)
        self.log(f"参数: 动量窗口={self.params.momentum_window}, "
                f"再平衡频率={self.params.rebalance_days}天", doprint=True)
    
    def next(self):
        """每个交易日执行"""
        
        # 检查是否到达再平衡日
        self.rebalance_counter += 1
        if self.rebalance_counter < self.params.rebalance_days:
            return
        
        # 重置计数器
        self.rebalance_counter = 0
        
        # 检查是否有足够的数据
        if len(self.datas[0]) < self.params.momentum_window:
            return
        
        # 计算所有ETF的风险调整动量
        adj_momentum_values = []
        for i in range(len(self.datas)):
            if len(self.momentum[i]) > 0 and len(self.volatility[i]) > 0:
                mom = self.momentum[i][0]
                vol = self.volatility[i][0]
                
                # 计算风险调整动量 = 动量 / 波动率
                # 避免除以零
                if vol > 1e-8:
                    adj_mom = mom / vol
                else:
                    adj_mom = 0.0
                
                adj_momentum_values.append(adj_mom)
            else:
                adj_momentum_values.append(0.0)
        
        # 筛选风险调整动量 > 0 的ETF
        positive_indices = [i for i, v in enumerate(adj_momentum_values) if v > 0]
        
        # 计算目标权重
        target_weights = np.zeros(len(self.datas))
        
        if len(positive_indices) > 0:
            # 获取正的风险调整动量值
            positive_momentum = np.array([adj_momentum_values[i] for i in positive_indices])
            
            # 归一化权重
            total_momentum = np.sum(positive_momentum)
            if total_momentum > 0:
                normalized_weights = positive_momentum / total_momentum
                
                # 分配权重
                for idx, weight in zip(positive_indices, normalized_weights):
                    target_weights[idx] = weight
        
        # 执行再平衡
        self._rebalance_portfolio(target_weights)
        
        # 记录权重信息
        if self.params.printlog:
            weight_info = ", ".join([f"ETF{i}: {w:.2%}" for i, w in enumerate(target_weights)])
            self.log(f"再平衡权重: {weight_info}")
    
    def _rebalance_portfolio(self, target_weights):
        """
        根据目标权重调整持仓
        
        Args:
            target_weights: 每个ETF的目标权重数组
        """
        total_value = self.broker.getvalue()
        
        for i, data in enumerate(self.datas):
            target_weight = target_weights[i]
            target_value = total_value * target_weight
            
            # 计算当前持仓价值
            current_position = self.getposition(data).size
            current_price = data.close[0]
            current_value = current_position * current_price
            
            # 计算需要调整的价值
            diff_value = target_value - current_value
            
            # 如果差异超过阈值，则进行调整
            threshold = total_value * 0.01  # 1%的阈值
            if abs(diff_value) > threshold:
                # 计算需要买入或卖出的股数
                size = int(diff_value / current_price)
                
                if size > 0:
                    self.log(f"ETF{i} 买入: {size}股 @ {current_price:.2f}")
                    self.buy(data=data, size=size)
                elif size < 0:
                    self.log(f"ETF{i} 卖出: {-size}股 @ {current_price:.2f}")
                    self.sell(data=data, size=-size)
    
    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f"买入执行: 价格={order.executed.price:.2f}, "
                    f"成本={order.executed.value:.2f}, "
                    f"手续费={order.executed.comm:.2f}"
                )
            else:
                self.log(
                    f"卖出执行: 价格={order.executed.price:.2f}, "
                    f"成本={order.executed.value:.2f}, "
                    f"手续费={order.executed.comm:.2f}"
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log("订单取消/保证金不足/拒绝")
        
        self.order = None
    
    def notify_trade(self, trade):
        """交易完成通知"""
        if not trade.isclosed:
            return
        
        self.log(f"交易利润: 毛利={trade.pnl:.2f}, 净利={trade.pnlcomm:.2f}")
    
    def stop(self):
        """策略结束时调用"""
        self.log(
            f"(ETF动量策略 动量窗口={self.params.momentum_window}) "
            f"期末价值 {self.broker.getvalue():.2f}",
            doprint=True
        )
