from src.strategy import MaCrossStrategy

from .base_test import StrategyTest, run_back_trader


class MaCrossStrategyTest(StrategyTest):
	"""双均线交叉策略测试。"""

	def test_ma(self):
		"""验证双均线交叉策略可在快慢线参数组合下完成回测。"""
		self.result = run_back_trader(
			self.cerebro,
			MaCrossStrategy,
			fast_length=range(1, 11, 5),
			slow_length=range(25, 35, 5),
		)
