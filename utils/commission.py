import backtrader as bt

class ChinaStockCommission(bt.CommInfoBase):

    total_commission = 0.0  # 累计手续费

    """
    自定义 A 股手续费模型：
    万 0.0875（即 0.0000875），最低 5 元
    """
    params = (
        ('stocklike', True),           # 股票类型
        ('commtype', bt.CommInfoBase.COMM_PERC), # 按百分比(比例)计费
        ('percabs', True),             # 比例使用绝对值表示
        
        # --- 在这里设置新的默认值 ---
        ('commission', 0.0000854),     # 默认万 0.854
        ('min_comm', 5.0),             # 默认最低 5 元
    )

    def _getcommission(self, size, price, pseudoexec):
        """
        重写计算手续费的核心方法
        """
        # 计算理论上的比例手续费（买卖总金额 * 费率）
        dt_comm = size * price * self.p.commission

        sxf = abs(dt_comm)
        
        # 对比最低 5 元的限制（注意：size 在卖出时为负数，故取绝对值）
        if abs(dt_comm) < self.p.min_comm:
            sxf = self.p.min_comm
        
        self.total_commission += abs(sxf)
        print(f"交易金额: {size * price:.2f}, 手续费: {sxf:.2f}, 累计手续费: {self.total_commission:.2f}")
        return abs(sxf)

