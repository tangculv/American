from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.event_notifications import build_event_payload, create_notification_event, send_notification_event  # noqa: E402
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


class EventNotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_notification_event_is_idempotent_by_dedupe_key(self) -> None:
        payload = build_event_payload(
            event_type="buy_signal",
            symbol="ZM",
            summary="ZM 已进入 buy_ready",
            correlation_id="cid-1",
            facts={"total_score": 84.6, "rank_in_scope": 2},
            actions=[{"action": "view_dashboard", "label": "查看看板"}],
        )
        first = create_notification_event(
            event_type="buy_signal",
            payload=payload,
            correlation_id="cid-1",
            symbol="ZM",
            dedupe_key="buy_signal:ZM:test",
            paths=self.paths,
        )
        second = create_notification_event(
            event_type="buy_signal",
            payload=payload,
            correlation_id="cid-1",
            symbol="ZM",
            dedupe_key="buy_signal:ZM:test",
            paths=self.paths,
        )
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["id"], second["id"])

    def test_build_gate_events_payload(self) -> None:
        blocked = build_event_payload(
            event_type="gate_blocked",
            symbol="ZM",
            summary="ZM 交易门槛受阻",
            correlation_id="cid-gate-1",
            facts={"trade_gate_status": "blocked"},
        )
        unblocked = build_event_payload(
            event_type="gate_unblocked",
            symbol="ZM",
            summary="ZM 交易门槛已解除",
            correlation_id="cid-gate-2",
            facts={"trade_gate_status": "unblocked"},
        )
        self.assertEqual(blocked["event_type"], "gate_blocked")
        self.assertEqual(unblocked["event_type"], "gate_unblocked")

    def test_build_extended_event_payloads(self) -> None:
        strategy_hit = build_event_payload(
            event_type="strategy_hit",
            symbol="GOOD",
            summary="低估值高质量科技股 发现候选 1 只",
            correlation_id="cid-hit",
            facts={"candidate_count": 1, "top_symbol": "GOOD"},
        )
        daily_digest = build_event_payload(
            event_type="daily_digest",
            symbol=None,
            summary="定时筛选完成：low_valuation_quality",
            correlation_id="cid-digest",
            facts={"top_n": 10},
        )
        self.assertEqual(strategy_hit["template_name"], "tpl_strategy_hit")
        self.assertEqual(daily_digest["template_name"], "tpl_daily_digest")
        self.assertEqual(daily_digest["event_type"], "daily_digest")

    def test_send_notification_event_marks_sent(self) -> None:
        payload = build_event_payload(
            event_type="system_error",
            symbol=None,
            summary="研究队列积压超过阈值",
            correlation_id="cid-2",
            facts={"error_type": "queue_backlog", "job_id": "research_queue", "retry_count": 0},
            actions=[{"action": "view_log", "label": "查看日志"}],
        )
        created = create_notification_event(
            event_type="system_error",
            payload=payload,
            correlation_id="cid-2",
            dedupe_key="system_error:queue_backlog:cid-2",
            paths=self.paths,
        )

        calls = {}

        def sender(title: str, lines: list[str], webhook_url: str) -> dict[str, object]:
            calls["title"] = title
            calls["lines"] = lines
            calls["webhook_url"] = webhook_url
            return {"ok": True}

        result = send_notification_event(
            notification_id=created["id"],
            webhook_url="https://example.com/hook",
            paths=self.paths,
            sender=sender,
        )
        self.assertTrue(result["sent"])
        self.assertIn("queue_backlog", "\n".join(calls["lines"]))

        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT send_status, sent_at FROM notification_event WHERE id = ?",
                (created["id"],),
            ).fetchone()
            self.assertEqual(row[0], "sent")
            self.assertIsNotNone(row[1])


if __name__ == "__main__":
    unittest.main()
