from __future__ import annotations

from datetime import datetime
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
from us_stock_research.models.screening_repo import persist_screening_run  # noqa: E402
from us_stock_research.ranking_workflow import build_ranking_snapshot  # noqa: E402
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


def stock(symbol: str, score: float, research: float, technical: float, state: str = "shortlisted") -> dict[str, object]:
    return {
        "symbol": symbol,
        "companyName": f"{symbol} Inc.",
        "sector": "Technology",
        "exchangeShortName": "NASDAQ",
        "marketCap": 20_000_000_000,
        "volume": 3_000_000,
        "avgVolume": 3_000_000,
        "price": 100.0,
        "ratios": {
            "roeRatioTTM": 0.18,
            "netProfitMarginTTM": 0.21,
            "debtToEquityRatioTTM": 0.3,
            "currentRatioTTM": 2.0,
            "priceToEarningsRatioTTM": 12.0,
            "priceToBookRatioTTM": 2.0,
            "enterpriseValueMultipleTTM": 10.0,
        },
        "score": score,
        "scoreDetail": {
            "eligibility": {"passed": True, "reasons": ["通过估值门槛"]},
            "tier": {"code": "strict_pass", "label": "严格通过", "summary": "通过"},
        },
        "_expected_state": state,
        "_expected_research": research,
        "_expected_technical": technical,
    }


class RankingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def seed(self) -> None:
        stocks = [
            stock("AAA", 88.0, 70.0, 60.0),
            stock("BBB", 88.0, 68.0, 65.0),
            stock("CCC", 79.0, 60.0, 55.0),
        ]
        persist_screening_run(
            strategy_key="low_valuation_quality",
            strategy_display_name="低估值高质量科技股",
            screened_stocks=stocks,
            ranked_stocks=stocks,
            generated_at=datetime(2026, 3, 15, 12, 0, 0),
            correlation_id=new_correlation_id(),
            ranking={"top_n": 3},
            paths=self.paths,
        )
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE stock_master SET lifecycle_state='queued_for_research', current_state='queued_for_research', trade_gate_blocked=0 WHERE symbol IN ('AAA','BBB')")
            connection.execute("UPDATE stock_master SET lifecycle_state='buy_ready', current_state='buy_ready', trade_gate_blocked=0 WHERE symbol='CCC'")
            connection.execute("UPDATE scoring_breakdown SET total_score=88.0, research_conclusion=70.0, technical_timing=60.0 WHERE symbol='AAA'")
            connection.execute("UPDATE scoring_breakdown SET total_score=88.0, research_conclusion=68.0, technical_timing=65.0 WHERE symbol='BBB'")
            connection.execute("UPDATE scoring_breakdown SET total_score=79.0, research_conclusion=60.0, technical_timing=55.0 WHERE symbol='CCC'")

    def test_build_research_priority_snapshot_with_tie_break(self) -> None:
        self.seed()
        result = build_ranking_snapshot(scope="research_priority", paths=self.paths, correlation_id=new_correlation_id())
        self.assertEqual(result["universe_size"], 2)
        with get_connection(self.paths) as connection:
            rows = connection.execute(
                "SELECT symbol, rank, universe_size, rank_percentile, trade_gate_status, actionable, tie_break_trace_json FROM ranking_snapshot WHERE snapshot_batch_id = ? ORDER BY rank",
                (result["snapshot_batch_id"],),
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["AAA", "BBB"])
        self.assertEqual(int(rows[0][2]), 2)
        self.assertEqual(round(float(rows[0][3]), 2), 100.0)
        self.assertEqual(round(float(rows[1][3]), 2), 50.0)
        self.assertEqual(rows[0][4], "unblocked")
        self.assertEqual(int(rows[0][5]), 1)
        self.assertIn("research_conclusion", rows[0][6])

    def test_build_buy_priority_snapshot(self) -> None:
        self.seed()
        result = build_ranking_snapshot(scope="buy_priority", paths=self.paths, correlation_id=new_correlation_id())
        self.assertEqual(result["universe_size"], 1)
        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT symbol, rank, actionable FROM ranking_snapshot WHERE snapshot_batch_id = ?",
                (result["snapshot_batch_id"],),
            ).fetchone()
        self.assertEqual(row[0], "CCC")
        self.assertEqual(int(row[1]), 1)
        self.assertEqual(int(row[2]), 1)

    def test_build_ranking_snapshot_emits_score_change_significant(self) -> None:
        self.seed()
        build_ranking_snapshot(scope="buy_priority", paths=self.paths, correlation_id=new_correlation_id())
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE scoring_breakdown SET total_score = total_score + 8 WHERE symbol='CCC'")
        with unittest.mock.patch('us_stock_research.ranking_workflow._utc_now_iso', return_value='2026-03-15T12:00:01'):
            build_ranking_snapshot(scope="buy_priority", paths=self.paths, correlation_id=new_correlation_id())
        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT event_type, symbol FROM notification_event WHERE event_type='score_change_significant' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'score_change_significant')
        self.assertEqual(row[1], 'CCC')


if __name__ == "__main__":
    unittest.main()
