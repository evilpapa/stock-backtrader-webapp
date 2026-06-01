"""
ETF动量策略单元测试

测试ETF动量轮动策略的基本功能
"""

import unittest
import pandas as pd
import backtrader as bt
import numpy as np

from strategy.etf_momentum import EtfMomentumStrategy


class EtfMomentumTest(unittest.TestCase):
	"""ETF动量策略测试类"""

	def setUp(self):
		"""测试前准备"""
		# 创建简单的测试数据
		dates = pd.date_range(start='2024-01-01', end='2024-06-30', freq='D')
		up = 100 + np.arange(len(dates)) * 0.1
		flat = np.full(len(dates), 100.0)
		down = 100 - np.arange(len(dates)) * 0.05

		# 创建三个模拟ETF数据（上涨、震荡、下跌）
		self.data1 = pd.DataFrame({
			'Open': up,
			'High': up + 1,
			'Low': up - 1,
			'Close': up,
			'Volume': 1000000,
		}, index=dates)

		self.data2 = pd.DataFrame({
			'Open': flat,
			'High': flat + 2,
			'Low': flat - 2,
			'Close': flat,
			'Volume': 1000000,
		}, index=dates)

		self.data3 = pd.DataFrame({
			'Open': down,
			'High': down + 1,
			'Low': down - 1,
			'Close': down,
			'Volume': 1000000,
		}, index=dates)

	def test_strategy_initialization(self):
		"""测试策略初始化"""
		cerebro = bt.Cerebro()

		# 添加数据
		data1 = bt.feeds.PandasData(dataname=self.data1)
		data2 = bt.feeds.PandasData(dataname=self.data2)
		data3 = bt.feeds.PandasData(dataname=self.data3)

		cerebro.adddata(data1, name='ETF1')
		cerebro.adddata(data2, name='ETF2')
		cerebro.adddata(data3, name='ETF3')

		# 添加策略
		cerebro.addstrategy(EtfMomentumStrategy, momentum_window=20)

		# 设置初始资金
		cerebro.broker.setcash(100000.0)

		# 运行
		initial_value = cerebro.broker.getvalue()
		results = cerebro.run()
		final_value = cerebro.broker.getvalue()

		# 验证策略运行完成
		self.assertIsNotNone(results)
		self.assertIsInstance(final_value, float)

		# 验证资金变化（上涨的ETF应该带来正收益）
		print(f"初始资金: {initial_value:.2f}")
		print(f"期末资金: {final_value:.2f}")
		print(f"收益率: {(final_value - initial_value) / initial_value * 100:.2f}%")

	def test_strategy_with_parameters(self):
		"""测试不同参数配置"""
		cerebro = bt.Cerebro()

		data1 = bt.feeds.PandasData(dataname=self.data1)
		cerebro.adddata(data1, name='ETF1')

		# 测试不同的动量窗口
		for window in [10, 20, 30]:
			cerebro_temp = bt.Cerebro()
			cerebro_temp.adddata(bt.feeds.PandasData(dataname=self.data1), name='ETF1')
			cerebro_temp.addstrategy(EtfMomentumStrategy, momentum_window=window)
			cerebro_temp.broker.setcash(100000.0)

			results = cerebro_temp.run()
			final_value = cerebro_temp.broker.getvalue()

			print(f"动量窗口={window}天, 期末资金={final_value:.2f}")

			self.assertIsNotNone(results)

	def test_rebalance_days_controls_frequency(self):
		"""测试再平衡频率参数控制调仓次数"""
		fast_cerebro = bt.Cerebro()
		fast_cerebro.adddata(bt.feeds.PandasData(dataname=self.data1), name='ETF1')
		fast_cerebro.addstrategy(
			EtfMomentumStrategy,
			momentum_window=20,
			rebalance_days=1,
		)
		fast_cerebro.broker.setcash(100000.0)
		fast_result = fast_cerebro.run()[0]

		slow_cerebro = bt.Cerebro()
		slow_cerebro.adddata(bt.feeds.PandasData(dataname=self.data1), name='ETF1')
		slow_cerebro.addstrategy(
			EtfMomentumStrategy,
			momentum_window=20,
			rebalance_days=20,
		)
		slow_cerebro.broker.setcash(100000.0)
		slow_result = slow_cerebro.run()[0]

		self.assertGreater(
			len(fast_result.rebalance_history),
			len(slow_result.rebalance_history),
		)

	def test_momentum_calculation(self):
		"""测试动量计算逻辑"""
		# 这是一个简化的测试，验证动量指标的计算
		cerebro = bt.Cerebro()

		# 添加上涨趋势的数据
		data = bt.feeds.PandasData(dataname=self.data1)
		cerebro.adddata(data, name='UpTrend')

		# 添加策略
		cerebro.addstrategy(EtfMomentumStrategy,
							momentum_window=20,
							printlog=False)

		cerebro.broker.setcash(100000.0)

		initial_value = cerebro.broker.getvalue()
		results = cerebro.run()
		final_value = cerebro.broker.getvalue()

		# 上涨趋势应该产生正收益
		self.assertGreater(final_value, initial_value,
						   "上涨趋势的ETF应该产生正收益")


if __name__ == '__main__':
	unittest.main()
