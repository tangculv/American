from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.alert_engine import Signal  # noqa: E402
from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.tracking_workflow import (  # noqa: E402
    build_monitoring_snapshot,
    check_reresearch_trigger,
    run_daily_monitoring,
    write_daily_snapshot,
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


class FakeAlertEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, dict | None, dict | None]] = []

    def detect_signals(self, symbol: str, snapshot: dict, research: dict | None, position: dict | None) -> list[Signal]:
        self.calls.append((symbol, snapshot, research, position))
        if symbol == "AAPL":
            return [Signal(type="急跌预警", level="warning", action="重点关注", value=-5.5, threshold=-5.0)]
        return []


class ExplodingAlertEngine(FakeAlertEngine):
    def detect_signals(self, symbol: str, snapshot: dict, research: dict | None, position: dict | None) -> list[Signal]:
        if symbol == "AAPL":
            raise RuntimeError("boom")
        return super().detect_signals(symbol, snapshot, research, position)


class FakeAlertManager:
    def __init__(self, paths: ProjectPaths | None = None) -> None:
        self.paths = paths
        self.processed: list[tuple[str, list[Signal]]] = []

    def process_signals(self, symbol: str, new_signals: list[Signal]) -> None:
        self.processed.append((symbol, new_signals))


class TrackingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status) VALUES ('AAPL', 'Apple', 'strategy', 0, 'held')"
            )
            connection.execute(
                "INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status) VALUES ('MSFT', 'Microsoft', 'strategy', 0, 'held')"
            )
            connection.execute(
                "INSERT INTO position_summary (symbol, status, total_shares, avg_cost, first_buy_date, total_invested, realized_pnl) VALUES ('AAPL', 'open', 10, 100, '2026-03-01', 1000, 0)"
            )
            connection.execute(
                "INSERT INTO position_summary (symbol, status, total_shares, avg_cost, first_buy_date, total_invested, realized_pnl) VALUES ('MSFT', 'open', 5, 200, '2026-03-05', 1000, 0)"
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _insert_technical(self, symbol: str, snapshot_date: str, price: float, ma_50: float | None = 100.0, ma_200: float | None = 95.0, rsi_14: float | None = 55.0, ma_20_slope: float | None = 0.5, high_52w: float | None = 120.0, volume: int | None = 1000000, volume_ratio: float | None = 1.2, weekly_trend: str = "up") -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO technical_snapshot (
                    symbol, snapshot_date, price, ma_50, ma_200, rsi_14, ma_20_slope,
                    high_52w, volume, volume_ratio, weekly_trend, signal, gate_is_blocked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'wait', 0)
                """,
                (symbol, snapshot_date, price, ma_50, ma_200, rsi_14, ma_20_slope, high_52w, volume, volume_ratio, weekly_trend),
            )

    def test_build_snapshot_from_technical(self) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0, ma_50=102.0, ma_200=98.0)
        self._insert_technical("AAPL", "2026-03-16", 105.0, ma_50=103.0, ma_200=99.0, ma_20_slope=-0.3)
        snapshot = build_monitoring_snapshot("AAPL", paths=self.paths)
        self.assertEqual(snapshot["price"], 105.0)
        self.assertAlmostEqual(snapshot["daily_change_pct"], 5.0)
        self.assertEqual(snapshot["prev_ma_50"], 102.0)
        self.assertEqual(snapshot["prev_ma_200"], 98.0)
        self.assertEqual(snapshot["ma_50_slope"], -0.3)

    def test_build_snapshot_missing_data(self) -> None:
        snapshot = build_monitoring_snapshot("AAPL", paths=self.paths)
        self.assertIn("price", snapshot)
        self.assertIsNone(snapshot["price"])
        self.assertIsNone(snapshot["daily_change_pct"])
        self.assertIsNone(snapshot["ma_50"])

    def test_write_daily_snapshot(self) -> None:
        snapshot = {"price": 110.0, "daily_change_pct": 2.5, "volume": 1000000, "volume_ratio": 1.3}
        position = {"avg_cost": 100.0, "total_shares": 10, "first_buy_date": "2026-03-01"}
        write_daily_snapshot("AAPL", snapshot, position, paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT symbol, price, daily_change_pct, volume, volume_ratio FROM daily_position_snapshot WHERE symbol = 'AAPL'"
            ).fetchone()
        self.assertEqual(tuple(row), ("AAPL", 110.0, 2.5, 1000000, 1.3))

    def test_write_daily_snapshot_calculates_pnl(self) -> None:
        snapshot = {"price": 110.0, "daily_change_pct": 2.5, "volume": 1000000, "volume_ratio": 1.3}
        position = {"avg_cost": 100.0, "total_shares": 10, "first_buy_date": "2026-03-01"}
        write_daily_snapshot("AAPL", snapshot, position, paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT unrealized_pnl, unrealized_pnl_pct, holding_days FROM daily_position_snapshot WHERE symbol = 'AAPL'"
            ).fetchone()
        self.assertEqual(float(row[0]), 100.0)
        self.assertEqual(float(row[1]), 10.0)
        self.assertGreaterEqual(int(row[2]), 0)

    def test_reresearch_trigger_price_change_5pct(self) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0)
        self._insert_technical("AAPL", "2026-03-16", 105.0)
        snapshot = build_monitoring_snapshot("AAPL", paths=self.paths)
        self.assertTrue(check_reresearch_trigger("AAPL", snapshot, paths=self.paths))

    def test_reresearch_trigger_price_change_4pct(self) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0)
        self._insert_technical("AAPL", "2026-03-16", 104.0)
        snapshot = build_monitoring_snapshot("AAPL", paths=self.paths)
        self.assertFalse(check_reresearch_trigger("AAPL", snapshot, paths=self.paths))

    def test_reresearch_trigger_trend_reversal(self) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0, weekly_trend="up")
        self._insert_technical("AAPL", "2026-03-16", 101.0, weekly_trend="down")
        snapshot = build_monitoring_snapshot("AAPL", paths=self.paths)
        self.assertTrue(check_reresearch_trigger("AAPL", snapshot, paths=self.paths))

    def test_reresearch_trigger_same_trend(self) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0, weekly_trend="up")
        self._insert_technical("AAPL", "2026-03-16", 101.0, weekly_trend="up")
        snapshot = build_monitoring_snapshot("AAPL", paths=self.paths)
        self.assertFalse(check_reresearch_trigger("AAPL", snapshot, paths=self.paths))

    @patch("us_stock_research.tracking_workflow.refresh_holding_tracking")
    @patch("us_stock_research.tracking_workflow.AlertManager", FakeAlertManager)
    @patch("us_stock_research.tracking_workflow.AlertEngine", FakeAlertEngine)
    def test_monitoring_integrates_alert_engine(self, mock_refresh) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0)
        self._insert_technical("AAPL", "2026-03-16", 105.0)
        self._insert_technical("MSFT", "2026-03-15", 200.0)
        self._insert_technical("MSFT", "2026-03-16", 201.0)
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO research_analysis (research_snapshot_id, symbol, invalidation_conditions_json, confidence_score, next_review_date) VALUES (1, 'AAPL', '[]', 80, '2026-04-01')"
            )
        mock_refresh.side_effect = lambda symbol, paths=None: {"symbol": symbol}
        result = run_daily_monitoring(paths=self.paths)
        self.assertEqual(result["monitored"], 2)
        self.assertEqual(result["signals_detected"], 1)
        self.assertIn("AAPL", result["reresearch_triggered"])

    @patch("us_stock_research.tracking_workflow.refresh_holding_tracking")
    @patch("us_stock_research.tracking_workflow.AlertManager", FakeAlertManager)
    @patch("us_stock_research.tracking_workflow.AlertEngine", ExplodingAlertEngine)
    def test_monitoring_error_isolation(self, mock_refresh) -> None:
        self._insert_technical("AAPL", "2026-03-15", 100.0)
        self._insert_technical("AAPL", "2026-03-16", 105.0)
        self._insert_technical("MSFT", "2026-03-15", 200.0)
        self._insert_technical("MSFT", "2026-03-16", 201.0)
        mock_refresh.side_effect = lambda symbol, paths=None: {"symbol": symbol}
        result = run_daily_monitoring(paths=self.paths)
        self.assertEqual(result["monitored"], 2)
        self.assertEqual(result["signals_detected"], 0)
        self.assertEqual(result["reresearch_triggered"], [])
        with get_connection(self.paths) as connection:
            rows = connection.execute("SELECT COUNT(*) FROM daily_position_snapshot").fetchone()[0]
        self.assertEqual(rows, 2)


if __name__ == "__main__":
    unittest.main()
