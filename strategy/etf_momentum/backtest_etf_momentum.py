"""
ETF动量轮动策略完整回测脚本 (Python版本)

这是R语言 strategy.r 的Python完整实现，包含:
1. 数据获取 (使用 yfinance)
2. 策略回测 (使用 backtrader)
3. 性能分析 (使用 empyrical)
4. 可视化 (使用 matplotlib)

依赖包映射:
R包                    → Python包
-------------------------------------------------
quantmod              → yfinance (数据获取)
PerformanceAnalytics  → empyrical (性能分析)
dplyr/tidyr           → pandas (数据处理)
ggplot2/cowplot       → matplotlib (可视化)

使用方法:
	python strategy/etf_momentum/backtest_etf_momentum.py
"""

import os
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import yfinance as yf
import backtrader as bt
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from pathlib import Path

# 尝试导入empyrical，如果没有安装则使用自定义计算
try:
	import empyrical as ep
	HAS_EMPYRICAL = True
except ImportError:
	HAS_EMPYRICAL = False
	print("警告: empyrical 未安装，将使用自定义性能计算")

#===========颜色设置================
# 常用颜色代码（前景色）
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'
WHITE = '\033[97m'
RESET = '\033[0m'  # 重置

# ==================== 配置参数 ====================
# 回测时间段
BACKTEST_START = "2024-01-01"
BACKTEST_END = datetime.now().strftime("%Y-%m-%d")

# ETF代码 (Yahoo Finance格式)
ETF_SYMBOLS = ["513100.SS", "510300.SS", "518880.SS"]  # 纳指、沪深300、黄金
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]

# 策略参数
MOMENTUM_WINDOW = 20  # 动量计算窗口
INITIAL_CASH = 100000.0  # 初始资金
COMMISSION = 0.001  # 手续费率 0.1%

# 输出目录
OUTPUT_DIR = "momentum_strategy_backtest"
DATA_CACHE_DIR = "data_cache"  # 数据缓存目录


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


# ==================== 数据获取 ====================
def fetch_etf_data(symbols, start_date, end_date):
	"""
	从Yahoo Finance获取ETF数据，支持本地缓存

	优先使用本地缓存文件，如果不存在则从网络下载并保存到本地。
	缓存文件命名格式: {symbol}_{start_date}_{end_date}.pkl

	Args:
		symbols: ETF代码列表
		start_date: 开始日期
		end_date: 结束日期

	Returns:
		dict: {symbol: DataFrame}
	"""
	print("正在获取ETF数据...")

	# 确保缓存目录存在
	data_dir = Path(__file__).resolve().parent.parent.parent / DATA_CACHE_DIR
	os.makedirs(data_dir, exist_ok=True)

	data_dict = {}

	for symbol in symbols:
		# 生成缓存文件名（去除特殊字符）
		safe_symbol = symbol.replace(".", "_")
		cache_filename = f"{safe_symbol}_{start_date}_{end_date}.pkl"
		cache_filepath = os.path.join(data_dir, cache_filename)
		print(cache_filepath)

		# 检查缓存文件是否存在
		if os.path.exists(cache_filepath):
			try:
				df = pd.read_pickle(cache_filepath)
				if not df.empty:
					data_dict[symbol] = df
					print(f"  ✓ {symbol}: {len(df)} 条数据 (来自缓存)")
					continue
			except Exception as e:
				print(f"  ⚠ {symbol}: 缓存文件读取失败 ({e})，将重新下载")

		# 从网络下载数据
		try:
			df = yf.download(symbol, start=start_date, end=end_date, progress=False)
			if not df.empty:
				data_dict[symbol] = df
				# 保存到缓存
				try:
					df.to_pickle(cache_filepath)
					print(f"  ✓ {symbol}: {len(df)} 条数据 (已下载并缓存)")
				except Exception as e:
					print(f"  ✓ {symbol}: {len(df)} 条数据 (已下载，缓存保存失败: {e})")
			else:
				print(f"  ✗ {symbol}: 无数据")
		except Exception as e:
			print(f"  ✗ {symbol}: 获取失败 - {e}")

	return data_dict


# ==================== Backtrader策略 ====================
class EtfMomentumStrategy(bt.Strategy):
	"""ETF动量轮动策略"""

	params = (
		("momentum_window", 20),
		("printlog", False),
	)

	def __init__(self):
		# 为每个数据源计算收益率和指标
		self.returns = []
		self.momentum = []
		self.volatility = []

		for data in self.datas:
			ret = bt.indicators.PctChange(data.close, period=1)
			self.returns.append(ret)

			momentum = bt.indicators.SimpleMovingAverage(
				ret, period=self.params.momentum_window
			)
			self.momentum.append(momentum)

			volatility = bt.indicators.StandardDeviation(
				ret, period=self.params.momentum_window
			)
			self.volatility.append(volatility)

		self.rebalance_counter = 0
		self.trade_log = []  # 用于记录交易日志

	def next(self):
		"""每个交易日执行"""
		# 每日再平衡
		self.rebalance_counter += 1
		if self.rebalance_counter < 1:  # 每日
			return

		self.rebalance_counter = 0

		# 检查数据充足性
		if len(self.datas[0]) < self.params.momentum_window:
			return

		# 计算风险调整动量
		adj_momentum_values = []
		for i in range(len(self.datas)):
			if len(self.momentum[i]) > 0 and len(self.volatility[i]) > 0:
				mom = self.momentum[i][0]
				vol = self.volatility[i][0]
				adj_mom = mom / vol if vol > 1e-8 else 0.0
				adj_momentum_values.append(adj_mom)
			else:
				adj_momentum_values.append(0.0)

		# 筛选正动量ETF并计算权重
		positive_indices = [i for i, v in enumerate(adj_momentum_values) if v > 0]
		target_weights = np.zeros(len(self.datas))

		if len(positive_indices) > 0:
			positive_momentum = np.array([adj_momentum_values[i] for i in positive_indices])
			total_momentum = np.sum(positive_momentum)

			if total_momentum > 0:
				normalized_weights = positive_momentum / total_momentum
				for idx, weight in zip(positive_indices, normalized_weights):
					target_weights[idx] = weight

		# 执行再平衡
		self._rebalance_portfolio(target_weights)

		# 记录权重
		self.trade_log.append({
			'date': self.datas[0].datetime.date(0),
			'weights': target_weights.copy()
		})

	def _rebalance_portfolio(self, target_weights):
		"""根据目标权重调整持仓"""
		total_value = self.broker.getvalue()

		for i, data in enumerate(self.datas):
			target_weight = target_weights[i]
			target_value = total_value * target_weight

			current_position = self.getposition(data).size
			current_price = data.close[0]
			current_value = current_position * current_price

			diff_value = target_value - current_value
			threshold = total_value * 0.01

			if abs(diff_value) > threshold:
				size = int(diff_value / current_price)
				if size > 0:
					self.buy(data=data, size=size)
				elif size < 0:
					self.sell(data=data, size=-size)


# ==================== 回测分析器 ====================
class CustomAnalyzer(bt.Analyzer):
	"""自定义分析器，记录每日收益率"""

	def __init__(self):
		self.returns = []
		self.dates = []
		self.values = []

	def next(self):
		self.dates.append(self.datas[0].datetime.date(0))
		self.values.append(self.strategy.broker.getvalue())

	def stop(self):
		# 计算收益率
		values_array = np.array(self.values)
		returns_array = np.diff(values_array) / values_array[:-1]

		self.returns = returns_array
		self.dates = self.dates[1:]  # 去掉第一个日期


# ==================== 主回测函数 ====================
def run_backtest(data_dict, symbols, names):
	"""
	运行回测

	Returns:
		tuple: (cerebro, results, trade_log)
	"""
	print("\n正在运行回测...")

	# 创建Cerebro引擎
	cerebro = bt.Cerebro()

	# 添加数据源
	for symbol, name in zip(symbols, names):
		if symbol in data_dict:
			data = bt.feeds.PandasData(dataname=data_dict[symbol])
			cerebro.adddata(data, name=name)

	# 添加策略
	cerebro.addstrategy(EtfMomentumStrategy, momentum_window=MOMENTUM_WINDOW)

	# 设置初始资金
	cerebro.broker.setcash(INITIAL_CASH)

	# 设置手续费
	cerebro.broker.setcommission(commission=COMMISSION)

	# 添加分析器
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")
	cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
	cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
	cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

	# 运行回测
	print(f"初始资金: {cerebro.broker.getvalue():.2f}")
	results = cerebro.run()
	print(f"期末资金: {cerebro.broker.getvalue():.2f}")


	return cerebro, results[0]


# ==================== 基准策略回测 ====================
def run_benchmark_backtest(data_dict, benchmark_symbol, benchmark_name):
	"""运行基准策略（买入持有）"""

	class BuyHoldStrategy(bt.Strategy):
		"""买入持有策略"""
		def __init__(self):
			self.bought = False

		def next(self):
			if not self.bought:
				# 使用所有资金买入
				cash = self.broker.getcash()
				size = int(cash / self.datas[0].close[0])
				self.buy(size=size)
				self.bought = True

	cerebro = bt.Cerebro()

	print(RED + "==> 运行基准策略回测..." + RESET)
	if benchmark_symbol in data_dict:
		data = bt.feeds.PandasData(dataname=data_dict[benchmark_symbol])
		cerebro.adddata(data, name=benchmark_name)

	cerebro.addstrategy(BuyHoldStrategy)
	cerebro.broker.setcash(INITIAL_CASH)
	cerebro.broker.setcommission(commission=COMMISSION)
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")

	results = cerebro.run()
	return results[0]


# ==================== 性能分析 ====================
def analyze_performance(strategy_result, benchmark_result, equal_weight_result, names):
	"""分析性能指标"""
	print("\n正在计算性能指标...")

	# 提取收益率
	strategy_returns = pd.Series(strategy_result.analyzers.custom.returns)
	benchmark_returns = pd.Series(benchmark_result.analyzers.custom.returns)
	equal_returns = pd.Series(equal_weight_result.analyzers.custom.returns)

	calc = PerformanceCalculator()

	# 计算各策略的性能指标
	metrics = {
		'策略': ['动量策略', '沪深300ETF', '等权重组合'],
		'年化收益率': [
			calc.annualized_return(strategy_returns) * 100,
			calc.annualized_return(benchmark_returns) * 100,
			calc.annualized_return(equal_returns) * 100
		],
		'年化波动率': [
			calc.annualized_volatility(strategy_returns) * 100,
			calc.annualized_volatility(benchmark_returns) * 100,
			calc.annualized_volatility(equal_returns) * 100
		],
		'夏普比率': [
			calc.sharpe_ratio(strategy_returns),
			calc.sharpe_ratio(benchmark_returns),
			calc.sharpe_ratio(equal_returns)
		],
		'最大回撤': [
			calc.max_drawdown(strategy_returns) * 100,
			calc.max_drawdown(benchmark_returns) * 100,
			calc.max_drawdown(equal_returns) * 100
		],
		'卡尔马比率': [
			calc.calmar_ratio(strategy_returns),
			calc.calmar_ratio(benchmark_returns),
			calc.calmar_ratio(equal_returns)
		],
		'索提诺比率': [
			calc.sortino_ratio(strategy_returns),
			calc.sortino_ratio(benchmark_returns),
			calc.sortino_ratio(equal_returns)
		],
		'胜率': [
			calc.win_rate(strategy_returns) * 100,
			calc.win_rate(benchmark_returns) * 100,
			calc.win_rate(equal_returns) * 100
		],
		'正收益天数': [
			(strategy_returns > 0).sum(),
			(benchmark_returns > 0).sum(),
			(equal_returns > 0).sum()
		],
		'总交易天数': [
			len(strategy_returns),
			len(benchmark_returns),
			len(equal_returns)
		]
	}

	df = pd.DataFrame(metrics)

	# 格式化输出
	df['年化收益率'] = df['年化收益率'].apply(lambda x: f"{x:.2f}%")
	df['年化波动率'] = df['年化波动率'].apply(lambda x: f"{x:.2f}%")
	df['夏普比率'] = df['夏普比率'].apply(lambda x: f"{x:.3f}")
	df['最大回撤'] = df['最大回撤'].apply(lambda x: f"{x:.2f}%")
	df['卡尔马比率'] = df['卡尔马比率'].apply(lambda x: f"{x:.3f}")
	df['索提诺比率'] = df['索提诺比率'].apply(lambda x: f"{x:.3f}")
	df['胜率'] = df['胜率'].apply(lambda x: f"{x:.2f}%")

	return df, strategy_returns, benchmark_returns, equal_returns


# ==================== 等权重组合回测 ====================
def run_equal_weight_backtest(data_dict, symbols, names):
	"""运行等权重组合策略"""

	class EqualWeightStrategy(bt.Strategy):
		"""等权重组合策略"""
		def __init__(self):
			self.rebalance_counter = 0
			self.bought = False

		def next(self):
			if not self.bought:
				# 初始买入：等权重分配
				total_value = self.broker.getvalue()
				for data in self.datas:
					target_value = total_value / len(self.datas)
					size = int(target_value / data.close[0])
					self.buy(data=data, size=size)
				self.bought = True

	cerebro = bt.Cerebro()

	for symbol, name in zip(symbols, names):
		if symbol in data_dict:
			data = bt.feeds.PandasData(dataname=data_dict[symbol])
			cerebro.adddata(data, name=name)

	cerebro.addstrategy(EqualWeightStrategy)
	cerebro.broker.setcash(INITIAL_CASH)
	cerebro.broker.setcommission(commission=COMMISSION)
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")

	results = cerebro.run()
	return results[0]


# ==================== 可视化 ====================
def plot_results(strategy_returns, benchmark_returns, equal_returns, 
				trade_log, dates, names):
	"""绘制回测结果"""
	print("\n正在生成图表...")

	# 计算累计收益率
	strategy_cum = (1 + strategy_returns).cumprod()
	benchmark_cum = (1 + benchmark_returns).cumprod()
	equal_cum = (1 + equal_returns).cumprod()

	# 计算回撤
	def calc_drawdown(returns):
		cum = (1 + returns).cumprod()
		running_max = cum.expanding().max()
		drawdown = (cum - running_max) / running_max
		return drawdown

	strategy_dd = calc_drawdown(strategy_returns)
	benchmark_dd = calc_drawdown(benchmark_returns)
	equal_dd = calc_drawdown(equal_returns)

	# 创建日期索引
	dates_index = pd.to_datetime(dates)

	# 颜色配置
	colors = {
		'动量策略': '#E41A1C',
		'沪深300ETF': '#377EB8',
		'等权重组合': '#4DAF4A'
	}

	# ========== 图1: 动量策略 vs 沪深300ETF ==========
	fig1 = plt.figure(figsize=(12, 8))
	gs1 = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

	# 累计收益率
	ax1 = fig1.add_subplot(gs1[0])
	ax1.plot(dates_index, strategy_cum, label='动量策略',
			color=colors['动量策略'], linewidth=2)
	ax1.plot(dates_index, benchmark_cum, label='沪深300ETF',
			color=colors['沪深300ETF'], linewidth=2)
	ax1.set_ylabel('累计收益率', fontsize=12)
	ax1.set_title('动量策略 vs 沪深300ETF: 累计收益率', fontsize=14, fontweight='bold')
	ax1.legend(loc='upper left')
	ax1.grid(True, alpha=0.3)
	ax1.set_xticklabels([])

	# 回撤
	ax2 = fig1.add_subplot(gs1[1])
	ax2.fill_between(dates_index, strategy_dd, 0,
					label='动量策略', color=colors['动量策略'], alpha=0.3)
	ax2.fill_between(dates_index, benchmark_dd, 0,
					label='沪深300ETF', color=colors['沪深300ETF'], alpha=0.3)
	ax2.set_xlabel('日期', fontsize=12)
	ax2.set_ylabel('回撤', fontsize=12)
	ax2.grid(True, alpha=0.3)
	ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

	plt.tight_layout()

	# ========== 图2: 动量策略 vs 等权重组合 ==========
	fig2 = plt.figure(figsize=(12, 8))
	gs2 = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

	ax3 = fig2.add_subplot(gs2[0])
	ax3.plot(dates_index, strategy_cum, label='动量策略',
			color=colors['动量策略'], linewidth=2)
	ax3.plot(dates_index, equal_cum, label='等权重组合',
			color=colors['等权重组合'], linewidth=2)
	ax3.set_ylabel('累计收益率', fontsize=12)
	ax3.set_title('动量策略 vs 等权重组合: 累计收益率', fontsize=14, fontweight='bold')
	ax3.legend(loc='upper left')
	ax3.grid(True, alpha=0.3)
	ax3.set_xticklabels([])

	ax4 = fig2.add_subplot(gs2[1])
	ax4.fill_between(dates_index, strategy_dd, 0,
					label='动量策略', color=colors['动量策略'], alpha=0.3)
	ax4.fill_between(dates_index, equal_dd, 0,
					label='等权重组合', color=colors['等权重组合'], alpha=0.3)
	ax4.set_xlabel('日期', fontsize=12)
	ax4.set_ylabel('回撤', fontsize=12)
	ax4.grid(True, alpha=0.3)
	ax4.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

	plt.tight_layout()

	# ========== 图3: 权重分配 ==========
	if trade_log:
		fig3, ax5 = plt.subplots(figsize=(12, 6))

		# 提取权重数据
		weight_dates = [log['date'] for log in trade_log]
		weights_array = np.array([log['weights'] for log in trade_log])

		weight_dates_pd = pd.to_datetime(weight_dates)

		# 堆叠面积图
		ax5.stackplot(weight_dates_pd,
					 weights_array[:, 0],
					 weights_array[:, 1],
					 weights_array[:, 2],
					 labels=names,
					 alpha=0.7,
					 colors=['#E41A1C', '#377EB8', '#4DAF4A'])

		ax5.set_xlabel('日期', fontsize=12)
		ax5.set_ylabel('权重', fontsize=12)
		ax5.set_title('动量策略: 每日权重分配', fontsize=14, fontweight='bold')
		ax5.legend(loc='upper left')
		ax5.grid(True, alpha=0.3)
		ax5.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

		plt.tight_layout()
	else:
		fig3 = None

	return fig1, fig2, fig3


# ==================== 保存结果 ====================
def save_results(performance_df, trade_log, dates, names, 
				strategy_returns, benchmark_returns, equal_returns,
				fig1, fig2, fig3):
	"""保存回测结果"""
	print(f"\n正在保存结果到 {OUTPUT_DIR}...")

	# 创建输出目录
	os.makedirs(OUTPUT_DIR, exist_ok=True)

	# 保存性能指标
	performance_df.to_csv(f"{OUTPUT_DIR}/performance_metrics.csv",
						 index=False, encoding='utf-8-sig')

	# 保存权重数据
	if trade_log:
		weights_df = pd.DataFrame([
			{
				'Date': log['date'],
				names[0]: log['weights'][0],
				names[1]: log['weights'][1],
				names[2]: log['weights'][2],
				'权重合计': log['weights'].sum()
			}
			for log in trade_log
		])
		weights_df.to_csv(f"{OUTPUT_DIR}/daily_weights.csv",
						 index=False, encoding='utf-8-sig')

	# 保存收益率数据
	returns_df = pd.DataFrame({
		'Date': dates,
		'动量策略': strategy_returns,
		'沪深300ETF': benchmark_returns,
		'等权重组合': equal_returns
	})
	returns_df.to_csv(f"{OUTPUT_DIR}/daily_returns.csv",
					 index=False, encoding='utf-8-sig')

	# 保存图表
	if fig1:
		fig1.savefig(f"{OUTPUT_DIR}/momentum_vs_benchmark.png",
					dpi=300, bbox_inches='tight')
	if fig2:
		fig2.savefig(f"{OUTPUT_DIR}/momentum_vs_equal_weight.png",
					dpi=300, bbox_inches='tight')
	if fig3:
		fig3.savefig(f"{OUTPUT_DIR}/daily_weights_plot.png",
					dpi=300, bbox_inches='tight')

	print(f"✓ 结果已保存到 {OUTPUT_DIR}/")


# ==================== 主程序 ====================
def main():
	"""主程序"""
	print("=" * 60)
	print("ETF动量轮动策略回测 (Python版本)")
	print("=" * 60)
	print(f"回测期间: {BACKTEST_START} 至 {BACKTEST_END}")
	print(f"ETF标的: {', '.join(ETF_NAMES)}")
	print(f"动量窗口: {MOMENTUM_WINDOW}天")
	print(f"初始资金: {INITIAL_CASH:,.0f}元")
	print("=" * 60)

	# 1. 获取数据
	data_dict = fetch_etf_data(ETF_SYMBOLS, BACKTEST_START, BACKTEST_END)
	data_feeds = {}

	for ticker in ETF_SYMBOLS:
		if ticker in data_dict:
			df = data_dict[ticker]
			df_ticker = df.xs(ticker, level=1, axis=1)
			df_ticker = df_ticker[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
			data_feeds[ticker] = df_ticker

	if len(data_feeds) < len(ETF_SYMBOLS):
		print("\n警告: 部分ETF数据获取失败，回测可能不完整")

	# 2. 运行动量策略回测
	cerebro, strategy_result = run_backtest(data_feeds, ETF_SYMBOLS, ETF_NAMES)

	# 3. 运行基准策略回测（沪深300）
	benchmark_result = run_benchmark_backtest(
		data_feeds, "510300.SS", "沪深300ETF"
	)

	# 4. 运行等权重组合回测
	equal_weight_result = run_equal_weight_backtest(
		data_feeds, ETF_SYMBOLS, ETF_NAMES
	)

	# 5. 性能分析
	performance_df, strategy_returns, benchmark_returns, equal_returns = \
		analyze_performance(strategy_result, benchmark_result,
						  equal_weight_result, ETF_NAMES)

	# 打印性能指标
	print("\n" + "=" * 60)
	print("性能指标汇总")
	print("=" * 60)
	print(performance_df.to_string(index=False))

	# 6. 可视化
	trade_log = strategy_result.strategy.trade_log
	dates = strategy_result.analyzers.custom.dates

	fig1, fig2, fig3 = plot_results(
		strategy_returns, benchmark_returns, equal_returns,
		trade_log, dates, ETF_NAMES
	)

	# 7. 保存结果
	save_results(performance_df, trade_log, dates, ETF_NAMES,
				strategy_returns, benchmark_returns, equal_returns,
				fig1, fig2, fig3)

	print("\n" + "=" * 60)
	print("回测完成！")
	print("=" * 60)

	# 显示图表
	plt.show()


if __name__ == "__main__":
	main()
