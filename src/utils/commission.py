import backtrader as bt

class ChinaStockCommission(bt.CommInfoBase):
    """A 股交易手续费模型，包含比例佣金和最低佣金限制。"""

    total_commission = 0.0  # 累计手续费

    params = (
        ('stocklike', True),                     # 股票类型
        ('commtype', bt.CommInfoBase.COMM_PERC), # 按百分比(比例)计费
        ('percabs', True),                       # 比例使用绝对值表示
        
        # 默认佣金参数集中放在这里，便于页面参数覆盖或后续统一调整。
        ('commission', 0.0000854),     # 默认万 0.854
        ('min_comm', 5.0),             # 默认最低 5 元
    )

    def _getcommission(self, size, price, pseudoexec):
        """按成交金额计算手续费，并累计本次回测的总手续费。"""
        # 计算理论上的比例手续费（买卖总金额 * 费率）
        dt_comm = size * price * self.p.commission

        sxf = abs(dt_comm)
        
        # 对比最低 5 元的限制（注意：size 在卖出时为负数，故取绝对值）
        if abs(dt_comm) < self.p.min_comm:
            sxf = self.p.min_comm
        
        self.total_commission += abs(sxf)
        #print(f"交易金额: {size * price:.2f}, 手续费: {sxf:.2f}, 累计手续费: {self.total_commission:.2f}")
        return abs(sxf)

