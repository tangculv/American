from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.position_manager import get_position, is_held, record_buy, record_sell  # noqa: E402


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


class PositionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _insert_stock(self, symbol: str = "AAPL") -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status)
                VALUES (?, ?, 'strategy', 0, 'watching')
                """,
                (symbol, f"{symbol} Inc"),
            )

    def test_single_buy(self) -> None:
        self._insert_stock("AAPL")
        record_buy("AAPL", 100.0, 10, "2026-03-16", paths=self.paths)

        position = get_position("AAPL", paths=self.paths)
        self.assertEqual(position["total_shares"], 10)
        self.assertEqual(position["avg_cost"], 100.0)
        self.assertEqual(position["status"], "open")

    def test_multiple_buys_weighted_avg(self) -> None:
        self._insert_stock("AAPL")
        record_buy("AAPL", 100.0, 10, "2026-03-16", paths=self.paths)
        record_buy("AAPL", 120.0, 20, "2026-03-17", paths=self.paths)

        position = get_position("AAPL", paths=self.paths)
        self.assertEqual(position["total_shares"], 30)
        self.assertAlmostEqual(position["avg_cost"], (1000.0 + 2400.0) / 30)

    def test_buy_creates_stock_master_if_missing(self) -> None:
        record_buy("MSFT", 200.0, 5, "2026-03-16", paths=self.paths)

        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT symbol, company_name, source, hit_count FROM stock_master WHERE symbol = 'MSFT'"
            ).fetchone()
        self.assertEqual(tuple(row), ("MSFT", "MSFT", "manual_entry", 0))

    def test_buy_updates_user_status_to_held(self) -> None:
        self._insert_stock("NVDA")
        record_buy("NVDA", 130.0, 3, "2026-03-16", paths=self.paths)

        with get_connection(self.paths) as connection:
            status = connection.execute(
                "SELECT user_status FROM stock_master WHERE symbol = 'NVDA'"
            ).fetchone()[0]
        self.assertEqual(status, "held")

    def test_buy_writes_trade_log(self) -> None:
        self._insert_stock("TSLA")
        record_buy("TSLA", 250.0, 4, "2026-03-16", reason="建仓", paths=self.paths)

        with get_connection(self.paths) as connection:
            row = connection.execute(
                "SELECT trade_type, trade_date, price, quantity, reason FROM trade_log WHERE symbol = 'TSLA'"
            ).fetchone()
        self.assertEqual(tuple(row), ("buy", "2026-03-16", 250.0, 4.0, "建仓"))

    def test_partial_sell(self) -> None:
        self._insert_stock("META")
        record_buy("META", 300.0, 10, "2026-03-16", paths=self.paths)
        record_sell("META", 320.0, 4, "2026-03-18", paths=self.paths)

        position = get_position("META", paths=self.paths)
        self.assertEqual(position["total_shares"], 6)
        self.assertEqual(position["status"], "open")

    def test_full_sell_closes_position(self) -> None:
        self._insert_stock("AMD")
        record_buy("AMD", 110.0, 8, "2026-03-16", paths=self.paths)
        record_sell("AMD", 120.0, 8, "2026-03-19", paths=self.paths)

        position = get_position("AMD", paths=self.paths)
        self.assertEqual(position["status"], "closed")
        self.assertEqual(position["total_shares"], 0)
        with get_connection(self.paths) as connection:
            status = connection.execute(
                "SELECT user_status FROM stock_master WHERE symbol = 'AMD'"
            ).fetchone()[0]
        self.assertEqual(status, "closed")

    def test_full_sell_closes_alerts(self) -> None:
        self._insert_stock("NFLX")
        record_buy("NFLX", 400.0, 6, "2026-03-16", paths=self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO alert_event (symbol, signal_type, signal_level, action, status, triggered_at)
                VALUES
                ('NFLX', '阶段回撤', 'warning', '重点关注', 'triggered', '2026-03-17T09:30:00'),
                ('NFLX', '目标价达成', 'action', '考虑减仓', 'notified', '2026-03-17T10:00:00'),
                ('NFLX', '旧预警', 'warning', '继续观察', 'expired', '2026-03-15T10:00:00')
                """
            )
        record_sell("NFLX", 410.0, 6, "2026-03-18", paths=self.paths)

        with get_connection(self.paths) as connection:
            rows = connection.execute(
                "SELECT status FROM alert_event WHERE symbol = 'NFLX' ORDER BY id"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["resolved", "resolved", "expired"])

    def test_realized_pnl_calculation(self) -> None:
        self._insert_stock("GOOG")
        record_buy("GOOG", 100.0, 10, "2026-03-16", paths=self.paths)
        record_buy("GOOG", 200.0, 10, "2026-03-17", paths=self.paths)
        record_sell("GOOG", 180.0, 5, "2026-03-18", paths=self.paths)

        position = get_position("GOOG", paths=self.paths)
        self.assertAlmostEqual(position["avg_cost"], 150.0)
        self.assertAlmostEqual(position["realized_pnl"], 150.0)

    def test_sell_more_than_held(self) -> None:
        self._insert_stock("INTC")
        record_buy("INTC", 20.0, 5, "2026-03-16", paths=self.paths)
        record_sell("INTC", 22.0, 10, "2026-03-18", paths=self.paths)

        position = get_position("INTC", paths=self.paths)
        self.assertEqual(position["status"], "closed")
        self.assertEqual(position["total_shares"], 0)

    def test_position_after_buy_sell_buy(self) -> None:
        self._insert_stock("BABA")
        record_buy("BABA", 80.0, 10, "2026-03-16", paths=self.paths)
        record_sell("BABA", 100.0, 5, "2026-03-17", paths=self.paths)
        record_buy("BABA", 120.0, 10, "2026-03-18", paths=self.paths)

        position = get_position("BABA", paths=self.paths)
        self.assertEqual(position["total_shares"], 15)
        self.assertAlmostEqual(position["avg_cost"], (800.0 + 1200.0) / 20)
        self.assertAlmostEqual(position["realized_pnl"], (100.0 - 100.0) * 5)

    def test_get_position_nonexistent(self) -> None:
        self.assertIsNone(get_position("NONE", paths=self.paths))

    def test_is_held(self) -> None:
        self._insert_stock("ORCL")
        self.assertFalse(is_held("ORCL", paths=self.paths))
        record_buy("ORCL", 90.0, 7, "2026-03-16", paths=self.paths)
        self.assertTrue(is_held("ORCL", paths=self.paths))
        record_sell("ORCL", 95.0, 7, "2026-03-17", paths=self.paths)
        self.assertFalse(is_held("ORCL", paths=self.paths))
        self.assertFalse(is_held("MISSING", paths=self.paths))


if __name__ == "__main__":
    unittest.main()
