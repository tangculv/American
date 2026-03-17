from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.portfolio_workflow import archive_after_review, record_buy, record_sell, trigger_exit_watch  # noqa: E402
from us_stock_research.review_workflow import list_pending_review_changes, update_suggested_change_status  # noqa: E402


def make_paths(root: Path) -> ProjectPaths:
    return ProjectPaths(
        root=root,
        config_dir=root / 'config',
        strategy_dir=root / 'config' / 'strategies',
        app_config_path=root / 'config' / 'app.yaml',
        outputs_dir=root / 'outputs' / 'fmp-screening',
        watchlist_dir=root / 'watchlist',
        data_dir=root / 'data',
        database_path=root / 'data' / 'stock_research.db',
        logs_dir=root / 'logs',
    )


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, sector, exchange, market_cap, avg_volume, lifecycle_state, current_state)
                VALUES ('TST', 'Test Corp', 'Technology', 'NASDAQ', 10000000000, 2000000, 'buy_ready', 'buy_ready')
                """
            )
        record_buy(symbol='TST', price=100, quantity=10, paths=self.paths)
        trigger_exit_watch(symbol='TST', reason='unit-test', paths=self.paths)
        record_sell(symbol='TST', price=120, quantity=10, paths=self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_archive_creates_pending_review_notification_and_change(self) -> None:
        archive_after_review(symbol='TST', summary='完成复盘', outcome='good', paths=self.paths)
        pending = list_pending_review_changes(paths=self.paths)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['symbol'], 'TST')
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type, symbol, send_status FROM notification_event WHERE event_type='review_pending'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 'review_pending')
            self.assertEqual(row[1], 'TST')
            self.assertEqual(row[2], 'pending')

    def test_review_decision_updates_status_and_audit(self) -> None:
        archive_after_review(symbol='TST', summary='完成复盘', outcome='good', paths=self.paths)
        pending = list_pending_review_changes(paths=self.paths)
        result = update_suggested_change_status(change_id=pending[0]['id'], decision='approved', reviewer='qa', note='looks good', paths=self.paths)
        self.assertTrue(result['changed'])
        self.assertEqual(result['status'], 'approved')
        second = update_suggested_change_status(change_id=pending[0]['id'], decision='approved', reviewer='qa', note='duplicate', paths=self.paths)
        self.assertFalse(second['changed'])
        with get_connection(self.paths) as connection:
            change = connection.execute("SELECT status, approved_at FROM suggested_change WHERE id = ?", (pending[0]['id'],)).fetchone()
            self.assertEqual(change[0], 'approved')
            self.assertIsNotNone(change[1])
            audit = connection.execute("SELECT action FROM audit_log WHERE entity_type='suggested_change' AND entity_key = ? ORDER BY id DESC", (str(pending[0]['id']),)).fetchone()
            self.assertEqual(audit[0], 'suggested_change_approved')


if __name__ == '__main__':
    unittest.main()
