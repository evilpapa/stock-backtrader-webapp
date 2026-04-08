"""龙头动量轮动策略 (Python版本)。"""

from .rotation_base import RotationStrategyBase


class LeadingRotationStrategy(RotationStrategyBase):
	_name = "LeadingRotation"
