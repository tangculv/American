from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.cli import build_parser, cmd_buy, cmd_ignore, cmd_monitor, cmd_research, cmd_run, cmd_sell, cmd_status, cmd_unignore  # noqa: E402
from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402


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


class CliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute("INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status) VALUES ('AAPL', 'Apple', 'strategy', 0, 'watching')")
            connection.execute("INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status) VALUES ('MSFT', 'Microsoft', 'strategy', 0, 'watching')")
            connection.execute("INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status) VALUES ('GOOGL', 'Alphabet', 'strategy', 0, 'held')")
            connection.execute("INSERT INTO position_summary (symbol, status, total_shares, avg_cost, first_buy_date, total_invested, realized_pnl, updated_at) VALUES ('GOOGL', 'open', 10, 100, '2026-03-01', 1000, 0, CURRENT_TIMESTAMP)")
            connection.execute("INSERT INTO daily_position_snapshot (symbol, snapshot_date, price, unrealized_pnl, unrealized_pnl_pct) VALUES ('GOOGL', '2026-03-17', 112, 120, 12.0)")
            connection.execute("INSERT INTO alert_event (symbol, signal_type, signal_level, action, status, triggered_at) VALUES ('GOOGL', '目标价达成', 'action', '考虑止盈', 'active', CURRENT_TIMESTAMP)")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch('us_stock_research.cli.build_daily_summary_notification')
    @patch('us_stock_research.cli.execute_research_with_two_layer_output')
    @patch('us_stock_research.cli.save_two_layer_result')
    @patch('us_stock_research.cli.build_research_batch')
    @patch('us_stock_research.cli.run_screening')
    def test_run_calls_build_research_batch(self, mock_screen, mock_batch, _mock_save, _mock_exec, _mock_summary) -> None:
        mock_screen.return_value = {'stocks': [{'symbol': 'AAPL'}, {'symbol': 'MSFT'}]}
        mock_batch.return_value = {'queued': [], 'reused': [], 'pending_next_batch': [], 'ignored': []}
        cmd_run(paths=self.paths)
        mock_batch.assert_called_once()

    @patch('us_stock_research.cli.build_daily_summary_notification')
    @patch('us_stock_research.cli.execute_research_with_two_layer_output')
    @patch('us_stock_research.cli.save_two_layer_result')
    @patch('us_stock_research.cli.build_research_batch')
    @patch('us_stock_research.cli.run_screening')
    def test_run_sends_daily_summary(self, mock_screen, mock_batch, _mock_save, _mock_exec, mock_summary) -> None:
        mock_screen.return_value = {'stocks': [{'symbol': 'AAPL'}]}
        mock_batch.return_value = {'queued': [], 'reused': [{'symbol': 'AAPL', 'last_research_date': '2026-03-10'}], 'pending_next_batch': [], 'ignored': []}
        cmd_run(paths=self.paths)
        mock_summary.assert_called_once()

    @patch('us_stock_research.cli.time.sleep')
    @patch('us_stock_research.cli.build_daily_summary_notification')
    @patch('us_stock_research.cli.save_two_layer_result')
    @patch('us_stock_research.cli.execute_research_with_two_layer_output')
    @patch('us_stock_research.cli.build_research_batch')
    @patch('us_stock_research.cli.run_screening')
    def test_run_respects_research_interval(self, mock_screen, mock_batch, mock_exec, _mock_save, _mock_summary, mock_sleep) -> None:
        mock_screen.return_value = {'stocks': [{'symbol': 'AAPL'}, {'symbol': 'MSFT'}]}
        mock_exec.return_value = type('R', (), {'quality_level': 'fail', 'fallback_used': False, 'markdown_report': ''})()
        mock_batch.return_value = {'queued': [{'symbol': 'AAPL'}, {'symbol': 'MSFT'}], 'reused': [], 'pending_next_batch': [], 'ignored': []}
        cmd_run(paths=self.paths)
        mock_sleep.assert_called_once()

    @patch('us_stock_research.cli.create_research_doc', return_value='')
    @patch('us_stock_research.cli.save_two_layer_result')
    @patch('us_stock_research.cli.execute_research_with_two_layer_output')
    def test_research_skips_dedup(self, mock_exec, _mock_save, _mock_doc) -> None:
        mock_exec.return_value = type('R', (), {'quality_level': 'pass', 'fallback_used': False, 'markdown_report': '# ok'})()
        cmd_research('AAPL', paths=self.paths)
        self.assertTrue(mock_exec.call_args.kwargs['skip_dedup'])

    @patch('us_stock_research.cli.send_alert_notifications_for_symbol')
    @patch('us_stock_research.cli.run_daily_monitoring', return_value={'monitored': 1, 'signals_detected': 2, 'reresearch_triggered': []})
    def test_monitor_calls_run_daily_monitoring(self, mock_monitor, _mock_send) -> None:
        cmd_monitor(paths=self.paths)
        mock_monitor.assert_called_once()

    @patch('us_stock_research.cli.send_alert_notifications_for_symbol')
    @patch('us_stock_research.cli.execute_reresearch')
    @patch('us_stock_research.cli.run_daily_monitoring', return_value={'monitored': 1, 'signals_detected': 2, 'reresearch_triggered': ['GOOGL']})
    def test_monitor_triggers_reresearch(self, _mock_monitor, mock_reresearch, _mock_send) -> None:
        cmd_monitor(paths=self.paths)
        mock_reresearch.assert_called_once_with('GOOGL', paths=self.paths)

    @patch('builtins.input', side_effect=['100', '5', '2026-03-17', 'starter'])
    @patch('us_stock_research.cli.create_notification_event')
    @patch('us_stock_research.cli.record_buy')
    def test_buy_calls_record_buy(self, mock_buy, _mock_notify, _mock_input) -> None:
        cmd_buy('AAPL', paths=self.paths)
        mock_buy.assert_called_once_with('AAPL', 100.0, 5, '2026-03-17', 'starter', paths=self.paths)

    @patch('builtins.input', side_effect=['100', '5', '2026-03-17', 'starter'])
    @patch('us_stock_research.cli.create_notification_event')
    @patch('us_stock_research.cli.record_buy')
    def test_buy_sends_confirmation(self, _mock_buy, mock_notify, _mock_input) -> None:
        cmd_buy('AAPL', paths=self.paths)
        self.assertEqual(mock_notify.call_args.kwargs['event_type'], 'buy_confirmation')

    @patch('builtins.input', side_effect=['120', '3', '2026-03-18', 'trim'])
    @patch('us_stock_research.cli.record_sell')
    @patch('us_stock_research.cli.get_position', side_effect=[{'realized_pnl': 0.0}, {'realized_pnl': 60.0}])
    def test_sell_calls_record_sell(self, _mock_position, mock_sell, _mock_input) -> None:
        cmd_sell('AAPL', paths=self.paths)
        mock_sell.assert_called_once_with('AAPL', 120.0, 3, '2026-03-18', 'trim', paths=self.paths)

    def test_ignore_updates_user_status(self) -> None:
        cmd_ignore('AAPL', paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT user_status FROM stock_master WHERE symbol = 'AAPL'").fetchone()
        self.assertEqual(row[0], 'ignored')

    def test_unignore_updates_user_status(self) -> None:
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE stock_master SET user_status = 'ignored' WHERE symbol = 'AAPL'")
        cmd_unignore('AAPL', paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT user_status FROM stock_master WHERE symbol = 'AAPL'").fetchone()
        self.assertEqual(row[0], 'watching')

    def test_status_shows_portfolio(self) -> None:
        with patch('sys.stdout', new_callable=StringIO) as stdout:
            cmd_status(paths=self.paths)
        output = stdout.getvalue()
        self.assertIn('持仓概况', output)
        self.assertIn('GOOGL', output)
        self.assertIn('考虑止盈', output)

    def test_ignore_unknown_symbol_warns(self) -> None:
        with patch('sys.stdout', new_callable=StringIO) as stdout:
            cmd_ignore('NVDA', paths=self.paths)
        self.assertIn('不在候选池', stdout.getvalue())

    def test_help_shows_all_commands(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        for command in ['run', 'run-and-notify', 'screen', 'research', 'monitor', 'buy', 'sell', 'ignore', 'unignore', 'status']:
            self.assertIn(command, help_text)


if __name__ == '__main__':
    unittest.main()
