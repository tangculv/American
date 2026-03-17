from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.alert_engine import Signal  # noqa: E402
from us_stock_research.alert_manager import (  # noqa: E402
    ACTION_PRIORITY,
    ACTIVE_STATUSES,
    CONDITION_BASED_SIGNALS,
    EXPIRY_TRADING_DAYS,
    PRICE_BASED_SIGNALS,
    TERMINAL_STATUSES,
    VALID_ALERT_STATUSES,
    AlertManager,
    close_all_active_alerts,
    create_alert,
    get_active_alerts,
)
from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402


def make_paths(root: Path) -> ProjectPaths:
    return ProjectPaths(
        root=root,
        config_dir=root / "config",
        strategy_dir=root / "config" / "strategies",
        app_config_path=root / "config" / "app.yaml",
        outputs_dir=root / "outputs" / "fmp-screening",
        watchlist_dir=root / "watchlist",
        data_dir=root / "data",
        database_path=root / "data" / "stock_research.db",
        logs_dir=root / "logs",
    )


class AlertManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        ensure_schema(self.paths)
        self.manager = AlertManager(paths=self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status)
                VALUES ('AAPL', 'Apple', 'strategy', 0, 'held')
                """
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _signal(
        self,
        signal_type: str = "急跌预警",
        level: str = "warning",
        action: str = "重点关注",
        value: float | None = None,
        threshold: float | None = None,
        detail: str | None = None,
    ) -> Signal:
        return Signal(type=signal_type, level=level, action=action, value=value, threshold=threshold, detail=detail)

    def _set_triggered_days_ago(self, alert_id: int, days: int) -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                "UPDATE alert_event SET triggered_at = datetime('now', ?) WHERE id = ?",
                (f'-{days} days', alert_id),
            )

    def test_new_signal_creates_alert(self) -> None:
        self.manager.process_signals("AAPL", [self._signal(value=-5.0, threshold=-5.0)])
        alerts = get_active_alerts("AAPL", paths=self.paths)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["status"], "triggered")
        self.assertEqual(alerts[0]["signal_type"], "急跌预警")

    def test_duplicate_signal_updates_existing(self) -> None:
        self.manager.process_signals("AAPL", [self._signal(value=-5.0, threshold=-5.0)])
        self.manager.process_signals("AAPL", [self._signal(value=-6.0, threshold=-5.0, detail="updated")])
        alerts = get_active_alerts("AAPL", paths=self.paths)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["trigger_value"], -6.0)
        self.assertEqual(alerts[0]["detail"], "updated")

    def test_acknowledge_alert(self) -> None:
        alert_id = create_alert("AAPL", self._signal(), paths=self.paths)
        self.manager.acknowledge(alert_id)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT status, acknowledged_at FROM alert_event WHERE id = ?", (alert_id,)).fetchone()
        self.assertEqual(tuple(row)[0], "acknowledged")
        self.assertIsNotNone(tuple(row)[1])

    def test_resolve_alert(self) -> None:
        alert_id = create_alert("AAPL", self._signal(), paths=self.paths)
        self.manager.resolve(alert_id)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT status, resolved_at FROM alert_event WHERE id = ?", (alert_id,)).fetchone()
        self.assertEqual(tuple(row)[0], "resolved")
        self.assertIsNotNone(tuple(row)[1])

    def test_close_all_active_alerts(self) -> None:
        create_alert("AAPL", self._signal("急跌预警"), paths=self.paths)
        create_alert("AAPL", self._signal("止损触发", "action", "考虑止损"), paths=self.paths)
        close_all_active_alerts("AAPL", paths=self.paths)
        with get_connection(self.paths) as connection:
            statuses = [row[0] for row in connection.execute("SELECT status FROM alert_event ORDER BY id").fetchall()]
        self.assertEqual(statuses, ["resolved", "resolved"])

    def test_warning_expires_after_recovery(self) -> None:
        alert_id = create_alert("AAPL", self._signal("急跌预警"), paths=self.paths)
        self._set_triggered_days_ago(alert_id, EXPIRY_TRADING_DAYS)
        self.manager.check_expirations("AAPL", [])
        with get_connection(self.paths) as connection:
            status = connection.execute("SELECT status FROM alert_event WHERE id = ?", (alert_id,)).fetchone()[0]
        self.assertEqual(status, "expired")

    def test_warning_not_expired_within_3_days(self) -> None:
        alert_id = create_alert("AAPL", self._signal("急跌预警"), paths=self.paths)
        self._set_triggered_days_ago(alert_id, EXPIRY_TRADING_DAYS - 1)
        self.manager.check_expirations("AAPL", [])
        with get_connection(self.paths) as connection:
            status = connection.execute("SELECT status FROM alert_event WHERE id = ?", (alert_id,)).fetchone()[0]
        self.assertEqual(status, "triggered")

    def test_price_signal_historical_reached(self) -> None:
        alert_id = create_alert("AAPL", self._signal("目标价达成", "action", "考虑止盈"), paths=self.paths)
        self._set_triggered_days_ago(alert_id, EXPIRY_TRADING_DAYS)
        self.manager.check_expirations("AAPL", [])
        with get_connection(self.paths) as connection:
            status = connection.execute("SELECT status FROM alert_event WHERE id = ?", (alert_id,)).fetchone()[0]
        self.assertEqual(status, "historical_reached")

    def test_condition_signal_never_auto_expires(self) -> None:
        alert_id = create_alert("AAPL", self._signal("止损触发", "action", "考虑止损"), paths=self.paths)
        self._set_triggered_days_ago(alert_id, EXPIRY_TRADING_DAYS + 10)
        self.manager.check_expirations("AAPL", [])
        with get_connection(self.paths) as connection:
            status = connection.execute("SELECT status FROM alert_event WHERE id = ?", (alert_id,)).fetchone()[0]
        self.assertEqual(status, "triggered")

    def test_retrigger_resets_expiry(self) -> None:
        self.manager.process_signals("AAPL", [self._signal("急跌预警", detail="old")])
        alert_id = get_active_alerts("AAPL", paths=self.paths)[0]["id"]
        self._set_triggered_days_ago(alert_id, EXPIRY_TRADING_DAYS + 1)
        self.manager.process_signals("AAPL", [self._signal("急跌预警", detail="new")])
        self.manager.check_expirations("AAPL", [self._signal("急跌预警", detail="new")])
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT status, detail FROM alert_event WHERE id = ?", (alert_id,)).fetchone()
        self.assertEqual(tuple(row), ("triggered", "new"))

    def test_drawdown_upgrades_to_stop_loss(self) -> None:
        create_alert("AAPL", self._signal("阶段回撤", "warning", "重点关注", value=15.0), paths=self.paths)
        self.manager.check_upgrades(
            "AAPL",
            [
                self._signal("阶段回撤", "warning", "重点关注", value=15.0),
                self._signal("止损触发", "action", "考虑止损", detail="条件触发"),
            ],
        )
        with get_connection(self.paths) as connection:
            rows = connection.execute("SELECT signal_type, status FROM alert_event ORDER BY id").fetchall()
        self.assertEqual([tuple(row) for row in rows], [("阶段回撤", "upgraded"), ("止损触发", "triggered")])

    def test_upgrade_preserves_link(self) -> None:
        old_id = create_alert("AAPL", self._signal("阶段回撤", "warning", "重点关注", value=15.0), paths=self.paths)
        self.manager.check_upgrades(
            "AAPL",
            [
                self._signal("阶段回撤", "warning", "重点关注", value=15.0),
                self._signal("止损触发", "action", "考虑止损", detail="条件触发"),
            ],
        )
        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT upgrade_from_id FROM alert_event WHERE signal_type = '止损触发'"
            ).fetchone()
        self.assertEqual(row[0], old_id)

    def test_no_upgrade_without_both_signals(self) -> None:
        alert_id = create_alert("AAPL", self._signal("阶段回撤", "warning", "重点关注", value=15.0), paths=self.paths)
        self.manager.check_upgrades("AAPL", [self._signal("阶段回撤", "warning", "重点关注", value=15.0)])
        with get_connection(self.paths) as connection:
            rows = connection.execute("SELECT id, signal_type, status FROM alert_event ORDER BY id").fetchall()
        self.assertEqual([tuple(row) for row in rows], [(alert_id, "阶段回撤", "triggered")])

    def test_merge_single_signal(self) -> None:
        create_alert("AAPL", self._signal("急跌预警", "warning", "重点关注"), paths=self.paths)
        merged = self.manager.merge_for_notification("AAPL")
        self.assertEqual(merged["top_action"], "重点关注")
        self.assertEqual(merged["signal_count"], 1)

    def test_merge_multiple_signals_highest_priority(self) -> None:
        create_alert("AAPL", self._signal("急跌预警", "warning", "重点关注"), paths=self.paths)
        create_alert("AAPL", self._signal("持有逻辑失效", "action", "考虑清仓"), paths=self.paths)
        merged = self.manager.merge_for_notification("AAPL")
        self.assertEqual(merged["top_action"], "考虑清仓")

    def test_merge_no_active_returns_none(self) -> None:
        self.assertIsNone(self.manager.merge_for_notification("AAPL"))

    def test_merge_order_by_priority(self) -> None:
        create_alert("AAPL", self._signal("急跌预警", "warning", "重点关注"), paths=self.paths)
        create_alert("AAPL", self._signal("技术顶部信号", "action", "考虑减仓"), paths=self.paths)
        create_alert("AAPL", self._signal("止损触发", "action", "考虑止损"), paths=self.paths)
        merged = self.manager.merge_for_notification("AAPL")
        self.assertEqual([item["action"] for item in merged["signals"]], ["考虑止损", "考虑减仓", "重点关注"])

    def test_merge_signals_structure(self) -> None:
        create_alert("AAPL", self._signal("急跌预警", "warning", "重点关注", detail="watch"), paths=self.paths)
        merged = self.manager.merge_for_notification("AAPL")
        self.assertEqual(merged["signals"], [{"type": "急跌预警", "action": "重点关注", "detail": "watch"}])

    def test_constants_match_task(self) -> None:
        self.assertEqual(VALID_ALERT_STATUSES, ["triggered", "notified", "acknowledged", "resolved", "expired", "historical_reached", "upgraded"])
        self.assertEqual(ACTIVE_STATUSES, ("triggered", "notified", "acknowledged"))
        self.assertEqual(TERMINAL_STATUSES, ("resolved", "expired", "historical_reached", "upgraded"))
        self.assertEqual(ACTION_PRIORITY["继续持有"], 1)
        self.assertEqual(ACTION_PRIORITY["考虑清仓"], 6)
        self.assertEqual(PRICE_BASED_SIGNALS, ["目标价达成", "收益率达标", "技术顶部信号"])
        self.assertEqual(CONDITION_BASED_SIGNALS, ["止损触发", "失效条件触发", "持有逻辑失效"])
        self.assertEqual(EXPIRY_TRADING_DAYS, 3)


if __name__ == "__main__":
    unittest.main()
