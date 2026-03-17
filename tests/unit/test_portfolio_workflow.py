from __future__ import annotations

from datetime import datetime
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


class PortfolioWorkflowTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_trade_lifecycle_roundtrip(self) -> None:
        record_buy(symbol='TST', price=100, quantity=10, paths=self.paths)
        with get_connection(self.paths) as connection:
            state = connection.execute("SELECT lifecycle_state FROM stock_master WHERE symbol='TST'").fetchone()[0]
        self.assertEqual(state, 'holding')

        trigger_exit_watch(symbol='TST', reason='unit-test', paths=self.paths)
        with get_connection(self.paths) as connection:
            state = connection.execute("SELECT lifecycle_state FROM stock_master WHERE symbol='TST'").fetchone()[0]
        self.assertEqual(state, 'exit_watch')

        record_sell(symbol='TST', price=120, quantity=10, paths=self.paths)
        with get_connection(self.paths) as connection:
            state = connection.execute("SELECT lifecycle_state FROM stock_master WHERE symbol='TST'").fetchone()[0]
            trades = connection.execute("SELECT COUNT(*) FROM trade_log WHERE symbol='TST'").fetchone()[0]
        self.assertEqual(state, 'exited')
        self.assertEqual(trades, 2)

        archive_after_review(symbol='TST', summary='完成复盘', outcome='good', paths=self.paths)
        with get_connection(self.paths) as connection:
            state = connection.execute("SELECT lifecycle_state FROM stock_master WHERE symbol='TST'").fetchone()[0]
            changes = connection.execute("SELECT COUNT(*) FROM suggested_change WHERE symbol='TST'").fetchone()[0]
        self.assertEqual(state, 'archived')
        self.assertEqual(changes, 1)
