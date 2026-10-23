import math
import statistics
import unittest

import backtrader as bt
import pandas as pd

from src.risk import (
	RISK_PRESETS,
	AssetSnapshot,
	PortfolioSnapshot,
	RiskConfig,
	RiskDecision,
	RiskManager,
	load_preset,
)
from src.risk.report import build_risk_event_frame, build_risk_summary_frame, format_risk_summary
from src.strategy import BaseStrategy


def make_feed(closes: list[float]) -> bt.feeds.PandasData:
	"""构造只包含收盘价序列的 Backtrader 数据源。"""
	dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
	frame = pd.DataFrame(
		{
			"open": closes,
			"high": [value * 1.01 for value in closes],
			"low": [value * 0.99 for value in closes],
			"close": closes,
			"volume": [1_000_000] * len(closes),
		},
		index=dates,
	)
	return bt.feeds.PandasData(dataname=frame)


def snapshot(equity: float, assets: list[tuple[str, float, float, float]] | None = None, date: str = "2024-01-02") -> PortfolioSnapshot:
	"""构造账户快照；assets 为 (名称, 数量, 成本价, 最新价)。"""
	rows = tuple(
		AssetSnapshot(name=name, size=size, cost_price=cost, last_price=last)
		for name, size, cost, last in (assets or [])
	)
	return PortfolioSnapshot(date=date, equity=equity, cash=equity, assets=rows)


class BuyAndHoldStrategy(BaseStrategy):
	"""一次性满仓买入并持有的测试策略。"""

	def __init__(self) -> None:
		super().__init__()
		self.buy_count = 0

	def next(self) -> None:
		if self.buy_count:
			return
		price = self.data.close[0]
		size = int(self.broker.getcash() * 0.99 / price)
		if size > 0:
			self._track_order(self.buy(size=size))
			self.buy_count += 1


class AlwaysRebuyStrategy(BaseStrategy):
	"""每根 K 线都尝试满仓买入，用于验证开仓拦截。"""

	def __init__(self) -> None:
		super().__init__()
		self.buy_attempts = 0

	def next(self) -> None:
		price = self.data.close[0]
		size = int(self.broker.getcash() * 0.99 / price)
		if size > 0:
			self.buy_attempts += 1
			self._track_order(self.buy(size=size))


def run_backtest(strategy_cls, closes: list[float], risk_config=None):
	"""在固定初始资金、无手续费环境下运行一次回测。"""
	cerebro = bt.Cerebro()
	cerebro.adddata(make_feed(closes))
	cerebro.broker.setcash(100000.0)
	cerebro.broker.setcommission(commission=0.0)
	cerebro.addstrategy(strategy_cls, risk_config=risk_config)
	strategy = cerebro.run()[0]
	return strategy, cerebro.broker.getvalue()


class RiskManagerRuleTest(unittest.TestCase):
	"""风控规则引擎的纯逻辑测试（不依赖 Backtrader）。"""

	def test_disabled_manager_is_neutral(self):
		"""未启用风控时所有指令都保持中性。"""
		manager = RiskManager(RiskConfig())
		decision = manager.evaluate(snapshot(100.0), bar=1)
		self.assertFalse(manager.enabled)
		self.assertFalse(decision.close_all)
		self.assertTrue(decision.allow_new_positions)
		self.assertEqual(decision.exposure_scale, 1.0)
		self.assertEqual(manager.clamp_weights({"A": 0.6, "B": 0.6}), {"A": 0.6, "B": 0.6})

	def test_accepts_dict_config(self):
		"""允许直接用字典构造风控配置，便于命令行和配置文件传参。"""
		manager = RiskManager({"enabled": True, "max_drawdown": 0.1, "stop_loss": 0.05})
		self.assertTrue(manager.enabled)
		self.assertEqual(manager.config.max_drawdown, 0.1)

	def test_drawdown_halt_and_cooldown(self):
		"""回撤超过阈值时清仓，并在冷却期内持续禁止开仓。"""
		manager = RiskManager(RiskConfig(enabled=True, max_drawdown=0.1, drawdown_cooldown_days=2))
		self.assertFalse(manager.evaluate(snapshot(100.0), bar=1).close_all)

		halt = manager.evaluate(snapshot(89.0), bar=2)
		self.assertTrue(halt.close_all)
		self.assertTrue(halt.halted)
		self.assertFalse(halt.allow_new_positions)
		self.assertAlmostEqual(halt.drawdown, 0.11, places=6)

		# 冷却期覆盖 bar=3、4，bar=5 恢复
		self.assertTrue(manager.evaluate(snapshot(89.0), bar=3).halted)
		self.assertTrue(manager.evaluate(snapshot(89.0), bar=4).halted)
		recovered = manager.evaluate(snapshot(89.0), bar=5)
		self.assertFalse(recovered.halted)
		self.assertTrue(recovered.allow_new_positions)
		self.assertEqual(manager.summary()["halt_count"], 1)

	def test_drawdown_uses_equity_peak(self):
		"""回撤基准是历史最高权益，而不是初始资金。"""
		manager = RiskManager(RiskConfig(enabled=True, max_drawdown=0.2))
		manager.evaluate(snapshot(100.0), bar=1)
		manager.evaluate(snapshot(200.0), bar=2)
		decision = manager.evaluate(snapshot(165.0), bar=3)
		self.assertFalse(decision.close_all)  # 相对峰值 200 只回撤 17.5%
		self.assertTrue(manager.evaluate(snapshot(155.0), bar=4).close_all)  # 回撤 22.5%

	def test_stop_loss_closes_asset_and_blocks_reentry(self):
		"""单标的跌幅超过止损线时平仓，并在冷却期内禁止回补。"""
		manager = RiskManager(RiskConfig(enabled=True, stop_loss=0.1, asset_cooldown_days=2))
		manager.evaluate(snapshot(100.0, [("A", 1000, 10.0, 10.0)]), bar=1)
		decision = manager.evaluate(snapshot(100.0, [("A", 1000, 10.0, 8.9)]), bar=2)

		self.assertEqual(decision.close_assets, ("A",))
		self.assertFalse(decision.close_all)
		self.assertTrue(manager.is_asset_blocked("A"))
		self.assertEqual(manager.clamp_weights({"A": 0.5, "B": 0.5}), {"B": 0.5})
		self.assertEqual(manager.summary()["stop_loss_count"], 1)

	def test_trailing_stop_uses_holding_peak(self):
		"""移动止损以持仓期最高价为基准，而不是成本价。"""
		manager = RiskManager(RiskConfig(enabled=True, trailing_stop=0.1))
		manager.evaluate(snapshot(100.0, [("A", 100, 10.0, 10.0)]), bar=1)
		manager.evaluate(snapshot(100.0, [("A", 100, 10.0, 12.0)]), bar=2)
		# 成本价 10 跌到 10.7 仍盈利，但相对高点 12 已回撤 10.8%
		decision = manager.evaluate(snapshot(100.0, [("A", 100, 10.0, 10.7)]), bar=3)
		self.assertEqual(decision.close_assets, ("A",))
		self.assertEqual(manager.summary()["trailing_stop_count"], 1)

	def test_take_profit_closes_asset(self):
		"""止盈线触发后平仓，且不会误判为组合熔断。"""
		manager = RiskManager(RiskConfig(enabled=True, take_profit=0.2))
		manager.evaluate(snapshot(100.0, [("A", 100, 10.0, 10.0)]), bar=1)
		decision = manager.evaluate(snapshot(100.0, [("A", 100, 10.0, 12.1)]), bar=2)
		self.assertEqual(decision.close_assets, ("A",))
		self.assertFalse(decision.close_all)

	def test_short_position_stop_loss(self):
		"""空头持仓的止损方向与多头相反。"""
		manager = RiskManager(RiskConfig(enabled=True, stop_loss=0.1))
		manager.evaluate(snapshot(100.0, [("A", -100, 10.0, 10.0)]), bar=1)
		self.assertEqual(manager.evaluate(snapshot(100.0, [("A", -100, 10.0, 10.2)]), bar=2).close_assets, ())
		self.assertEqual(manager.evaluate(snapshot(100.0, [("A", -100, 10.0, 11.2)]), bar=3).close_assets, ("A",))

	def test_daily_loss_limit_blocks_new_positions(self):
		"""单日亏损超过限制时当日禁止开仓，但不影响已有持仓。"""
		manager = RiskManager(RiskConfig(enabled=True, daily_loss_limit=0.05))
		manager.evaluate(snapshot(100.0, [("A", 100, 10.0, 10.0)]), bar=1)
		decision = manager.evaluate(snapshot(94.0, [("A", 100, 10.0, 9.4)]), bar=2)
		self.assertFalse(decision.allow_new_positions)
		self.assertEqual(decision.close_assets, ())
		self.assertTrue(manager.evaluate(snapshot(94.0, [("A", 100, 10.0, 9.4)]), bar=3).allow_new_positions)

	def test_volatility_target_scales_exposure(self):
		"""实现波动率高于目标时按比例压缩仓位，并受最小系数约束。"""
		config = RiskConfig(enabled=True, max_drawdown=0.0, target_volatility=0.10, volatility_window=20, min_vol_scale=0.2)
		manager = RiskManager(config)

		returns = [0.03 if index % 2 == 0 else -0.02 for index in range(24)]
		equity = 100.0
		decision = manager.evaluate(snapshot(equity), bar=1)
		for index, ret in enumerate(returns, start=1):
			equity *= 1 + ret
			decision = manager.evaluate(snapshot(equity), bar=index + 1)

		realized = statistics.pstdev(returns[-20:]) * math.sqrt(252)
		expected = max(0.2, min(1.0, 0.10 / realized))
		self.assertAlmostEqual(decision.realized_volatility, realized, places=9)
		self.assertAlmostEqual(decision.exposure_scale, expected, places=9)
		self.assertLess(decision.exposure_scale, 1.0)

	def test_volatility_target_never_levers_up(self):
		"""低波动环境仓位系数上限为 1，不会加杠杆。"""
		manager = RiskManager(RiskConfig(enabled=True, target_volatility=0.9, volatility_window=5, min_vol_scale=0.2))
		equity = 100.0
		decision = RiskDecision()
		for index in range(10):
			equity *= 1.0001
			decision = manager.evaluate(snapshot(equity), bar=index + 1)
		self.assertEqual(decision.exposure_scale, 1.0)

	def test_clamp_weights_applies_position_limits(self):
		"""单标的上限与组合上限同时生效，且不重新分配被裁掉的权重。"""
		manager = RiskManager(RiskConfig(enabled=True, max_asset_weight=0.4, max_gross_exposure=0.6))
		adjusted = manager.clamp_weights({"A": 0.5, "B": 0.5})
		self.assertAlmostEqual(adjusted["A"], 0.3, places=9)
		self.assertAlmostEqual(adjusted["B"], 0.3, places=9)
		self.assertAlmostEqual(sum(adjusted.values()), 0.6, places=9)

	def test_clamp_weights_applies_exposure_scale(self):
		"""波动率裁剪系数会作用在目标权重上。"""
		manager = RiskManager(RiskConfig(enabled=True, target_volatility=0.2))
		adjusted = manager.clamp_weights({"A": 1.0}, RiskDecision(exposure_scale=0.5))
		self.assertAlmostEqual(adjusted["A"], 0.5, places=9)

	def test_config_validation_rejects_bad_values(self):
		"""非法参数在构造阶段直接报错，避免回测中途才暴露。"""
		with self.assertRaises(ValueError):
			RiskConfig(enabled=True, max_drawdown=1.5)
		with self.assertRaises(ValueError):
			RiskConfig(enabled=True, max_gross_exposure=0.0)
		with self.assertRaises(ValueError):
			RiskConfig.from_dict({"enabled": True, "max_dradown": 0.2})
		with self.assertRaises(ValueError):
			RiskConfig(enabled=True, volatility_window=1)
		with self.assertRaises(TypeError):
			RiskConfig(enabled=True, stop_loss="0.1")

	def test_presets_are_valid_and_ordered(self):
		"""内置预设可直接使用，且风险由低到高逐步放宽。"""
		conservative = load_preset("conservative")
		balanced = load_preset("balanced")
		aggressive = load_preset("aggressive")
		self.assertFalse(RISK_PRESETS["none"].enabled)
		self.assertLess(conservative.max_drawdown, balanced.max_drawdown)
		self.assertLess(balanced.max_drawdown, aggressive.max_drawdown)
		self.assertLess(conservative.stop_loss, aggressive.stop_loss)
		with self.assertRaises(ValueError):
			load_preset("unknown")


class RiskControlIntegrationTest(unittest.TestCase):
	"""风控混入与 Backtrader 策略的集成测试。"""

	def test_disabled_risk_keeps_strategy_behaviour(self):
		"""风控关闭时回测结果与未接入风控完全一致。"""
		closes = [100.0] * 5 + [101.0, 102.0, 103.0, 104.0, 105.0]
		plain, plain_value = run_backtest(BuyAndHoldStrategy, closes)
		configured, configured_value = run_backtest(BuyAndHoldStrategy, closes, RiskConfig())

		self.assertAlmostEqual(plain_value, configured_value, places=6)
		self.assertEqual(configured.risk_events, [])
		self.assertFalse(configured.risk_summary()["enabled"])
		self.assertGreater(plain.buy_count, 0)

	def test_stop_loss_exits_position_in_backtest(self):
		"""价格跌破止损线后策略持仓被清零。"""
		closes = [100.0] * 5 + [101.0, 102.0, 101.0, 88.0, 87.0, 86.0]
		strategy, value = run_backtest(BuyAndHoldStrategy, closes, RiskConfig(enabled=True, stop_loss=0.1))

		self.assertEqual(strategy.position.size, 0)
		self.assertEqual(strategy.risk_summary()["stop_loss_count"], 1)
		self.assertTrue(any(event.rule == "stop_loss" for event in strategy.risk_events))
		self.assertGreater(value, 0)

	def test_drawdown_halt_flattens_portfolio(self):
		"""组合回撤熔断后清空全部持仓，且冷却期内不再开仓。"""
		closes = [100.0] * 5 + [110.0, 120.0, 130.0, 95.0, 90.0, 89.0, 88.0]
		config = RiskConfig(enabled=True, max_drawdown=0.15, drawdown_cooldown_days=5, stop_loss=0.0)
		strategy, _ = run_backtest(BuyAndHoldStrategy, closes, config)

		self.assertEqual(strategy.position.size, 0)
		self.assertEqual(strategy.risk_summary()["halt_count"], 1)
		self.assertGreater(strategy.risk_summary()["blocked_bars"], 0)

	def test_blocked_asset_respects_cooldown_then_reenters(self):
		"""止损冷却期内拦截回补买入，冷却结束后允许重新建仓。"""
		closes = [100.0] * 5 + [85.0] * 25
		config = RiskConfig(enabled=True, stop_loss=0.1, asset_cooldown_days=8)
		strategy, _ = run_backtest(AlwaysRebuyStrategy, closes, config)

		summary = strategy.risk_summary()
		self.assertGreaterEqual(summary["stop_loss_count"], 1)
		self.assertGreater(summary["blocked_buy_count"], 0)
		# 冷却期结束后策略可以重新买入，因此期末仍有持仓。
		self.assertGreater(strategy.position.size, 0)

	def test_weight_cap_limits_single_asset_exposure(self):
		"""apply_risk_weights 会把单标的权重压到上限以内。"""
		closes = [100.0] * 10
		strategy, _ = run_backtest(
			BuyAndHoldStrategy,
			closes,
			RiskConfig(enabled=True, max_asset_weight=0.5),
		)
		adjusted = strategy.apply_risk_weights({"资产A": 1.0})
		self.assertAlmostEqual(adjusted["资产A"], 0.5, places=9)

	def test_risk_report_frames(self):
		"""事件表与统计表可以正常生成，用于命令行和页面展示。"""
		closes = [100.0] * 5 + [101.0, 90.0, 89.0]
		strategy, _ = run_backtest(BuyAndHoldStrategy, closes, RiskConfig(enabled=True, stop_loss=0.05))

		events = build_risk_event_frame(strategy.risk_events)
		self.assertEqual(list(events.columns), ["日期", "规则", "标的", "动作", "说明"])
		self.assertGreater(len(events), 0)

		summary = build_risk_summary_frame(strategy)
		self.assertIn("固定止损次数", set(summary["指标"]))
		self.assertIn("风控启用", set(summary["指标"]))
		self.assertIn("风控: ", format_risk_summary(strategy))

	def test_all_strategy_hooks_are_wrapped_once(self):
		"""每个策略钩子只被包装一次，COO 策略的 next_open 同样受保护。"""
		from src.strategy import EtfMomentumStrategy, MysteriousSpiralStrategy

		self.assertTrue(getattr(EtfMomentumStrategy.__dict__["next"], "__risk_control__", False))
		self.assertTrue(getattr(MysteriousSpiralStrategy.__dict__["next_open"], "__risk_control__", False))
		# 包装层内部必须还是原始方法，说明没有被重复套娃
		wrapped = BuyAndHoldStrategy.__dict__["next"]
		self.assertTrue(getattr(wrapped, "__risk_control__", False))
		self.assertFalse(getattr(getattr(wrapped, "__wrapped__", None), "__risk_control__", False))

	def test_risk_config_is_inherited_from_base_strategy(self):
		"""策略无需重复声明 risk_config，即可通过参数注入风控配置。"""
		from src.strategy import EtfMomentumStrategy

		params_cls = getattr(EtfMomentumStrategy, "params")
		params = dict(params_cls._getitems())
		self.assertIn("risk_config", params)
		self.assertIn("print_log", params)


class RiskPipelineTest(unittest.TestCase):
	"""回测流水线（示例结果表 + 风控文件）的端到端测试。"""

	@staticmethod
	def _price_frame(scale: float, periods: int = 140) -> pd.DataFrame:
		"""构造带趋势和回撤的合成行情，用于驱动流水线。"""
		dates = pd.bdate_range("2024-01-01", periods=periods)
		closes = []
		price = 100.0 * scale
		for index in range(periods):
			# 前 100 天震荡上行，随后快速回撤，用于触发止损与风控事件。
			# 必须保留日间波动，否则风险调整动量为 0，策略不会建仓。
			trend = 0.002 if index < 100 else -0.02
			wiggle = 0.004 if index % 2 == 0 else -0.004
			price *= 1.0 + trend + wiggle
			closes.append(price)
		frame = pd.DataFrame(
			{
				"Open": closes,
				"High": [value * 1.01 for value in closes],
				"Low": [value * 0.99 for value in closes],
				"Close": closes,
				"Volume": [1_000_000] * periods,
			},
			index=dates,
		)
		return frame

	def test_etf_momentum_pipeline_writes_risk_outputs(self):
		"""启用风控后，回测流水线会额外输出风控事件与风控统计文件。"""
		import tempfile
		from pathlib import Path

		from src.utils.etf_momentum_backtest import run_etf_momentum_backtest

		price_data = {
			"513100": self._price_frame(1.0),
			"510300": self._price_frame(1.2),
			"518880": self._price_frame(0.8),
		}
		assets = [
			{"symbol": "513100", "name": "纳指ETF"},
			{"symbol": "510300", "name": "沪深300ETF"},
			{"symbol": "518880", "name": "黄金ETF"},
		]
		with tempfile.TemporaryDirectory() as tmp:
			output_dir = Path(tmp)
			frames = run_etf_momentum_backtest(
				assets,
				"510300",
				"沪深300ETF",
				"2024-01-01",
				"2024-07-01",
				100_000.0,
				5,
				1,
				output_dir,
				price_data=price_data,
				strategy_class=BuyAndHoldStrategy,
				strategy_params={"print_log": False},
				risk_config=RiskConfig(enabled=True, stop_loss=0.05, trailing_stop=0.08, max_drawdown=0.2),
			)

			self.assertTrue((output_dir / "risk_events.csv").is_file())
			self.assertTrue((output_dir / "risk_summary.csv").is_file())
			risk_summary, risk_events = frames.risk_summary, frames.risk_events
			self.assertIsNotNone(risk_summary)
			self.assertIsNotNone(risk_events)
			if risk_summary is None or risk_events is None:  # pragma: no cover - 上两行已保证
				return
			self.assertIn("风控启用", set(risk_summary["指标"]))
			self.assertGreater(len(risk_events), 0)
			self.assertIn("规则", set(risk_events.columns))


if __name__ == "__main__":
	unittest.main()
