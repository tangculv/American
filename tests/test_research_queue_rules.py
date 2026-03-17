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

from us_stock_research.config import AppSettings, ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.research_queue import (  # noqa: E402
    build_research_batch,
    execute_research_batch_serial,
    has_significant_change,
    increment_hit_count,
    should_research,
)
from us_stock_research.service import run_screening  # noqa: E402


class FixedDateTime(__import__("datetime").datetime):
    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 3, 12, 20, 30, 0)
        if tz is not None:
            return base.replace(tzinfo=tz)
        return base


class StubFMPClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def company_screener(self, **kwargs):
        return [
            {"symbol": "AAA", "companyName": "AAA Corp", "marketCap": 20_000_000_000, "price": 100.0, "sector": "Technology", "exchange": "NASDAQ"},
            {"symbol": "BBB", "companyName": "BBB Corp", "marketCap": 30_000_000_000, "price": 90.0, "sector": "Technology", "exchange": "NASDAQ"},
            {"symbol": "IGN", "companyName": "IGN Corp", "marketCap": 10_000_000_000, "price": 50.0, "sector": "Technology", "exchange": "NASDAQ"},
        ]

    def ratios_ttm(self, symbol: str):
        return {
            "priceToEarningsRatioTTM": 12.0,
            "priceToBookRatioTTM": 1.8,
            "roeRatioTTM": 0.18,
            "netProfitMarginTTM": 0.22,
            "debtToEquityRatioTTM": 0.35,
            "currentRatioTTM": 2.1,
        }


def fake_evaluate_candidates(client, candidates, ranking):
    payloads = {
        "AAA": {"symbol": "AAA", "companyName": "AAA Corp", "score": 95.0, "scoreDetail": {"eligibility": {"passed": True}, "tier": {"code": "pass"}}},
        "BBB": {"symbol": "BBB", "companyName": "BBB Corp", "score": 85.0, "scoreDetail": {"eligibility": {"passed": True}, "tier": {"code": "pass"}}},
        "IGN": {"symbol": "IGN", "companyName": "IGN Corp", "score": 75.0, "scoreDetail": {"eligibility": {"passed": True}, "tier": {"code": "pass"}}},
    }
    return [payloads[item["symbol"]] for item in candidates]


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


class ResearchQueueRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        self.paths.ensure()
        ensure_schema(self.paths)
        self.datetime_patch = patch('us_stock_research.research_queue.datetime', FixedDateTime)
        self.datetime_patch.start()

    def tearDown(self) -> None:
        self.datetime_patch.stop()
        self.temp_dir.cleanup()

    def _insert_stock(self, symbol: str, user_status: str = 'watching') -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status) VALUES (?, ?, 'strategy', 0, ?)",
                (symbol, symbol, user_status),
            )

    def _insert_research(self, symbol: str, research_date: str, status: str = 'completed') -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO research_snapshot (
                    symbol, research_date, trigger_type, trigger_priority,
                    prompt_template_id, prompt_version, strategy_id, input_data_json,
                    status, retry_count, expires_at
                ) VALUES (?, ?, 'expired', 'P2', 'tpl', 'v1', 's1', '{}', ?, 0, ?)
                """,
                (symbol, research_date, status, research_date),
            )

    def _insert_daily_snapshot(self, symbol: str, snapshot_date: str, daily_change_pct: float) -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO daily_position_snapshot (symbol, snapshot_date, price, daily_change_pct) VALUES (?, ?, 100, ?)",
                (symbol, snapshot_date, daily_change_pct),
            )

    def _insert_technical(self, symbol: str, snapshot_date: str, weekly_trend: str) -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                """
                INSERT INTO technical_snapshot (
                    symbol, snapshot_date, price, weekly_trend, signal, gate_is_blocked
                ) VALUES (?, ?, 100, ?, 'wait', 0)
                """,
                (symbol, snapshot_date, weekly_trend),
            )

    def test_should_research_never_researched(self) -> None:
        self._insert_stock('AAA')
        self.assertEqual(should_research('AAA', paths=self.paths), (True, 'never_researched'))

    def test_should_research_within_10_days(self) -> None:
        self._insert_stock('AAA')
        self._insert_research('AAA', '2026-03-04T15:00:00+00:00')
        should, reason = should_research('AAA', paths=self.paths)
        self.assertFalse(should)
        self.assertTrue(reason.startswith('reuse:'))

    def test_should_research_exactly_10_days(self) -> None:
        self._insert_stock('AAA')
        self._insert_research('AAA', '2026-03-03T15:00:00+00:00')
        self.assertFalse(should_research('AAA', paths=self.paths)[0])

    def test_should_research_expired_after_10_days(self) -> None:
        self._insert_stock('AAA')
        self._insert_research('AAA', '2026-03-01T15:00:00+00:00')
        self.assertEqual(should_research('AAA', paths=self.paths), (True, 'expired'))

    def test_should_research_ignored(self) -> None:
        self._insert_stock('AAA', user_status='ignored')
        self.assertEqual(should_research('AAA', paths=self.paths), (False, 'ignored'))

    def test_should_research_manual_override(self) -> None:
        self._insert_stock('AAA')
        self._insert_research('AAA', '2026-03-04T15:00:00+00:00')
        self.assertEqual(should_research('AAA', skip_dedup=True, paths=self.paths), (True, 'manual_override'))

    def test_should_research_held_significant_change(self) -> None:
        self._insert_stock('AAA', user_status='held')
        self._insert_research('AAA', '2026-03-04T15:00:00+00:00')
        self._insert_daily_snapshot('AAA', '2026-03-12', 6.0)
        self.assertEqual(should_research('AAA', paths=self.paths), (True, 'held_significant_change'))

    def test_should_research_held_no_significant_change(self) -> None:
        self._insert_stock('AAA', user_status='held')
        self._insert_research('AAA', '2026-03-04T15:00:00+00:00')
        self._insert_daily_snapshot('AAA', '2026-03-12', 3.0)
        self.assertFalse(should_research('AAA', paths=self.paths)[0])

    def test_has_significant_change_price(self) -> None:
        self._insert_daily_snapshot('AAA', '2026-03-12', 5.1)
        self.assertTrue(has_significant_change('AAA', paths=self.paths))

    def test_has_significant_change_price_boundary(self) -> None:
        self._insert_daily_snapshot('AAA', '2026-03-12', 4.9)
        self.assertFalse(has_significant_change('AAA', paths=self.paths))

    def test_has_significant_change_trend_reversal(self) -> None:
        self._insert_technical('AAA', '2026-03-11', 'up')
        self._insert_technical('AAA', '2026-03-12', 'down')
        self.assertTrue(has_significant_change('AAA', paths=self.paths))

    def test_has_significant_change_no_data(self) -> None:
        self.assertFalse(has_significant_change('AAA', paths=self.paths))

    def test_build_batch_respects_15_limit(self) -> None:
        candidates = []
        for idx in range(20):
            symbol = f'S{idx:02d}'
            self._insert_stock(symbol)
            candidates.append({'symbol': symbol, 'initial_score': 100 - idx})
        batch = build_research_batch(candidates, paths=self.paths)
        self.assertEqual(len(batch['queued']), 15)
        self.assertEqual(len(batch['pending_next_batch']), 5)

    def test_build_batch_ignored_stocks_excluded(self) -> None:
        self._insert_stock('AAA', user_status='ignored')
        self._insert_stock('BBB')
        batch = build_research_batch([
            {'symbol': 'AAA', 'initial_score': 90},
            {'symbol': 'BBB', 'initial_score': 80},
        ], paths=self.paths)
        self.assertEqual([item['symbol'] for item in batch['queued']], ['BBB'])
        self.assertEqual(batch['ignored'], [{'symbol': 'AAA'}])

    def test_build_batch_sorted_by_score(self) -> None:
        for symbol in ['AAA', 'BBB', 'CCC']:
            self._insert_stock(symbol)
        batch = build_research_batch([
            {'symbol': 'AAA', 'initial_score': 70},
            {'symbol': 'BBB', 'initial_score': 90},
            {'symbol': 'CCC', 'initial_score': 80},
        ], paths=self.paths)
        self.assertEqual([item['symbol'] for item in batch['queued']], ['BBB', 'CCC', 'AAA'])

    def test_build_batch_reused_stocks(self) -> None:
        self._insert_stock('AAA')
        self._insert_research('AAA', '2026-03-04T15:00:00+00:00')
        batch = build_research_batch([{'symbol': 'AAA', 'initial_score': 90}], paths=self.paths)
        self.assertEqual(batch['queued'], [])
        self.assertEqual(batch['reused'][0]['symbol'], 'AAA')

    def test_build_batch_returns_all_categories(self) -> None:
        self._insert_stock('AAA')
        batch = build_research_batch([{'symbol': 'AAA', 'initial_score': 90}], paths=self.paths)
        self.assertEqual(set(batch.keys()), {'queued', 'reused', 'pending_next_batch', 'ignored'})

    def test_build_batch_invalid_score_defaults_to_zero(self) -> None:
        self._insert_stock('AAA')
        with self.assertLogs('us_stock_research.research_queue', level='WARNING') as captured:
            batch = build_research_batch([{'symbol': 'AAA', 'initial_score': 'bad'}], paths=self.paths)
        self.assertEqual(batch['queued'][0]['initial_score'], 0.0)
        self.assertTrue(any('Invalid initial_score' in message for message in captured.output))

    def test_build_batch_empty_symbol_skipped(self) -> None:
        self._insert_stock('AAA')
        with self.assertLogs('us_stock_research.research_queue', level='WARNING') as captured:
            batch = build_research_batch([
                {'symbol': '   ', 'initial_score': 99},
                {'symbol': 'AAA', 'initial_score': 80},
            ], paths=self.paths)
        self.assertEqual([item['symbol'] for item in batch['queued']], ['AAA'])
        self.assertTrue(any('Skipping candidate with empty symbol' in message for message in captured.output))

    def test_serial_batch_single_item_no_sleep(self) -> None:
        calls: list[str] = []

        def research_fn(symbol: str) -> str:
            calls.append(symbol)
            return f'research:{symbol}'

        with patch('us_stock_research.research_queue.time.sleep') as mock_sleep:
            result = execute_research_batch_serial(['AAA'], research_fn)
        self.assertEqual(calls, ['AAA'])
        self.assertEqual(result, ['research:AAA'])
        mock_sleep.assert_not_called()

    def test_serial_batch_multiple_items_sleep_between(self) -> None:
        calls: list[str] = []

        def research_fn(symbol: str) -> str:
            calls.append(symbol)
            return symbol.lower()

        with patch('us_stock_research.research_queue.time.sleep') as mock_sleep:
            result = execute_research_batch_serial(['AAA', 'BBB', 'CCC'], research_fn, interval_seconds=2.5)
        self.assertEqual(calls, ['AAA', 'BBB', 'CCC'])
        self.assertEqual(result, ['aaa', 'bbb', 'ccc'])
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(2.5)

    def test_serial_batch_returns_results_in_order(self) -> None:
        result = execute_research_batch_serial(['BBB', 'AAA', 'CCC'], lambda symbol: f'out:{symbol}')
        self.assertEqual(result, ['out:BBB', 'out:AAA', 'out:CCC'])

    def test_increment_hit_count_existing(self) -> None:
        self._insert_stock('AAA')
        increment_hit_count('AAA', paths=self.paths)
        with get_connection(self.paths) as connection:
            hit_count = connection.execute("SELECT hit_count FROM stock_master WHERE symbol='AAA'").fetchone()[0]
        self.assertEqual(int(hit_count), 1)

    def test_increment_hit_count_creates_if_missing(self) -> None:
        increment_hit_count('AAA', paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT source, hit_count FROM stock_master WHERE symbol='AAA'").fetchone()
        self.assertEqual((row[0], int(row[1])), ('strategy', 1))

    @patch('us_stock_research.service.load_settings', return_value=AppSettings(fmp_api_key='demo'))
    @patch('us_stock_research.service.load_strategy')
    @patch('us_stock_research.service.FMPClient', StubFMPClient)
    @patch('us_stock_research.service.datetime', FixedDateTime)
    @patch('us_stock_research.cli.evaluate_candidates', side_effect=fake_evaluate_candidates)
    @patch('us_stock_research.cli.write_outputs', return_value={'json': Path('/tmp/out.json')})
    def test_service_increments_hit_count_for_all_candidates(self, _write_outputs, _evaluate, mock_strategy, _settings) -> None:
        self._insert_stock('IGN', user_status='ignored')
        mock_strategy.return_value = {
            'name': 'Test Strategy',
            'screen': {'limit': 50, 'market_cap_min': 0, 'market_cap_max': 100_000_000_000, 'volume_min': 0, 'sector': 'Technology', 'exchange': 'NASDAQ'},
            'ranking': {'top_n': 10, 'notes': 'notes'},
        }
        result = run_screening('test_strategy', top_n=3, paths=self.paths)
        with get_connection(self.paths) as connection:
            rows = connection.execute("SELECT symbol, hit_count FROM stock_master WHERE symbol IN ('AAA','BBB','IGN') ORDER BY symbol").fetchall()
        self.assertEqual([(row[0], int(row[1])) for row in rows], [('AAA', 1), ('BBB', 1), ('IGN', 1)])
        self.assertIn('research_batch', result)
        self.assertEqual(set(result['research_batch'].keys()), {'queued', 'reused', 'pending_next_batch', 'ignored'})

    def test_manual_research_does_not_increment_hit_count(self) -> None:
        self._insert_stock('AAA')
        self._insert_research('AAA', '2026-03-04T15:00:00+00:00')
        should, reason = should_research('AAA', skip_dedup=True, paths=self.paths)
        self.assertEqual((should, reason), (True, 'manual_override'))
        with get_connection(self.paths) as connection:
            hit_count = connection.execute("SELECT hit_count FROM stock_master WHERE symbol='AAA'").fetchone()[0]
        self.assertEqual(int(hit_count), 0)


if __name__ == '__main__':
    unittest.main()
