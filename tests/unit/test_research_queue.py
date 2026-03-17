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
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.research_queue import (  # noqa: E402
    BACKLOG_ALERT_THRESHOLD,
    claim_next_research_task,
    enqueue_queue_task,
    mark_research_task_failed,
    reorder_research_queue,
    run_daily_recovery_reorder,
)


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


class ResearchQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_enqueue_reorders_by_priority(self) -> None:
        enqueue_queue_task(symbol="P2A", trigger_type="expired", trigger_priority="P2", strategy_id="s1", correlation_id="cid-1", paths=self.paths)
        enqueue_queue_task(symbol="P1A", trigger_type="new_entry", trigger_priority="P1-A", strategy_id="s1", correlation_id="cid-2", paths=self.paths)
        enqueue_queue_task(symbol="P0A", trigger_type="manual", trigger_priority="P0", strategy_id="s1", correlation_id="cid-3", paths=self.paths)

        ordered = reorder_research_queue(paths=self.paths, correlation_id="cid-4")
        self.assertEqual([task.symbol for task in ordered], ["P0A", "P1A", "P2A"])

    def test_claim_next_task_claims_highest_priority(self) -> None:
        enqueue_queue_task(symbol="LOW", trigger_type="expired", trigger_priority="P2", strategy_id="s1", correlation_id="cid-1", paths=self.paths)
        enqueue_queue_task(symbol="HIGH", trigger_type="crash", trigger_priority="P1-B", strategy_id="s1", correlation_id="cid-2", paths=self.paths, extra_payload={"crash_pct": 12})

        task = claim_next_research_task(paths=self.paths, correlation_id="cid-3")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.symbol, "HIGH")
        self.assertEqual(task.status, "in_progress")

    def test_failed_task_retries_and_degrades_priority(self) -> None:
        task_id = enqueue_queue_task(symbol="ZM", trigger_type="manual", trigger_priority="P0", strategy_id="s1", correlation_id="cid-1", paths=self.paths)

        first = mark_research_task_failed(task_id=task_id, error_message="429", correlation_id="cid-2", paths=self.paths)
        second = mark_research_task_failed(task_id=task_id, error_message="429", correlation_id="cid-3", paths=self.paths)
        third = mark_research_task_failed(task_id=task_id, error_message="429", correlation_id="cid-4", paths=self.paths)
        fourth = mark_research_task_failed(task_id=task_id, error_message="fatal", correlation_id="cid-5", paths=self.paths)

        self.assertEqual(first["next_status"], "retry_pending")
        self.assertEqual(second["next_status"], "retry_pending")
        self.assertEqual(third["next_priority"], "P1-A")
        self.assertEqual(fourth["next_status"], "failed")

        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT status, retry_count, trigger_priority FROM research_snapshot WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertEqual(int(row[1]), 4)
        self.assertEqual(row[2], "P1-A")

    def test_soft_budget_blocks_p2_but_allows_p1(self) -> None:
        for idx in range(20):
            with get_connection(self.paths) as connection:
                connection.execute(
                    "INSERT INTO audit_log (entity_type, entity_key, action, correlation_id, payload_json, created_at) VALUES ('research_queue', ?, 'research_queue_claimed', ?, '{}', '2026-03-14T08:00:00')",
                    (f'PRE{idx}', f'pre-{idx}'),
                )
        enqueue_queue_task(symbol="P2A", trigger_type="expired", trigger_priority="P2", strategy_id="s1", correlation_id="cid-p2", paths=self.paths)
        self.assertIsNone(claim_next_research_task(paths=self.paths, correlation_id="cid-claim-p2"))
        enqueue_queue_task(symbol="P1A", trigger_type="new_entry", trigger_priority="P1-A", strategy_id="s1", correlation_id="cid-p1", paths=self.paths)
        task = claim_next_research_task(paths=self.paths, correlation_id="cid-claim-p1")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.symbol, "P1A")

    def test_backlog_creates_system_error_notification(self) -> None:
        for idx in range(BACKLOG_ALERT_THRESHOLD + 1):
            enqueue_queue_task(symbol=f"Q{idx:03d}", trigger_type="expired", trigger_priority="P2", strategy_id="s1", correlation_id=f"cid-{idx}", paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type, send_status FROM notification_event WHERE event_type = 'system_error' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'system_error')
        self.assertEqual(row[1], 'pending')

    def test_daily_recovery_reorder_writes_audit(self) -> None:
        enqueue_queue_task(symbol="P2A", trigger_type="expired", trigger_priority="P2", strategy_id="s1", correlation_id="cid-1", paths=self.paths)
        result = run_daily_recovery_reorder(paths=self.paths, correlation_id="cid-recover", as_of="2026-03-15T09:00:00-04:00")
        self.assertEqual(result["budget"]["soft_budget"], 20)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT action FROM audit_log WHERE action='research_queue_daily_recovery_reordered' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], 'research_queue_daily_recovery_reordered')


if __name__ == "__main__":
    unittest.main()
