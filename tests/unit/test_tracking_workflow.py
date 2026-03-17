from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.tracking_workflow import refresh_holding_tracking  # noqa: E402


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


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def company_screener(self, **kwargs):
        return [
            {
                'symbol': 'HLD',
                'companyName': 'Holding Corp',
                'sector': 'Technology',
                'exchange': 'NASDAQ',
                'price': 120,
                'marketCap': 15000000000,
                'volume': 3000000,
            }
        ]

    def ratios_ttm(self, symbol: str):
        return {
            'priceToEarningsRatioTTM': 12,
            'priceToBookRatioTTM': 2,
            'returnOnEquityTTM': 0.18,
            'netProfitMarginTTM': 0.2,
            'debtToEquityRatioTTM': 0.4,
            'currentRatioTTM': 1.8,
            'enterpriseValueMultipleTTM': 10,
        }

    def historical_price_full(self, symbol: str):
        rows = []
        base = 120.0
        for i in range(260):
            close = base - (i * 0.1)
            rows.append({'close': close, 'high': close * 1.01, 'low': close * 0.99, 'volume': 2500000, 'date': f'2026-01-{(i%28)+1:02d}'})
        return rows


class GateFlipClient(FakeClient):
    def company_screener(self, **kwargs):
        rows = super().company_screener(**kwargs)
        rows[0]['price'] = 85
        rows[0]['volume'] = 3500000
        return rows

    def historical_price_full(self, symbol: str):
        rows = []
        recent = [85.0, 84.8, 84.5, 84.1, 83.8, 83.2, 82.9, 82.5, 82.0, 81.5,
                  81.0, 80.7, 80.4, 80.1, 79.8, 79.5, 79.2, 79.0, 78.8, 78.6,
                  78.5, 78.4, 78.3, 78.2, 78.1, 78.0, 77.9, 77.8, 77.7, 77.6,
                  77.5, 77.4, 77.3, 77.2, 77.1, 77.0, 76.9, 76.8, 76.7, 76.6,
                  76.5, 76.4, 76.3, 76.2, 76.1, 76.0, 75.9, 75.8, 75.7, 75.6,
                  75.5, 75.4, 75.3, 75.2, 75.1, 75.0, 74.9, 74.8, 74.7, 74.6,
                  74.5, 74.4, 74.3, 74.2, 74.1, 74.0, 73.9, 73.8, 73.7, 73.6,
                  73.5, 73.4, 73.3, 73.2, 73.1, 73.0, 72.9, 72.8, 72.7, 72.6,
                  72.5, 72.4, 72.3, 72.2, 72.1, 72.0, 71.9, 71.8, 71.7, 71.6,
                  71.5, 71.4, 71.3, 71.2, 71.1, 71.0, 70.9, 70.8, 70.7, 70.6,
                  70.5, 70.4, 70.3, 70.2, 70.1, 70.0, 69.9, 69.8, 69.7, 69.6,
                  69.5, 69.4, 69.3, 69.2, 69.1, 69.0, 68.9, 68.8, 68.7, 68.6,
                  68.5, 68.4, 68.3, 68.2, 68.1, 68.0, 67.9, 67.8, 67.7, 67.6,
                  67.5, 67.4, 67.3, 67.2, 67.1, 67.0, 66.9, 66.8, 66.7, 66.6,
                  66.5, 66.4, 66.3, 66.2, 66.1, 66.0, 65.9, 65.8, 65.7, 65.6,
                  65.5, 65.4, 65.3, 65.2, 65.1, 65.0, 64.9, 64.8, 64.7, 64.6,
                  64.5, 64.4, 64.3, 64.2, 64.1, 64.0, 63.9, 63.8, 63.7, 63.6,
                  63.5, 63.4, 63.3, 63.2, 63.1, 63.0, 62.9, 62.8, 62.7, 62.6,
                  62.5, 62.4, 62.3, 62.2, 62.1, 62.0, 61.9, 61.8, 61.7, 61.6,
                  61.5, 61.4, 61.3, 61.2, 61.1, 61.0, 60.9, 60.8, 60.7, 60.6,
                  60.5, 60.4, 60.3, 60.2, 60.1, 60.0]
        for i, close in enumerate(recent):
            rows.append({'close': close, 'high': close * 1.01, 'low': close * 0.99, 'volume': 3500000, 'date': f'2026-02-{(i%28)+1:02d}'})
        return rows


class VolatileClient(FakeClient):
    def company_screener(self, **kwargs):
        rows = super().company_screener(**kwargs)
        rows[0]['price'] = 132
        rows[0]['volume'] = 4200000
        return rows

    def historical_price_full(self, symbol: str):
        rows = []
        closes = [132.0, 131.5, 131.0, 130.0, 129.0, 128.0, 127.0, 126.0, 125.0, 124.0,
                  123.0, 122.5, 122.0, 121.8, 121.5, 121.2, 121.0, 120.8, 120.5, 120.2,
                  120.0, 119.8, 119.5, 119.2, 119.0, 118.8, 118.5, 118.2, 118.0, 117.8,
                  117.5, 117.2, 117.0, 116.8, 116.5, 116.2, 116.0, 115.8, 115.5, 115.2] + [115.0 - i*0.1 for i in range(220)]
        for i, close in enumerate(closes[:260]):
            rows.append({'close': close, 'high': close * 1.01, 'low': close * 0.99, 'volume': 4200000, 'date': f'2026-02-{(i%28)+1:02d}'})
        return rows


class TrackingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, sector, exchange, market_cap, avg_volume, lifecycle_state, current_state)
                VALUES ('HLD', 'Holding Corp', 'Technology', 'NASDAQ', 10000000000, 2000000, 'holding', 'holding')
                """
            )
            connection.execute(
                "INSERT INTO trade_log (symbol, trade_type, trade_date, price, quantity, fees, notes) VALUES ('HLD', 'buy', '2026-03-01T00:00:00', 100, 10, 0, '')"
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch('us_stock_research.tracking_workflow.FMPClient', FakeClient)
    def test_refresh_holding_tracking_updates_db(self) -> None:
        result = refresh_holding_tracking(symbol='HLD', paths=self.paths)
        self.assertEqual(result['symbol'], 'HLD')
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT current_price, latest_score, latest_signal FROM stock_master WHERE symbol='HLD'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(float(row[0]), 120.0)
        self.assertIsNotNone(row[1])
        self.assertTrue(str(row[2]))

    @patch('us_stock_research.tracking_workflow.FMPClient', GateFlipClient)
    def test_refresh_holding_tracking_emits_gate_unblocked_notification(self) -> None:
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE stock_master SET trade_gate_blocked = 1 WHERE symbol='HLD'")
        result = refresh_holding_tracking(symbol='HLD', paths=self.paths)
        self.assertFalse(result['gate_blocked'])
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type FROM notification_event WHERE symbol='HLD' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 'gate_unblocked')

    @patch('us_stock_research.tracking_workflow.FMPClient', VolatileClient)
    def test_refresh_holding_tracking_emits_price_and_score_notifications(self) -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                "UPDATE stock_master SET latest_score = 50, current_price = 120, trade_gate_blocked = 0 WHERE symbol='HLD'"
            )
        result = refresh_holding_tracking(symbol='HLD', paths=self.paths)
        self.assertEqual(result['symbol'], 'HLD')
        with get_connection(self.paths) as connection:
            rows = connection.execute(
                "SELECT event_type FROM notification_event WHERE symbol='HLD' ORDER BY id DESC LIMIT 5"
            ).fetchall()
        event_types = [row[0] for row in rows]
        self.assertIn('price_alert', event_types)
        self.assertIn('score_change_significant', event_types)
