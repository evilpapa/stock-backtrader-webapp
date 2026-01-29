import numpy as np

# 尝试导入empyrical，如果没有安装则使用自定义计算
try:
	import empyrical as ep
	HAS_EMPYRICAL = True
except ImportError:
	HAS_EMPYRICAL = False
	print("警告: empyrical 未安装，将使用自定义性能计算")


# ==================== 性能指标计算函数 ====================
class PerformanceCalculator:
	"""性能指标计算器"""

	@staticmethod
	def annualized_return(returns):
		"""年化收益率"""
		if HAS_EMPYRICAL:
			return ep.annual_return(returns)
		else:
			# 简单年化计算
			total_return = (1 + returns).prod() - 1
			days = len(returns)
			years = days / 252.0
			return (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

	@staticmethod
	def annualized_volatility(returns):
		"""年化波动率"""
		if HAS_EMPYRICAL:
			return ep.annual_volatility(returns)
		else:
			return returns.std() * np.sqrt(252)

	@staticmethod
	def sharpe_ratio(returns, risk_free=0.0):
		"""夏普比率"""
		if HAS_EMPYRICAL:
			return ep.sharpe_ratio(returns, risk_free=risk_free)
		else:
			excess_returns = returns - risk_free / 252
			if excess_returns.std() == 0:
				return 0
			return np.sqrt(252) * excess_returns.mean() / excess_returns.std()

	@staticmethod
	def max_drawdown(returns):
		"""最大回撤"""
		if HAS_EMPYRICAL:
			return ep.max_drawdown(returns)
		else:
			cum_returns = (1 + returns).cumprod()
			running_max = cum_returns.expanding().max()
			drawdown = (cum_returns - running_max) / running_max
			return drawdown.min()

	@staticmethod
	def calmar_ratio(returns):
		"""卡尔马比率 = 年化收益率 / 最大回撤"""
		annual_return = PerformanceCalculator.annualized_return(returns)
		max_dd = abs(PerformanceCalculator.max_drawdown(returns))
		return annual_return / max_dd if max_dd != 0 else 0

	@staticmethod
	def sortino_ratio(returns, required_return=0.0):
		"""索提诺比率"""
		if HAS_EMPYRICAL:
			return ep.sortino_ratio(returns, required_return=required_return)
		else:
			excess_returns = returns - required_return / 252
			downside_returns = excess_returns[excess_returns < 0]
			if len(downside_returns) == 0 or downside_returns.std() == 0:
				return 0
			return np.sqrt(252) * excess_returns.mean() / downside_returns.std()

	@staticmethod
	def win_rate(returns):
		"""胜率（正收益天数占比）"""
		return (returns > 0).sum() / len(returns)

	@staticmethod
	def calc_drawdown(returns):
		"""计算每个时间点的回撤"""
		cum = (1 + returns).cumprod()
		running_max = cum.expanding().max()
		drawdown = (cum - running_max) / running_max
		return drawdown

