import marimo

__generated_with = "0.19.6"
app = marimo.App()


@app.cell
def _():
    import os
    import sys
    from datetime import datetime, timedelta
    import numpy as np
    import pandas as pd
    import backtrader as bt
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.gridspec import GridSpec
    from utils.fetch_data import fetch_etf_data
    from utils.colors import RED, GREEN, GREEN, BLUE, MAGENTA, CYAN, RESET
    from strategy.performance_calculator import PerformanceCalculator
    from strategy.etf_momentum_backtrader import EtfMomentumSBacktrader
    from strategy.just_buy_hold import JustBuyHoldStrategy
    from strategy.equal_weight import EqualWeightStrategy
    from strategy.analyzer import CustomAnalyzer
    return (
        BLUE,
        CYAN,
        CustomAnalyzer,
        EqualWeightStrategy,
        EtfMomentumSBacktrader,
        GREEN,
        GridSpec,
        PerformanceCalculator,
        RED,
        RESET,
        bt,
        fetch_etf_data,
        mdates,
        np,
        os,
        pd,
        plt,
    )


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(fetch_etf_data, pd):
    # ==================== 配置参数 ====================
    # 回测时间段
    BACKTEST_START = "2024-01-01"
    BACKTEST_END = "2026-01-26"
    # BACKTEST_END = datetime.now().strftime("%Y-%m-%d")

    # ETF代码 (Yahoo Finance格式)
    ETF_SYMBOLS = ["513100.SS", "510300.SS", "518880.SS"]  # 纳指、沪深300、黄金
    ETF_NAMES = ["纳指ETF", "沪深300ETF", "黄金ETF"]

    # 策略参数
    MOMENTUM_WINDOW = 20  # 动量计算窗口
    INITIAL_CASH = 100000.0  # 初始资金
    COMMISSION = 0.001  # 手续费率 0.1%

    # 输出目录
    OUTPUT_DIR = "datas/etf_momentum/backtest_results"


    print("=" * 60)
    print("ETF动量轮动策略回测 (Python版本)")
    print("=" * 60)
    print(f"回测期间: {BACKTEST_START} 至 {BACKTEST_END}")
    print(f"ETF标的: {', '.join(ETF_NAMES)}")
    print(f"动量窗口: {MOMENTUM_WINDOW}天")
    print(f"初始资金: {INITIAL_CASH:,.0f}元")
    print("=" * 60)

    # 1. 获取数据
    data_dict = fetch_etf_data(ETF_SYMBOLS, BACKTEST_START, BACKTEST_END, strategy_name="etf_momentum")
    data_feeds = {}

    # yfinance 下载的数据稍微进行转换
    for ticker in ETF_SYMBOLS:
    	if ticker in data_dict:
    		df = data_dict[ticker]
		
    		# 检查是否是多索引（批量下载）还是单索引（单个下载）
    		if isinstance(df.columns, pd.MultiIndex):
    			# 多索引：需要提取对应ticker的数据
    			df_ticker = df.xs(ticker, level=1, axis=1)
    		else:
    			# 单索引：直接使用
    			df_ticker = df
    		# 确保列名正确
    		if 'Open' in df_ticker.columns:
    			df_ticker = df_ticker[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()
    			data_feeds[ticker] = df_ticker
    			print(f"  ✓ 数据处理完成: {ticker}, 共 {len(df_ticker)} 行")
    		else:
    			print(f"  ✗ 数据列名不匹配: {ticker}, 列名: {df_ticker.columns.tolist()}")

    if len(data_feeds) < len(ETF_SYMBOLS):
    	print("\n警告: 部分ETF数据获取失败，回测可能不完整")

    print(data_feeds)
    return (
        COMMISSION,
        ETF_NAMES,
        ETF_SYMBOLS,
        INITIAL_CASH,
        MOMENTUM_WINDOW,
        OUTPUT_DIR,
        data_feeds,
    )


@app.cell
def _(bt, np):
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


    return


@app.cell
def _(mo):
    mo.md("""
    # 主回测函数
    """)
    return


@app.cell
def _(
    BLUE,
    COMMISSION,
    CustomAnalyzer,
    ETF_NAMES,
    ETF_SYMBOLS,
    EtfMomentumSBacktrader,
    GREEN,
    INITIAL_CASH,
    MOMENTUM_WINDOW,
    RESET,
    bt,
    data_feeds,
):
    # ==================== 主回测函数 ====================
    def run_backtest(data_dict, symbols, names):
    	"""
    	运行回测

    	Returns:
    		tuple: (cerebro, results, trade_log)
    	"""
    	print(BLUE + "\n正在运行回测..." + RESET)

    	# 创建Cerebro引擎
    	cerebro = bt.Cerebro()

    	# 添加数据源
    	for symbol, name in zip(symbols, names):
    		if symbol in data_dict:
    			data = bt.feeds.PandasData(dataname=data_dict[symbol])
    			cerebro.adddata(data, name=name)

    	# 添加策略
    	cerebro.addstrategy(EtfMomentumSBacktrader, momentum_window=MOMENTUM_WINDOW)

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
    	print(GREEN + f"初始资金: {cerebro.broker.getvalue():.2f}" + RESET)
    	results = cerebro.run()
    	print(GREEN + f"期末资金: {cerebro.broker.getvalue():.2f}" + RESET)

    	return cerebro, results[0]


    cerebro, strategy_result = run_backtest(data_feeds, ETF_SYMBOLS, ETF_NAMES)
    return (strategy_result,)


@app.cell
def _(mo):
    mo.md(r"""
    # 基准策略回测
    """)
    return


@app.cell
def _(
    COMMISSION,
    CYAN,
    CustomAnalyzer,
    INITIAL_CASH,
    RED,
    RESET,
    bt,
    data_feeds,
):
    # ==================== 基准策略: 买入持有 ====================
    class BuyHoldStrategy(bt.Strategy):
        """买入持有策略"""
    
        def __init__(self):
            self.order = None  # 跟踪订单状态
            self.bought = False
    
        def notify_order(self, order):
            """订单状态通知"""
            if order.status in [order.Completed]:
                if order.isbuy():
                    self.log(f'买入执行, 价格: {order.executed.price:.2f}, '
                            f'数量: {order.executed.size:.2f}, '
                            f'手续费: {order.executed.comm:.2f}')
                    self.bought = True
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.log(f'订单被取消/拒绝: {order.status}')
        
            self.order = None
    
        def next(self):
            # 避免重复下单
            if self.order:
                return
        
            # 只在未买入时执行
            if not self.bought:
                # 获取当前可用资金
                cash = self.broker.getcash()
                price = self.datas[0].close[0]
            
                # 计算可买入数量（预留1%资金用于手续费）
                size = int((cash * 0.99) / price)
            
                if size > 0:
                    self.order = self.buy(size=size)
                    self.log(f'提交买单, 价格: {price:.2f}, 数量: {size}')
                else:
                    self.log(f'资金不足，无法买入 (现金: {cash:.2f}, 价格: {price:.2f})')
    
        def log(self, txt, dt=None):
            """日志函数"""
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')


    # ==================== 基准策略回测 ====================
    def run_benchmark_backtest(data_dict, benchmark_symbol, benchmark_name):
    	"""运行基准策略（买入持有）"""

    	cerebro = bt.Cerebro()

    	print(RED + "\n==> 运行基准策略回测..." + RESET)
    	if benchmark_symbol in data_dict:
    		data = bt.feeds.PandasData(dataname=data_dict[benchmark_symbol])
    		cerebro.adddata(data, name=benchmark_name)
    		print(f"  ✓ 已添加数据: {benchmark_name}")
    	else:
    		print(f"  ✗ 错误: 找不到 {benchmark_symbol} 的数据")
    		return None

    	cerebro.addstrategy(BuyHoldStrategy)
    	cerebro.broker.setcash(INITIAL_CASH)
    	cerebro.broker.setcommission(commission=COMMISSION)
    	cerebro.addanalyzer(CustomAnalyzer, _name="custom")

    	print(CYAN + f"  初始资金: {cerebro.broker.getvalue():.2f}" + RESET)
    	results = cerebro.run()
    	print(CYAN + f"  期末资金: {cerebro.broker.getvalue():.2f}" + RESET)

    	return results[0]


    # 运行基准策略回测（沪深300）
    benchmark_result = run_benchmark_backtest(
    	data_feeds, "510300.SS", "沪深300ETF"
    )
    print(benchmark_result[0])
    return


@app.cell
def _(mo):
    mo.md(r"""
    # 等权重组合回测
    """)
    return


@app.cell
def _(
    COMMISSION,
    CustomAnalyzer,
    ETF_NAMES,
    ETF_SYMBOLS,
    EqualWeightStrategy,
    GREEN,
    INITIAL_CASH,
    RED,
    RESET,
    bt,
    data_feeds,
):
    # ==================== 等权重组合回测 ====================
    def run_equal_weight_backtest(data_dict, symbols, names):
    	"""运行等权重组合策略"""

    	cerebro = bt.Cerebro()

    	print(RED + "\n==> 运行等权重组合回测..." + RESET)
    	data_count = 0
    	for symbol, name in zip(symbols, names):
    		if symbol in data_dict:
    			data = bt.feeds.PandasData(dataname=data_dict[symbol])
    			cerebro.adddata(data, name=name)
    			data_count += 1
    			print(f"  ✓ 已添加数据: {name}")

    	if data_count == 0:
    		print("  ✗ 错误: 没有可用的数据")
    		return None

    	cerebro.addstrategy(EqualWeightStrategy)
    	cerebro.broker.setcash(INITIAL_CASH)
    	cerebro.broker.setcommission(commission=COMMISSION)
    	cerebro.addanalyzer(CustomAnalyzer, _name="custom")

    	print(GREEN + f"  初始资金: {cerebro.broker.getvalue():.2f}" + RESET)
    	results = cerebro.run()
    	print(GREEN + f"  期末资金: {cerebro.broker.getvalue():.2f}" + RESET)

    	return results[0]


    # 4. 运行等权重组合回测
    equal_weight_result = run_equal_weight_backtest(
    	data_feeds, ETF_SYMBOLS, ETF_NAMES
    )
    return


@app.cell
def _(PerformanceCalculator, pd):
    # ==================== 效能分析 ====================
    def analyze_performance(strategy_result, benchmark_result, equal_weight_result, names):
    	"""分析效能指标"""
    	print("\n正在计算效能指标...")

    	# 提取收益率
    	strategy_returns = pd.Series(strategy_result.analyzers.custom.returns)
    	benchmark_returns = pd.Series(benchmark_result.analyzers.custom.returns)
    	equal_returns = pd.Series(equal_weight_result.analyzers.custom.returns)

    	calc = PerformanceCalculator()

    	# 计算各策略的效能指标
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
    return


@app.cell
def _(GridSpec, PerformanceCalculator, mdates, np, pd, plt):

    # ==================== 可视化 ====================
    def plot_results(strategy_returns, benchmark_returns, equal_returns,
    				 strategy_dates, benchmark_dates, equal_dates,
    				 trade_log, names):
    	"""绘制回测结果"""
    	print("\n正在生成图表...")

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
    	ax1.plot(strategy_dates_idx, strategy_cum, label='动量策略', color=colors['动量策略'], linewidth=2)
    	ax1.plot(benchmark_dates_idx, benchmark_cum, label='沪深300ETF', color=colors['沪深300ETF'], linewidth=2)
    	ax1.set_ylabel('累计收益率', fontsize=12)
    	ax1.set_title('动量策略 vs 沪深300ETF: 累计收益率', fontsize=14, fontweight='bold')
    	ax1.legend(loc='upper left')
    	ax1.grid(True, alpha=0.3)
    	ax1.set_xticklabels([])

    	# 回撤
    	ax2 = fig1.add_subplot(gs1[1])
    	ax2.fill_between(strategy_dates_idx, strategy_dd, 0, label='动量策略', color=colors['动量策略'], alpha=0.3)
    	ax2.fill_between(benchmark_dates_idx, benchmark_dd, 0, label='沪深300ETF', color=colors['沪深300ETF'], alpha=0.3)
    	ax2.set_xlabel('日期', fontsize=12)
    	ax2.set_ylabel('回撤', fontsize=12)
    	ax2.grid(True, alpha=0.3)
    	ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    	plt.tight_layout()

    	# ========== 图2: 动量策略 vs 等权重组合 ==========
    	fig2 = plt.figure(figsize=(12, 8))
    	gs2 = GridSpec(2, 1, height_ratios=[2, 1], hspace=0.05)

    	ax3 = fig2.add_subplot(gs2[0])
    	ax3.plot(strategy_dates_idx, strategy_cum, label='动量策略', color=colors['动量策略'], linewidth=2)
    	ax3.plot(equal_dates_idx, equal_cum, label='等权重组合', color=colors['等权重组合'], linewidth=2)
    	ax3.set_ylabel('累计收益率', fontsize=12)
    	ax3.set_title('动量策略 vs 等权重组合: 累计收益率', fontsize=14, fontweight='bold')
    	ax3.legend(loc='upper left')
    	ax3.grid(True, alpha=0.3)
    	ax3.set_xticklabels([])

    	ax4 = fig2.add_subplot(gs2[1])
    	ax4.fill_between(strategy_dates_idx, strategy_dd, 0, label='动量策略', color=colors['动量策略'], alpha=0.3)
    	ax4.fill_between(equal_dates, equal_dd, 0, label='等权重组合', color=colors['等权重组合'], alpha=0.3)
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
    		ax5.stackplot(weight_dates_pd, weights_array[:, 0], weights_array[:, 1], weights_array[:, 2],
    					  labels=names, alpha=0.7, colors=['#E41A1C', '#377EB8', '#4DAF4A'])

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


    return (plot_results,)


@app.cell
def _(OUTPUT_DIR, os, pd):
    # ==================== 保存结果 ====================
    def save_results(performance_df, trade_log, names,
    				 strategy_dates, benchmark_dates, equal_dates,
    				 strategy_returns, benchmark_returns, equal_returns, fig1, fig2, fig3):
    	"""保存回测结果"""
    	print(f"\n正在保存结果到 {OUTPUT_DIR}...")

    	# 创建输出目录
    	os.makedirs(OUTPUT_DIR, exist_ok=True)

    	# 保存性能指标
    	performance_df.to_csv(f"{OUTPUT_DIR}/performance_metrics.csv", index=False, encoding='utf-8-sig')

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
    		'Date': strategy_dates,
    		'动量策略': strategy_returns,
    		'沪深300ETF': benchmark_returns,
    		'等权重组合': equal_returns
    	})
    	returns_df.to_csv(f"{OUTPUT_DIR}/daily_returns.csv", index=False, encoding='utf-8-sig')

    	# 保存图表
    	if fig1:
    		fig1.savefig(f"{OUTPUT_DIR}/momentum_vs_benchmark.png", dpi=300, bbox_inches='tight')
    	if fig2:
    		fig2.savefig(f"{OUTPUT_DIR}/momentum_vs_equal_weight.png", dpi=300, bbox_inches='tight')
    	if fig3:
    		fig3.savefig(f"{OUTPUT_DIR}/daily_weights_plot.png", dpi=300, bbox_inches='tight')

    	print(f"✓ 结果已保存到 {OUTPUT_DIR}/")


    return (save_results,)


app._unparsable_cell(
    r"""
    if benchmark_result is None or equal_weight_result is None:
    	print("\n错误: 基准策略或等权重策略回测失败，无法进行性能分析")
    	return

    # 5. 效能分析
    performance_df, strategy_returns, benchmark_returns, equal_returns = \
    	analyze_performance(strategy_result, benchmark_result, equal_weight_result, ETF_NAMES)

    # 打印效能指标
    print("\n" + "=" * 60)
    print("效能指标汇总")
    print("=" * 60)
    print(performance_df.to_string(index=False))
    """,
    name="_"
)


@app.cell
def _(
    ETF_NAMES,
    benchmark_returns,
    equal_returns,
    performance_df,
    plot_results,
    plt,
    save_results,
    strategy_result,
    strategy_returns,
):
    # 6. 可视化
    trade_log = strategy_result.trade_log
    dates = strategy_result.analyzers.custom.dates

    fig1, fig2, fig3 = plot_results(
    	strategy_returns, benchmark_returns, equal_returns,
    	trade_log, dates, ETF_NAMES
    )

    # 7. 保存结果
    save_results(performance_df, trade_log, dates, ETF_NAMES, strategy_returns, benchmark_returns, equal_returns, fig1, fig2, fig3)

    print("\n" + "=" * 60)
    print("回测完成！")
    print("=" * 60)

    # 显示图表
    plt.show()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
