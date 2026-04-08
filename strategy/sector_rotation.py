"""
行业动量轮动策略 (Python版本)

策略逻辑与龙头轮动一致：
1. 计算 N 日平均收益率作为原始动量
2. 计算 N 日收益率标准差作为波动率
3. 仅在原始动量为正的行业 ETF 中，按风险调整动量排序
4. 选择前 L 个标的，并按风险调整动量归一化分配权重
5. 每 K 个交易日调仓一次
"""

from .leading_rotation import LeadingRotationStrategy


class SectorRotationStrategy(LeadingRotationStrategy):
	_name = "SectorRotation"
