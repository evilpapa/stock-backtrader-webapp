from src.strategy import MaStrategy

from .base_test import StrategyTest, run_back_trader


class MaStrategyTest(StrategyTest):
	"""均线策略测试。"""

	def test_ma(self):
		"""验证均线策略可在参数优化范围内完成回测。"""
		self.result = run_back_trader(self.cerebro, MaStrategy, maperiod=range(3, 31))
