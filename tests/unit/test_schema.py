from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import append_audit_log, ensure_schema, get_connection  # noqa: E402
from us_stock_research.utils import new_correlation_id  # noqa: E402


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


class SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def table_names(self) -> set[str]:
        with get_connection(self.paths) as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def test_ensure_schema_creates_phase1_tables(self) -> None:
        names = self.table_names()

        self.assertIn("stock_master", names)
        self.assertIn("strategy_hit", names)
        self.assertIn("scoring_breakdown", names)
        self.assertIn("ranking_snapshot", names)
        self.assertIn("audit_log", names)

    def test_get_connection_uses_wal_mode(self) -> None:
        with get_connection(self.paths) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(str(journal_mode).lower(), "wal")

    def test_append_audit_log_persists_json_payload(self) -> None:
        correlation_id = new_correlation_id()
        append_audit_log(
            entity_type="stock",
            entity_key="AAPL",
            action="state_changed",
            previous_state="discovered",
            new_state="shortlisted",
            correlation_id=correlation_id,
            payload={"source": "unit-test", "rank": 1},
            paths=self.paths,
        )

        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT entity_type, entity_key, action, previous_state, new_state, correlation_id, payload_json FROM audit_log"
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "stock")
        self.assertEqual(row[1], "AAPL")
        self.assertEqual(row[2], "state_changed")
        self.assertEqual(row[3], "discovered")
        self.assertEqual(row[4], "shortlisted")
        self.assertEqual(row[5], correlation_id)
        self.assertEqual(json.loads(row[6]), {"rank": 1, "source": "unit-test"})

    def test_append_audit_log_rejects_empty_entity_type(self) -> None:
        with self.assertRaises(ValueError):
            append_audit_log(
                entity_type="",
                entity_key="AAPL",
                action="created",
                correlation_id=new_correlation_id(),
                paths=self.paths,
            )


if __name__ == "__main__":
    unittest.main()
