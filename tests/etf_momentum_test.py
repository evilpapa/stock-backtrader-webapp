"""
ETF动量策略单元测试

测试ETF动量轮动策略的基本功能
"""

import unittest
from datetime import datetime
import pandas as pd
import backtrader as bt

from strategy.etf_momentum import EtfMomentumStrategy


class EtfMomentumTest(unittest.TestCase):
	"""ETF动量策略测试类"""

	def setUp(self):
		"""测试前准备"""
		# 创建简单的测试数据
		dates = pd.date_range(start='2024-01-01', end='2024-06-30', freq='D')

		# 创建三个模拟ETF数据（上涨、震荡、下跌）
		self.data1 = pd.DataFrame({
			'Open': 100 + pd.Series(range(len(dates))) * 0.1,
			'High': 101 + pd.Series(range(len(dates))) * 0.1,
			'Low': 99 + pd.Series(range(len(dates))) * 0.1,
			'Close': 100 + pd.Series(range(len(dates))) * 0.1,
			'Volume': 1000000,
		}, index=dates)

		self.data2 = pd.DataFrame({
			'Open': 100,
			'High': 102,
			'Low': 98,
			'Close': 100,
			'Volume': 1000000,
		}, index=dates)

		self.data3 = pd.DataFrame({
			'Open': 100 - pd.Series(range(len(dates))) * 0.05,
			'High': 101 - pd.Series(range(len(dates))) * 0.05,
			'Low': 99 - pd.Series(range(len(dates))) * 0.05,
			'Close': 100 - pd.Series(range(len(dates))) * 0.05,
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
