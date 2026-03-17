from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.alert_engine import AlertEngine, Signal  # noqa: E402


class StubAlertEngine(AlertEngine):
    def __init__(self, earnings_days: int | None = None) -> None:
        self.earnings_days = earnings_days

    def _days_to_earnings(self, symbol: str) -> int | None:
        del symbol
        return self.earnings_days


class AlertEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AlertEngine()
        self.position = {"avg_cost": 100.0}

    def _snapshot(self, **overrides: float) -> dict:
        snapshot = {
            "price": 100.0,
            "daily_change_pct": 0.0,
            "high_52w": 110.0,
            "ma_50": 105.0,
            "ma_200": 100.0,
            "prev_ma_50": 106.0,
            "prev_ma_200": 100.0,
            "rsi_14": 50.0,
            "ma_50_slope": 0.5,
        }
        snapshot.update(overrides)
        return snapshot

    def _research(self, **overrides: object) -> dict:
        research = {
            "prev_roe": 20.0,
            "roe": 20.0,
            "net_debt_to_ebitda": 3.0,
            "stop_loss_condition": None,
            "target_price_conservative": None,
            "target_price_base": None,
            "target_price_optimistic": None,
            "invalidation_conditions": [],
            "invalidation_conditions_json": None,
            "overall_conclusion": "值得投",
        }
        research.update(overrides)
        return research

    def _find(self, signals: list[Signal], signal_type: str) -> list[Signal]:
        return [signal for signal in signals if signal.type == signal_type]

    def test_sharp_drop_at_5pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(daily_change_pct=-5.0), None, None)
        matched = self._find(signals, "急跌预警")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].level, "warning")
        self.assertEqual(matched[0].action, "重点关注")
        self.assertEqual(matched[0].threshold, -5.0)

    def test_sharp_drop_at_4_9pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(daily_change_pct=-4.9), None, None)
        self.assertEqual(self._find(signals, "急跌预警"), [])

    def test_drawdown_at_15pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(price=85.0, high_52w=100.0), None, None)
        matched = self._find(signals, "阶段回撤")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].value, 15.0)
        self.assertEqual(matched[0].threshold, 15.0)

    def test_drawdown_at_14pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(price=86.0, high_52w=100.0), None, None)
        self.assertEqual(self._find(signals, "阶段回撤"), [])

    def test_roe_drop_5pp(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(), self._research(prev_roe=20.0, roe=15.0), None)
        matched = self._find(signals, "基本面恶化")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].threshold, 5.0)
        self.assertIn("ROE 下降 5.0", matched[0].detail or "")

    def test_roe_drop_4pp(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(), self._research(prev_roe=20.0, roe=16.0), None)
        self.assertEqual(self._find(signals, "基本面恶化"), [])

    def test_leverage_at_4(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(), self._research(net_debt_to_ebitda=4.0), None)
        matched = self._find(signals, "杠杆风险升级")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].value, 4.0)
        self.assertEqual(matched[0].threshold, 4.0)

    def test_leverage_at_3_9(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(), self._research(net_debt_to_ebitda=3.9), None)
        self.assertEqual(self._find(signals, "杠杆风险升级"), [])

    def test_death_cross_just_crossed(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(ma_50=99.0, ma_200=100.0, prev_ma_50=100.0, prev_ma_200=100.0),
            None,
            None,
        )
        matched = self._find(signals, "技术面转弱")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].detail, "50日均线下穿200日均线（死叉）")

    def test_death_cross_already_below(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(ma_50=99.0, ma_200=100.0, prev_ma_50=98.0, prev_ma_200=100.0),
            None,
            None,
        )
        self.assertEqual(self._find(signals, "技术面转弱"), [])

    def test_earnings_within_3_days(self) -> None:
        engine = StubAlertEngine(earnings_days=2)
        signals = engine.detect_signals("AAPL", self._snapshot(), None, None)
        matched = self._find(signals, "财报临近")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].value, 2.0)
        self.assertEqual(matched[0].threshold, 3.0)

    def test_earnings_no_data(self) -> None:
        engine = StubAlertEngine(earnings_days=None)
        signals = engine.detect_signals("AAPL", self._snapshot(), None, None)
        self.assertEqual(self._find(signals, "财报临近"), [])

    def test_stop_loss_at_8pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(price=92.0), None, self.position)
        matched = self._find(signals, "止损触发")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].threshold, -8.0)

    def test_stop_loss_at_7pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(price=93.0), None, self.position)
        self.assertEqual(self._find(signals, "止损触发"), [])

    def test_target_price_conservative_hit(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(price=121.0),
            self._research(target_price_conservative=120.0),
            self.position,
        )
        matched = self._find(signals, "目标价达成")
        self.assertEqual(len(matched), 1)
        self.assertIn("保守目标价", matched[0].detail or "")

    def test_target_price_not_hit(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(price=119.0),
            self._research(
                target_price_conservative=120.0,
                target_price_base=130.0,
                target_price_optimistic=140.0,
            ),
            self.position,
        )
        self.assertEqual(self._find(signals, "目标价达成"), [])

    def test_profit_target_at_20pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(price=120.0), None, self.position)
        matched = self._find(signals, "收益率达标")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].threshold, 20.0)

    def test_profit_target_at_19pct(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(price=119.0), None, self.position)
        self.assertEqual(self._find(signals, "收益率达标"), [])

    def test_invalidation_condition_exists(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(invalidation_conditions=["行业逻辑破坏"]),
            self.position,
        )
        matched = self._find(signals, "失效条件触发")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].detail, "行业逻辑破坏")

    def test_invalidation_condition_empty(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(invalidation_conditions=[]),
            self.position,
        )
        self.assertEqual(self._find(signals, "失效条件触发"), [])

    def test_holding_logic_invalid(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(overall_conclusion="不值得投"),
            self.position,
        )
        matched = self._find(signals, "持有逻辑失效")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].action, "考虑清仓")

    def test_holding_logic_valid(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(overall_conclusion="值得投"),
            self.position,
        )
        self.assertEqual(self._find(signals, "持有逻辑失效"), [])

    def test_technical_top(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(rsi_14=75.0, ma_50_slope=-0.5),
            None,
            self.position,
        )
        matched = self._find(signals, "技术顶部信号")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].action, "考虑减仓")

    def test_technical_top_rsi_low(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(rsi_14=65.0, ma_50_slope=-0.5),
            None,
            self.position,
        )
        self.assertEqual(self._find(signals, "技术顶部信号"), [])

    def test_no_position_no_sell_signals(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(price=92.0, rsi_14=75.0, ma_50_slope=-0.5),
            self._research(
                stop_loss_condition="跌破关键位",
                target_price_conservative=90.0,
                invalidation_conditions=["逻辑失效"],
                overall_conclusion="不值得投",
            ),
            None,
        )
        self.assertEqual(self._find(signals, "止损触发"), [])
        self.assertEqual(self._find(signals, "目标价达成"), [])
        self.assertEqual(self._find(signals, "收益率达标"), [])
        self.assertEqual(self._find(signals, "失效条件触发"), [])
        self.assertEqual(self._find(signals, "持有逻辑失效"), [])
        self.assertEqual(self._find(signals, "技术顶部信号"), [])

    def test_multiple_signals_returned(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(
                price=120.0,
                daily_change_pct=-6.0,
                high_52w=150.0,
                rsi_14=75.0,
                ma_50_slope=-0.5,
            ),
            self._research(
                prev_roe=20.0,
                roe=14.0,
                net_debt_to_ebitda=4.5,
                stop_loss_condition="跌破关键位",
                target_price_conservative=118.0,
                invalidation_conditions_json='["核心假设破坏"]',
                overall_conclusion="不值得投",
            ),
            self.position,
        )
        signal_types = [signal.type for signal in signals]
        self.assertIn("急跌预警", signal_types)
        self.assertIn("阶段回撤", signal_types)
        self.assertIn("基本面恶化", signal_types)
        self.assertIn("杠杆风险升级", signal_types)
        self.assertIn("目标价达成", signal_types)
        self.assertIn("收益率达标", signal_types)
        self.assertIn("失效条件触发", signal_types)
        self.assertIn("持有逻辑失效", signal_types)
        self.assertIn("技术顶部信号", signal_types)

    def test_fundamental_deterioration_roe_drop(self) -> None:
        signals = self.engine.detect_signals("AAPL", self._snapshot(), self._research(prev_roe=15.0, roe=9.5), None)
        matched = self._find(signals, "基本面恶化")
        self.assertEqual(len(matched), 1)
        self.assertIn("ROE", matched[0].detail or "")

    def test_fundamental_deterioration_net_margin_flip(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(prev_roe=10.0, roe=10.0, prev_net_margin=5.0, curr_net_margin=-1.0),
            None,
        )
        matched = self._find(signals, "基本面恶化")
        self.assertEqual(len(matched), 1)
        self.assertIn("净利率由正转负", matched[0].detail or "")

    def test_fundamental_deterioration_de_ratio_high(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(prev_roe=10.0, roe=10.0, curr_de_ratio=2.1),
            None,
        )
        matched = self._find(signals, "基本面恶化")
        self.assertEqual(len(matched), 1)
        self.assertIn("负债权益比", matched[0].detail or "")

    def test_fundamental_deterioration_none_triggers(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(prev_roe=10.0, roe=10.0, prev_net_margin=5.0, curr_net_margin=4.0, curr_de_ratio=1.5),
            None,
        )
        self.assertEqual(self._find(signals, "基本面恶化"), [])

    def test_technical_weakness_death_cross(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(ma_50=99.0, ma_200=100.0, prev_ma_50=101.0, prev_ma_200=100.0),
            None,
            None,
        )
        matched = self._find(signals, "技术面转弱")
        self.assertEqual(len(matched), 1)
        self.assertIn("死叉", matched[0].detail or "")

    def test_technical_weakness_volume_spike(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(volume=200.0, avg_volume_20d=100.0, daily_change_pct=-1.0),
            None,
            None,
        )
        matched = self._find(signals, "技术面转弱")
        self.assertEqual(len(matched), 1)
        self.assertIn("成交量", matched[0].detail or "")

    def test_technical_weakness_volume_spike_no_trigger_when_up(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(volume=200.0, avg_volume_20d=100.0, daily_change_pct=1.0),
            None,
            None,
        )
        self.assertEqual(self._find(signals, "技术面转弱"), [])

    def test_technical_weakness_no_trigger(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(volume=150.0, avg_volume_20d=100.0, daily_change_pct=-1.0),
            None,
            None,
        )
        self.assertEqual(self._find(signals, "技术面转弱"), [])

    def test_reduce_condition_met(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(reduce_position_condition="估值透支"),
            self.position,
        )
        matched = self._find(signals, "减仓条件达成")
        self.assertEqual(len(matched), 1)
        self.assertIn("减仓条件", matched[0].detail or "")

    def test_reduce_condition_empty(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(),
            self._research(reduce_position_condition=None),
            self.position,
        )
        self.assertEqual(self._find(signals, "减仓条件达成"), [])

    def test_overvaluation_triggered(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(price=150.0),
            self._research(target_price_base=100.0),
            self.position,
        )
        matched = self._find(signals, "估值过高")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].threshold, 150.0)

    def test_overvaluation_not_triggered(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(price=149.0),
            self._research(target_price_base=100.0),
            self.position,
        )
        self.assertEqual(self._find(signals, "估值过高"), [])

    def test_overvaluation_no_target(self) -> None:
        signals = self.engine.detect_signals(
            "AAPL",
            self._snapshot(price=150.0),
            self._research(target_price_base=None),
            self.position,
        )
        self.assertEqual(self._find(signals, "估值过高"), [])


if __name__ == "__main__":
    unittest.main()
