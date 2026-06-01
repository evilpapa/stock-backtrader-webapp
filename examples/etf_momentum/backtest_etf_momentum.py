"""
ETF动量轮动策略回测脚本

包含:
1. 数据获取 (使用 xtdata)
2. 策略回测 (使用 backtrader)
3. 性能分析 (使用 empyrical-reloaded)
4. 可视化 (使用 matplotlib)

使用：
	uv run python examples/etf_momentum/backtest_etf_momentum.py
"""

import os
import sys
import logging
from datetime import datetime, timedelta

import backtrader as bt
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.gridspec import GridSpec
from tabulate import tabulate

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from charts import configure_matplotlib_chinese_font
from strategy.analyzer import CustomAnalyzer
from strategy.equal_weight import EqualWeightStrategy
from strategy.just_buy_hold import JustBuyHoldStrategy
from strategy.performance_calculator import PerformanceCalculator
from utils.colors import BLUE, YELLOW, colorize
from utils.xtdata_client import fetch_history_ohlcv, to_title_case_ohlcv


# ==================== 配置参数 ====================
INITIAL_CASH = 100000.0
COMMISSION = 0.025
MOMENTUM_WINDOW = 10
REBALANCE_DAYS = 20

# 回测时间段
BACKTEST_START = "2025-01-01"
BACKTEST_END = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# ETF代码
ETF_SYMBOLS = ["513100", "510300", "518880"]  # 纳指、沪深300、黄金
ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]

# 输出目录
OUTPUT_DIR = f'{project_root}/examples/etf_momentum/backtest_results'

configure_matplotlib_chinese_font()

logger = logging.getLogger(__name__)


def configure_logging(level=logging.INFO):
	"""配置脚本日志输出。"""
	logging.basicConfig(
		level=level,
		format="%(asctime)s [%(levelname)s] %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)


# ==================== Backtrader 策略 ====================
class EtfMomentumStrategy(bt.Strategy):
	"""
	ETF动量轮动策略
	"""

	params = (
		("momentum_window", 20),
		("rebalance_days", 1),
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
		self.rebalance_counter += 1
		if self.rebalance_counter < self.params.rebalance_days:
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
			positive_momentum = np.array(
				[adj_momentum_values[i] for i in positive_indices]
			)
			total_momentum = np.sum(positive_momentum)

			if total_momentum > 0:
				normalized_weights = positive_momentum / total_momentum
				for idx, weight in zip(positive_indices, normalized_weights):
					target_weights[idx] = weight

		# 执行再平衡
		self._rebalance_portfolio(target_weights)

		# 记录权重
		self.trade_log.append(
			{"date": self.datas[0].datetime.date(0), "weights": target_weights.copy()}
		)

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


# ==================== 主回测函数 ====================
def run_backtest(data_dict, symbols, names):
	"""
	运行回测

	Returns:
		tuple: (cerebro, results, trade_log)
	"""
	colorize("\n正在运行回测...", BLUE)

	# 创建Cerebro引擎
	cerebro = bt.Cerebro()

	# 添加数据源
	for symbol, name in zip(symbols, names):
		if symbol in data_dict:
			data = bt.feeds.PandasData(dataname=data_dict[symbol])
			cerebro.adddata(data, name=name)

	# 添加策略
	cerebro.addstrategy(
		EtfMomentumStrategy,
		momentum_window=MOMENTUM_WINDOW,
		rebalance_days=REBALANCE_DAYS,
	)

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
	colorize(f"初始资金: {cerebro.broker.getvalue():.2f}", YELLOW)
	results = cerebro.run()
	colorize(f"期末资金: {cerebro.broker.getvalue():.2f}", YELLOW)

	return cerebro, results[0]


# ==================== 基准策略回测 ====================
def run_benchmark_backtest(data_dict, benchmark_symbol, benchmark_name):
	"""运行基准策略（买入持有）"""

	cerebro = bt.Cerebro()

	logger.info("运行基准策略回测...")
	if benchmark_symbol in data_dict:
		data = bt.feeds.PandasData(dataname=data_dict[benchmark_symbol])
		cerebro.adddata(data, name=benchmark_name)
		logger.info("已添加数据: %s", benchmark_name)
	else:
		logger.error("找不到 %s 的数据", benchmark_symbol)
		return None

	cerebro.addstrategy(JustBuyHoldStrategy)
	cerebro.broker.setcash(INITIAL_CASH)
	cerebro.broker.setcommission(commission=COMMISSION)
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")

	logger.info("初始资金: %.2f", cerebro.broker.getvalue())
	results = cerebro.run()
	logger.info("期末资金: %.2f", cerebro.broker.getvalue())

	return results[0]


# ==================== 等权重组合回测 ====================
def run_equal_weight_backtest(data_dict, symbols, names):
	"""运行等权重组合策略"""

	cerebro = bt.Cerebro()

	logger.info("运行等权重组合回测...")
	data_count = 0
	for symbol, name in zip(symbols, names):
		if symbol in data_dict:
			data = bt.feeds.PandasData(dataname=data_dict[symbol])
			cerebro.adddata(data, name=name)
			data_count += 1
			logger.info("已添加数据: %s", name)

	if data_count == 0:
		logger.error("没有可用的数据")
		return None

	cerebro.addstrategy(EqualWeightStrategy)
	cerebro.broker.setcash(INITIAL_CASH)
	cerebro.broker.setcommission(commission=COMMISSION)
	cerebro.addanalyzer(CustomAnalyzer, _name="custom")

	logger.info("初始资金: %.2f", cerebro.broker.getvalue())
	results = cerebro.run()
	logger.info("期末资金: %.2f", cerebro.broker.getvalue())

	return results[0]


# ==================== 效能分析 ====================
def analyze_performance(strategy_result, benchmark_result, equal_weight_result, names):
	"""分析效能指标"""
	logger.info("正在计算效能指标...")

	# 提取收益率
	strategy_returns = pd.Series(strategy_result.analyzers.custom.returns)
	benchmark_returns = pd.Series(benchmark_result.analyzers.custom.returns)
	equal_returns = pd.Series(equal_weight_result.analyzers.custom.returns)

	calc = PerformanceCalculator()

	# 计算各策略的效能指标
	metrics = {
		"策略": ["动量策略", "沪深300ETF", "等权重组合"],
		"年化收益率": [
			calc.annualized_return(strategy_returns) * 100,
			calc.annualized_return(benchmark_returns) * 100,
			calc.annualized_return(equal_returns) * 100,
		],
		"年化波动率": [
			calc.annualized_volatility(strategy_returns) * 100,
			calc.annualized_volatility(benchmark_returns) * 100,
			calc.annualized_volatility(equal_returns) * 100,
		],
		"夏普比率": [
			calc.sharpe_ratio(strategy_returns),
			calc.sharpe_ratio(benchmark_returns),
			calc.sharpe_ratio(equal_returns),
		],
		"最大回撤": [
			calc.max_drawdown(strategy_returns) * 100,
			calc.max_drawdown(benchmark_returns) * 100,
			calc.max_drawdown(equal_returns) * 100,
		],
		"卡尔马比率": [
			calc.calmar_ratio(strategy_returns),
			calc.calmar_ratio(benchmark_returns),
			calc.calmar_ratio(equal_returns),
		],
		"索提诺比率": [
			calc.sortino_ratio(strategy_returns),
			calc.sortino_ratio(benchmark_returns),
			calc.sortino_ratio(equal_returns),
		],
		"胜率": [
			calc.win_rate(strategy_returns) * 100,
			calc.win_rate(benchmark_returns) * 100,
			calc.win_rate(equal_returns) * 100,
		],
		"正收益天数": [
			(strategy_returns > 0).sum(),
			(benchmark_returns > 0).sum(),
			(equal_returns > 0).sum(),
		],
		"总交易天数": [
			len(strategy_returns),
			len(benchmark_returns),
			len(equal_returns),
		],
	}

	df = pd.DataFrame(metrics)

	# 格式化输出
	df["年化收益率"] = df["年化收益率"].apply(lambda x: f"{x:.2f}%")
	df["年化波动率"] = df["年化波动率"].apply(lambda x: f"{x:.2f}%")
	df["夏普比率"] = df["夏普比率"].apply(lambda x: f"{x:.3f}")
	df["最大回撤"] = df["最大回撤"].apply(lambda x: f"{x:.2f}%")
	df["卡尔马比率"] = df["卡尔马比率"].apply(lambda x: f"{x:.3f}")
	df["索提诺比率"] = df["索提诺比率"].apply(lambda x: f"{x:.3f}")
	df["胜率"] = df["胜率"].apply(lambda x: f"{x:.2f}%")

	return df, strategy_returns, benchmark_returns, equal_returns


# ==================== 可视化 ====================
def plot_results(
	strategy_returns,
	benchmark_returns,
	equal_returns,
	strategy_dates,
	benchmark_dates,
	equal_dates,
	trade_log,
	names,
):
	"""绘制回测结果"""
	logger.info("正在生成图表...")

	# 计算累计收益率
	strategy_cum = (1 + strategy_returns).cumprod()
	benchmark_cum = (1 + benchmark_returns).cumprod()
	equal_cum = (1 + equal_returns).cumprod()

	calc = PerformanceCalculator()

	strategy_dd = calc.calc_drawdown(strategy_returns)
	benchmark_dd = calc.calc_drawdown(benchmark_returns)
	equal_dd = calc.calc_drawdown(equal_returns)

	# 创建日期索引
	strategy_dates_idx = pd.to_datetime(strategy_dates)
	benchmark_dates_idx = pd.to_datetime(benchmark_dates)
	equal_dates_idx = pd.to_datetime(equal_dates)

	# 颜色配置
	colors = {"动量策略": "#E41A1C", "沪深300ETF": "#377EB8", "等权重组合": "#4DAF4A"}

	# ========== 图1: 动量策略 vs 沪深300ETF ==========
	fig1 = plt.figure(figsize=(12, 8))
	gs1 = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

	# 累计收益率
	ax1 = fig1.add_subplot(gs1[0])
	ax1.plot(
		strategy_dates_idx,
		strategy_cum,
		label="动量策略",
		color=colors["动量策略"],
		linewidth=2,
	)
	ax1.plot(
		benchmark_dates_idx,
		benchmark_cum,
		label="沪深300ETF",
		color=colors["沪深300ETF"],
		linewidth=2,
	)
	ax1.set_ylabel("累计收益率", fontsize=12)
	ax1.set_title("动量策略 vs 沪深300ETF: 累计收益率", fontsize=14, fontweight="bold")
	ax1.legend(loc="upper left")
	ax1.grid(True, alpha=0.3)
	ax1.set_xticklabels([])

	# 回撤
	ax2 = fig1.add_subplot(gs1[1])
	ax2.fill_between(
		strategy_dates_idx,
		strategy_dd,
		0,
		label="动量策略",
		color=colors["动量策略"],
		alpha=0.3,
	)
	ax2.fill_between(
		benchmark_dates_idx,
		benchmark_dd,
		0,
		label="沪深300ETF",
		color=colors["沪深300ETF"],
		alpha=0.3,
	)
	ax2.set_xlabel("日期", fontsize=12)
	ax2.set_ylabel("回撤", fontsize=12)
	ax2.grid(True, alpha=0.3)
	ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

	plt.tight_layout()

	# ========== 图2: 动量策略 vs 等权重组合 ==========
	fig2 = plt.figure(figsize=(12, 8))
	gs2 = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

	ax3 = fig2.add_subplot(gs2[0])
	ax3.plot(
		strategy_dates_idx,
		strategy_cum,
		label="动量策略",
		color=colors["动量策略"],
		linewidth=2,
	)
	ax3.plot(
		equal_dates_idx,
		equal_cum,
		label="等权重组合",
		color=colors["等权重组合"],
		linewidth=2,
	)
	ax3.set_ylabel("累计收益率", fontsize=12)
	ax3.set_title("动量策略 vs 等权重组合: 累计收益率", fontsize=14, fontweight="bold")
	ax3.legend(loc="upper left")
	ax3.grid(True, alpha=0.3)
	ax3.set_xticklabels([])

	ax4 = fig2.add_subplot(gs2[1])
	ax4.fill_between(
		strategy_dates_idx,
		strategy_dd,
		0,
		label="动量策略",
		color=colors["动量策略"],
		alpha=0.3,
	)
	ax4.fill_between(
		equal_dates,
		equal_dd,
		0,
		label="等权重组合",
		color=colors["等权重组合"],
		alpha=0.3,
	)
	ax4.set_xlabel("日期", fontsize=12)
	ax4.set_ylabel("回撤", fontsize=12)
	ax4.grid(True, alpha=0.3)
	ax4.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

	plt.tight_layout()

	# ========== 图3: 权重分配 ==========
	if trade_log:
		fig3, ax5 = plt.subplots(figsize=(12, 6))

		# 提取权重数据
		weight_dates = [log["date"] for log in trade_log]
		weights_array = np.array([log["weights"] for log in trade_log])

		weight_dates_pd = pd.to_datetime(weight_dates)

		# 堆叠面积图
		ax5.stackplot(
			weight_dates_pd,
			weights_array[:, 0],
			weights_array[:, 1],
			weights_array[:, 2],
			labels=names,
			alpha=0.7,
			colors=["#E41A1C", "#377EB8", "#4DAF4A"],
		)

		ax5.set_xlabel("日期", fontsize=12)
		ax5.set_ylabel("权重", fontsize=12)
		ax5.set_title("动量策略: 每日权重分配", fontsize=14, fontweight="bold")
		ax5.legend(loc="upper left")
		ax5.grid(True, alpha=0.3)
		ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

		plt.tight_layout()
	else:
		fig3 = None

	return fig1, fig2, fig3


# ==================== 保存结果 ====================
def save_results(
	performance_df,
	trade_log,
	names,
	strategy_dates,
	benchmark_dates,
	equal_dates,
	strategy_returns,
	benchmark_returns,
	equal_returns,
	fig1,
	fig2,
	fig3,
):
	"""保存回测结果"""
	logger.info("正在保存结果到 %s...", OUTPUT_DIR)

	# 创建输出目录
	os.makedirs(OUTPUT_DIR, exist_ok=True)

	# 保存性能指标
	performance_df.to_csv(
		f"{OUTPUT_DIR}/performance_metrics.csv", index=False, encoding="utf-8-sig"
	)

	# 保存权重数据
	if trade_log:
		weights_df = pd.DataFrame(
			[
				{
					"Date": log["date"],
					names[0]: log["weights"][0],
					names[1]: log["weights"][1],
					names[2]: log["weights"][2],
					"权重合计": log["weights"].sum(),
				}
				for log in trade_log
			]
		)
		weights_df.to_csv(
			f"{OUTPUT_DIR}/daily_weights.csv", index=False, encoding="utf-8-sig"
		)

	# 保存收益率数据
	returns_df = pd.DataFrame(
		{
			"Date": strategy_dates,
			"动量策略": strategy_returns,
			"沪深300ETF": benchmark_returns,
			"等权重组合": equal_returns,
		}
	)
	returns_df.to_csv(
		f"{OUTPUT_DIR}/daily_returns.csv", index=False, encoding="utf-8-sig"
	)

	# 保存图表
	if fig1:
		fig1.savefig(
			f"{OUTPUT_DIR}/momentum_vs_benchmark.png", dpi=300, bbox_inches="tight"
		)
	if fig2:
		fig2.savefig(
			f"{OUTPUT_DIR}/momentum_vs_equal_weight.png", dpi=300, bbox_inches="tight"
		)
	if fig3:
		fig3.savefig(
			f"{OUTPUT_DIR}/daily_weights_plot.png", dpi=300, bbox_inches="tight"
		)

	logger.info("结果已保存到 %s/", OUTPUT_DIR)


# ==================== 主程序 ====================
def main():
	"""主程序"""
	configure_logging()
	logger.info("%s", "=" * 60)
	logger.info("ETF动量轮动策略回测 (Python版本)")
	logger.info("%s", "=" * 60)
	logger.info("回测期间: %s 至 %s", BACKTEST_START, BACKTEST_END)
	logger.info("ETF标的: %s", ", ".join(ETF_NAMES))
	logger.info("动量窗口: %s天", MOMENTUM_WINDOW)
	logger.info("再平衡频率: %s天", REBALANCE_DAYS)
	logger.info("初始资金: %s元", INITIAL_CASH)
	logger.info("%s", "=" * 60)

	# 1. 获取数据
	logger.info("正在从 xtdata 获取 ETF 历史数据...")
	data_feeds = {}

	for ticker in ETF_SYMBOLS:
		try:
			df_ticker = to_title_case_ohlcv(
				fetch_history_ohlcv(ticker, BACKTEST_START, BACKTEST_END)
			)
		except Exception as exc:
			logger.exception("数据获取失败: %s - %s", ticker, exc)
			continue

		df_ticker = df_ticker[["Open", "High", "Low", "Close", "Volume"]].dropna()
		if df_ticker.empty:
			logger.warning("数据清洗后为空: %s", ticker)
			continue
		data_feeds[ticker] = df_ticker
		logger.info("数据处理完成: %s, 共 %d 行", ticker, len(df_ticker))

	if len(data_feeds) < len(ETF_SYMBOLS):
		logger.warning("部分ETF数据获取失败，回测可能不完整")

	# 2. 运行动量策略回测
	cerebro, strategy_result = run_backtest(data_feeds, ETF_SYMBOLS, ETF_NAMES)

	# 3. 运行基准策略回测（沪深300）
	benchmark_result = run_benchmark_backtest(data_feeds, "510300", "沪深300ETF")

	# 4. 运行等权重组合回测
	equal_weight_result = run_equal_weight_backtest(data_feeds, ETF_SYMBOLS, ETF_NAMES)

	if benchmark_result is None or equal_weight_result is None:
		logger.error("基准策略或等权重策略回测失败，无法进行性能分析")
		return

	# 5. 效能分析
	performance_df, strategy_returns, benchmark_returns, equal_returns = (
		analyze_performance(
			strategy_result, benchmark_result, equal_weight_result, ETF_NAMES
		)
	)

	# 打印效能指标
	logger.info("%s", "=" * 60)
	logger.info("效能指标汇总")
	logger.info("%s", "=" * 60)
	logger.info("\n%s", tabulate(performance_df, headers='keys', tablefmt='grid', showindex=False))

	# 6. 可视化
	trade_log = strategy_result.trade_log
	strategy_dates = strategy_result.analyzers.custom.dates
	benchmark_dates = benchmark_result.analyzers.custom.dates
	equal_dates = equal_weight_result.analyzers.custom.dates

	fig1, fig2, fig3 = plot_results(
		strategy_returns,
		benchmark_returns,
		equal_returns,
		strategy_dates,
		benchmark_dates,
		equal_dates,
		trade_log,
		ETF_NAMES,
	)

	# 7. 保存结果
	save_results(
		performance_df,
		trade_log,
		ETF_NAMES,
		strategy_dates,
		benchmark_dates,
		equal_dates,
		strategy_returns,
		benchmark_returns,
		equal_returns,
		fig1,
		fig2,
		fig3,
	)

	logger.info("%s", "=" * 60)
	logger.info("回测完成！")
	logger.info("%s", "=" * 60)

	if os.getenv("SHOW_PLOTS") == "1":  # 弹窗图片
		plt.show()
	else:
		plt.close("all")


if __name__ == "__main__":
	main()
