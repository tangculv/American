from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.cli import write_outputs as real_write_outputs  # noqa: E402
from us_stock_research.config import AppSettings, ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.service import ScreeningServiceError, run_screening  # noqa: E402


class FixedDateTime(__import__("datetime").datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 12, 20, 30, 0, tzinfo=tz)


class StubFMPClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def company_screener(self, **kwargs):
        return [
            {
                "symbol": "GOOD",
                "companyName": "Good Corp",
                "marketCap": 20_000_000_000,
                "price": 100.0,
                "sector": "Technology",
                "exchange": "NASDAQ",
            },
            {
                "symbol": "BAD",
                "companyName": "Bad Corp",
                "marketCap": 30_000_000_000,
                "price": 200.0,
                "sector": "Technology",
                "exchange": "NASDAQ",
            },
        ]

    def ratios_ttm(self, symbol: str):
        payloads = {
            "GOOD": {
                "priceToEarningsRatioTTM": 12.0,
                "priceToBookRatioTTM": 1.8,
                "roeRatioTTM": 0.18,
                "netProfitMarginTTM": 0.22,
                "debtToEquityRatioTTM": 0.35,
                "currentRatioTTM": 2.1,
            },
            "BAD": {
                "priceToEarningsRatioTTM": 80.0,
                "priceToBookRatioTTM": 12.0,
                "roeRatioTTM": 0.28,
                "netProfitMarginTTM": 0.30,
                "debtToEquityRatioTTM": 0.20,
                "currentRatioTTM": 3.0,
            },
        }
        return payloads.get(symbol)


class RejectOnlyFMPClient(StubFMPClient):
    def company_screener(self, **kwargs):
        return [
            {
                "symbol": "BAD",
                "companyName": "Bad Corp",
                "marketCap": 30_000_000_000,
                "price": 200.0,
                "sector": "Technology",
                "exchange": "NASDAQ",
            }
        ]



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


class ServicePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        self.paths.ensure()
        ensure_schema(self.paths)
        self.strategy = {
            "name": "低估值高质量科技股",
            "screen": {
                "limit": 50,
                "market_cap_min": 500_000_000,
                "market_cap_max": 100_000_000_000,
                "volume_min": 1_000_000,
                "sector": "Technology",
                "exchange": "NASDAQ",
            },
            "ranking": {
                "top_n": 10,
                "notes": "PE/PB + ROE + 财务健康 + 市值",
                "gates": {
                    "max_pe": 30,
                    "max_pb": 5,
                    "min_valuation_score": 2,
                    "require_positive_pe": True,
                    "require_positive_pb": True,
                    "min_roe_for_quality": 0.10,
                },
            },
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_run_screening_persists_db_before_writing_outputs(self) -> None:
        observed: dict[str, int] = {}

        def wrapped_write_outputs(paths: ProjectPaths, stocks, strategy_name: str, timestamp=None):
            with get_connection(self.paths) as connection:
                observed["stock_master"] = int(connection.execute("SELECT COUNT(*) FROM stock_master").fetchone()[0])
                observed["strategy_hit"] = int(connection.execute("SELECT COUNT(*) FROM strategy_hit").fetchone()[0])
                observed["scoring_breakdown"] = int(connection.execute("SELECT COUNT(*) FROM scoring_breakdown").fetchone()[0])
                observed["ranking_snapshot"] = int(connection.execute("SELECT COUNT(*) FROM ranking_snapshot").fetchone()[0])
            return real_write_outputs(paths, stocks, strategy_name, timestamp=timestamp)

        with patch("us_stock_research.service.load_settings", return_value=AppSettings(fmp_api_key="demo")), patch(
            "us_stock_research.service.load_strategy",
            return_value=self.strategy,
        ), patch("us_stock_research.service.FMPClient", StubFMPClient), patch(
            "us_stock_research.service.datetime",
            FixedDateTime,
        ), patch("us_stock_research.cli.write_outputs", side_effect=wrapped_write_outputs):
            result = run_screening("low_valuation_quality", top_n=1, paths=self.paths)

        self.assertEqual(result["stockCount"], 1)
        self.assertEqual([stock["symbol"] for stock in result["stocks"]], ["GOOD"])
        self.assertEqual(observed, {
            "stock_master": 2,
            "strategy_hit": 2,
            "scoring_breakdown": 2,
            "ranking_snapshot": 1,
        })

        with get_connection(self.paths) as connection:
            stock_rows = connection.execute(
                "SELECT symbol, current_state FROM stock_master ORDER BY symbol"
            ).fetchall()
            audit_actions = connection.execute(
                "SELECT action FROM audit_log ORDER BY id"
            ).fetchall()

            notification_rows = connection.execute(
                "SELECT event_type, symbol FROM notification_event ORDER BY id"
            ).fetchall()

        self.assertTrue(any(str(row[0]) == "strategy_hit" and str(row[1]) == "GOOD" for row in notification_rows))

        self.assertEqual([(str(row[0]), str(row[1])) for row in stock_rows], [("BAD", "rejected"), ("GOOD", "shortlisted")])
        self.assertIn("screening_persisted", [str(row[0]) for row in audit_actions])
        self.assertTrue(Path(result["outputs"]["json"]).exists())
        payload = json.loads(Path(result["outputs"]["json"]).read_text(encoding="utf-8"))
        self.assertEqual([item["symbol"] for item in payload], ["GOOD"])

    def test_run_screening_persists_rejections_even_when_no_ranked_output(self) -> None:
        with patch("us_stock_research.service.load_settings", return_value=AppSettings(fmp_api_key="demo")), patch(
            "us_stock_research.service.load_strategy",
            return_value=self.strategy,
        ), patch("us_stock_research.service.FMPClient", RejectOnlyFMPClient), patch(
            "us_stock_research.service.datetime",
            FixedDateTime,
        ):
            with self.assertRaises(ScreeningServiceError):
                run_screening("low_valuation_quality", top_n=1, paths=self.paths)

        with get_connection(self.paths) as connection:
            stock_rows = connection.execute(
                "SELECT symbol, current_state FROM stock_master ORDER BY symbol"
            ).fetchall()
            strategy_hits = int(connection.execute("SELECT COUNT(*) FROM strategy_hit").fetchone()[0])
            scoring_rows = int(connection.execute("SELECT COUNT(*) FROM scoring_breakdown").fetchone()[0])
            ranking_rows = int(connection.execute("SELECT COUNT(*) FROM ranking_snapshot").fetchone()[0])

        self.assertEqual([(str(row[0]), str(row[1])) for row in stock_rows], [("BAD", "rejected")])
        self.assertEqual(strategy_hits, 1)
        self.assertEqual(scoring_rows, 1)
        self.assertEqual(ranking_rows, 0)


if __name__ == "__main__":
    unittest.main()
