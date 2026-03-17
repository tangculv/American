from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.lifecycle import PHASE1_STATES, TRANSITION_RULES, transition_stock_state, validate_transition  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
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


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def audit_rows(self) -> list[tuple[str, str, str, str, str]]:
        with get_connection(self.paths) as connection:
            rows = connection.execute(
                "SELECT entity_key, action, previous_state, new_state, payload_json FROM audit_log ORDER BY id"
            ).fetchall()
        return [(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])) for row in rows]

    def test_phase1_state_catalog_contains_all_prd_states(self) -> None:
        self.assertEqual(
            PHASE1_STATES,
            (
                "discovered",
                "shortlisted",
                "rejected",
                "queued_for_research",
                "researched",
                "scored",
                "waiting_for_setup",
                "buy_ready",
                "holding",
                "exit_watch",
                "exited",
                "archived",
            ),
        )

    def test_validate_transition_accepts_all_declared_legal_paths(self) -> None:
        for from_state, targets in TRANSITION_RULES.items():
            for to_state in targets:
                ok, reason = validate_transition(from_state, to_state)
                self.assertTrue(ok, msg=f"expected legal transition for {from_state} -> {to_state}: {reason}")
                self.assertEqual(reason, "ok")

    def test_validate_transition_rejects_reversed_or_skipped_paths(self) -> None:
        invalid_paths = [
            ("discovered", "queued_for_research"),
            ("shortlisted", "buy_ready"),
            ("scored", "holding"),
            ("holding", "buy_ready"),
            ("archived", "holding"),
            ("rejected", "archived"),
        ]
        for from_state, to_state in invalid_paths:
            ok, reason = validate_transition(from_state, to_state)
            self.assertFalse(ok)
            self.assertIn(f"{from_state} -> {to_state}", reason)

    def test_validate_transition_rejects_same_state(self) -> None:
        ok, reason = validate_transition("holding", "holding")
        self.assertFalse(ok)
        self.assertIn("holding -> holding", reason)

    def test_transition_stock_state_writes_audit_log(self) -> None:
        correlation_id = new_correlation_id()
        result = transition_stock_state(
            symbol="NVDA",
            from_state="discovered",
            to_state="shortlisted",
            trigger_source="screening_score",
            correlation_id=correlation_id,
            payload={"score": 78.5},
            paths=self.paths,
        )

        self.assertEqual(result["symbol"], "NVDA")
        self.assertEqual(result["from_state"], "discovered")
        self.assertEqual(result["to_state"], "shortlisted")

        rows = self.audit_rows()
        self.assertEqual(len(rows), 1)
        symbol, action, previous_state, new_state, payload_json = rows[0]
        self.assertEqual(symbol, "NVDA")
        self.assertEqual(action, "state_transition")
        self.assertEqual(previous_state, "discovered")
        self.assertEqual(new_state, "shortlisted")
        self.assertEqual(
            json.loads(payload_json),
            {
                "score": 78.5,
                "symbol": "NVDA",
                "trigger_source": "screening_score",
            },
        )

    def test_transition_stock_state_rejects_illegal_path_without_audit_log(self) -> None:
        with self.assertRaises(ValueError):
            transition_stock_state(
                symbol="AAPL",
                from_state="holding",
                to_state="buy_ready",
                trigger_source="manual_rewind",
                correlation_id=new_correlation_id(),
                paths=self.paths,
            )

        self.assertEqual(self.audit_rows(), [])


if __name__ == "__main__":
    unittest.main()
