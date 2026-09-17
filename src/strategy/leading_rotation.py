"""龙头动量轮动策略 (Python版本)。"""

from .rotation_base import RotationStrategyBase


class LeadingRotationStrategy(RotationStrategyBase):
	"""龙头标的风险调整动量轮动策略。"""

	_name = "LeadingRotation"
