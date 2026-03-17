from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.alert_engine import Signal  # noqa: E402
from us_stock_research.alert_manager import AlertManager  # noqa: E402
from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.event_notifications import (  # noqa: E402
    ACTION_LEVEL_WARNING,
    EVENT_SPECS,
    build_daily_summary_notification,
    build_event_payload,
    create_alert_notification,
    create_notification_event,
    handle_system_failure,
    send_alert_notifications_for_symbol,
    send_notification_event,
    should_send_notification,
)
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


class NotificationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _mark_sent_hours_ago(self, notification_id: int, hours: int) -> None:
        with get_connection(self.paths) as connection:
            connection.execute(
                "UPDATE notification_event SET send_status='sent', sent_at=datetime('now', ?) WHERE id = ?",
                (f'-{hours} hours', notification_id),
            )

    def _create_sent_event(self, event_type: str, symbol: str | None, correlation_id: str = 'cid') -> int:
        payload = build_event_payload(event_type=event_type, symbol=symbol, summary='summary', correlation_id=correlation_id)
        created = create_notification_event(event_type=event_type, payload=payload, correlation_id=correlation_id, symbol=symbol, paths=self.paths)
        self._mark_sent_hours_ago(created['id'], 1)
        return int(created['id'])

    def test_new_event_types_in_specs(self) -> None:
        for event_type in ['daily_screening', 'research_completed_v2', 'buy_confirmation', 'risk_warning', 'sell_reminder', 'reresearch_completed', 'system_failure']:
            with self.subTest(event_type=event_type):
                self.assertIn(event_type, EVENT_SPECS)

    def test_event_specs_have_urgency(self) -> None:
        for event_type in ['daily_screening', 'research_completed_v2', 'buy_confirmation', 'risk_warning', 'sell_reminder', 'reresearch_completed', 'system_failure']:
            self.assertIn('urgency', EVENT_SPECS[event_type])

    def test_buy_confirmation_zero_cooldown(self) -> None:
        self.assertEqual(EVENT_SPECS['buy_confirmation']['cooldown_hours'], 0)

    def test_existing_event_types_unchanged(self) -> None:
        self.assertIn('strategy_hit', EVENT_SPECS)
        self.assertEqual(EVENT_SPECS['strategy_hit']['template_name'], 'tpl_strategy_hit')
        self.assertIn('daily_digest', EVENT_SPECS)

    def test_should_send_ok_no_history(self) -> None:
        self.assertEqual(should_send_notification('risk_warning', 'AAPL', paths=self.paths), (True, 'ok'))

    def test_should_send_cooldown_within_window(self) -> None:
        notification_id = self._create_sent_event('risk_warning', 'AAPL')
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE notification_event SET sent_at=datetime('now', '-3 hours') WHERE id = ?", (notification_id,))
        self.assertEqual(should_send_notification('risk_warning', 'AAPL', paths=self.paths), (False, 'cooldown'))

    def test_should_send_ok_after_cooldown(self) -> None:
        notification_id = self._create_sent_event('risk_warning', 'AAPL')
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE notification_event SET sent_at=datetime('now', '-7 hours') WHERE id = ?", (notification_id,))
        self.assertEqual(should_send_notification('risk_warning', 'AAPL', paths=self.paths), (True, 'ok'))

    def test_should_send_upgrade_bypasses_cooldown(self) -> None:
        self._create_sent_event('risk_warning', 'AAPL')
        self.assertEqual(should_send_notification('risk_warning', 'AAPL', is_upgrade=True, paths=self.paths), (True, 'ok'))

    def test_should_send_zero_cooldown_always_ok(self) -> None:
        self.assertEqual(should_send_notification('buy_confirmation', 'AAPL', paths=self.paths), (True, 'ok'))

    def test_create_alert_notification_risk_warning(self) -> None:
        merged = {'symbol': 'AAPL', 'top_action': '重点关注', 'signals': [{'type': '急跌预警', 'action': '重点关注', 'detail': 'd'}], 'signal_count': 1}
        created = create_alert_notification('AAPL', merged, 'risk_warning', 'cid-1', paths=self.paths)
        self.assertTrue(created['created'])
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type FROM notification_event WHERE id = ?", (created['id'],)).fetchone()
        self.assertEqual(row[0], 'risk_warning')

    def test_create_alert_notification_sell_reminder(self) -> None:
        merged = {'symbol': 'AAPL', 'top_action': '考虑止损', 'signals': [{'type': '止损触发', 'action': '考虑止损', 'detail': 'd'}], 'signal_count': 1}
        created = create_alert_notification('AAPL', merged, 'sell_reminder', 'cid-2', paths=self.paths)
        self.assertTrue(created['created'])
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type FROM notification_event WHERE id = ?", (created['id'],)).fetchone()
        self.assertEqual(row[0], 'sell_reminder')

    def test_create_alert_notification_cooldown_skip(self) -> None:
        self._create_sent_event('risk_warning', 'AAPL', 'cid-3')
        merged = {'symbol': 'AAPL', 'top_action': '重点关注', 'signals': [{'type': '急跌预警', 'action': '重点关注', 'detail': 'd'}], 'signal_count': 1}
        created = create_alert_notification('AAPL', merged, 'risk_warning', 'cid-4', paths=self.paths)
        self.assertFalse(created['created'])
        self.assertEqual(created['reason'], 'cooldown')

    def test_create_alert_notification_content(self) -> None:
        merged = {'symbol': 'AAPL', 'top_action': '重点关注', 'signals': [{'type': '急跌预警', 'action': '重点关注', 'detail': 'd'}], 'signal_count': 2}
        created = create_alert_notification('AAPL', merged, 'risk_warning', 'cid-5', paths=self.paths)
        with get_connection(self.paths) as connection:
            payload = connection.execute("SELECT payload_json FROM notification_event WHERE id = ?", (created['id'],)).fetchone()[0]
        self.assertIn('AAPL', payload)
        self.assertIn('重点关注', payload)
        self.assertIn('2条信号', payload)

    def test_daily_summary_mixed_results(self) -> None:
        created = build_daily_summary_notification([
            {'symbol': 'AAPL', 'status': 'success', 'summary': '值得投资', 'doc_url': 'https://doc/1', 'reuse_date': None},
            {'symbol': 'MSFT', 'status': 'fallback', 'summary': '降级完成', 'doc_url': 'https://doc/2', 'reuse_date': None},
            {'symbol': 'META', 'status': 'failed', 'summary': '失败', 'doc_url': None, 'reuse_date': None},
            {'symbol': 'GOOG', 'status': 'reused', 'summary': '复用', 'doc_url': None, 'reuse_date': '2026-03-05'},
            {'symbol': 'TSLA', 'status': 'pending', 'summary': '待研究', 'doc_url': None, 'reuse_date': None},
        ], 'cid-daily', paths=self.paths)
        with get_connection(self.paths) as connection:
            message = connection.execute("SELECT message_content FROM notification_event WHERE id = ?", (created['id'],)).fetchone()[0]
        for icon in ['✅', '⚠️', '❌', '🔄', '⏳']:
            self.assertIn(icon, message)

    def test_daily_summary_all_failed(self) -> None:
        created = build_daily_summary_notification([
            {'symbol': 'AAPL', 'status': 'failed', 'summary': '失败', 'doc_url': None, 'reuse_date': None},
            {'symbol': 'MSFT', 'status': 'failed', 'summary': '失败', 'doc_url': None, 'reuse_date': None},
        ], 'cid-all-failed', paths=self.paths)
        with get_connection(self.paths) as connection:
            payload = connection.execute("SELECT payload_json FROM notification_event WHERE id = ?", (created['id'],)).fetchone()[0]
        self.assertIn('全批次失败', payload)

    def test_daily_summary_empty_batch(self) -> None:
        created = build_daily_summary_notification([], 'cid-empty', paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type FROM notification_event WHERE id = ?", (created['id'],)).fetchone()
        self.assertEqual(row[0], 'system_failure')

    def test_daily_summary_success_has_doc_url(self) -> None:
        created = build_daily_summary_notification([
            {'symbol': 'AAPL', 'status': 'success', 'summary': '值得投资', 'doc_url': 'https://doc/1', 'reuse_date': None},
        ], 'cid-link', paths=self.paths)
        with get_connection(self.paths) as connection:
            message = connection.execute("SELECT message_content FROM notification_event WHERE id = ?", (created['id'],)).fetchone()[0]
        self.assertIn('[查看报告](https://doc/1)', message)

    def test_handle_system_failure_task_not_started(self) -> None:
        created = handle_system_failure('task_not_started', '定时任务未启动', 'cid-fail', paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT event_type FROM notification_event WHERE id = ?", (created['id'],)).fetchone()
        self.assertEqual(row[0], 'system_failure')

    def test_handle_system_failure_cooldown(self) -> None:
        created = handle_system_failure('task_not_started', '定时任务未启动', 'cid-fail-2', paths=self.paths)
        with get_connection(self.paths) as connection:
            connection.execute("UPDATE notification_event SET send_status='sent', sent_at=datetime('now', '-30 minutes') WHERE id = ?", (created['id'],))
        second = handle_system_failure('task_not_started', '定时任务未启动', 'cid-fail-3', paths=self.paths)
        self.assertFalse(second['created'])
        self.assertEqual(second['reason'], 'cooldown')

    @patch('us_stock_research.event_notifications.time.sleep', return_value=None)
    def test_send_notification_retries_on_failure(self, _sleep) -> None:
        payload = build_event_payload(event_type='system_failure', symbol=None, summary='error', correlation_id='cid-retry')
        created = create_notification_event(event_type='system_failure', payload=payload, correlation_id='cid-retry', paths=self.paths)
        calls = {'count': 0}
        def sender(title: str, lines: list[str], webhook_url: str) -> dict:
            calls['count'] += 1
            if calls['count'] < 3:
                raise RuntimeError('fail')
            return {'ok': True}
        result = send_notification_event(notification_id=created['id'], webhook_url='https://example.com', paths=self.paths, sender=sender)
        self.assertTrue(result['sent'])
        self.assertEqual(calls['count'], 3)

    @patch('us_stock_research.event_notifications.time.sleep', return_value=None)
    def test_send_notification_records_error_after_3_retries(self, _sleep) -> None:
        payload = build_event_payload(event_type='system_failure', symbol=None, summary='error', correlation_id='cid-retry-fail')
        created = create_notification_event(event_type='system_failure', payload=payload, correlation_id='cid-retry-fail', paths=self.paths)
        def sender(title: str, lines: list[str], webhook_url: str) -> dict:
            raise RuntimeError('boom')
        result = send_notification_event(notification_id=created['id'], webhook_url='https://example.com', paths=self.paths, sender=sender)
        self.assertFalse(result['sent'])
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT send_status, error_message FROM notification_event WHERE id = ?", (created['id'],)).fetchone()
        self.assertEqual(row[0], 'failed')
        self.assertIn('boom', row[1])

    @patch('us_stock_research.event_notifications.time.sleep', return_value=None)
    def test_send_notification_no_raise_on_failure(self, _sleep) -> None:
        payload = build_event_payload(event_type='system_failure', symbol=None, summary='error', correlation_id='cid-no-raise')
        created = create_notification_event(event_type='system_failure', payload=payload, correlation_id='cid-no-raise', paths=self.paths)
        def sender(title: str, lines: list[str], webhook_url: str) -> dict:
            raise RuntimeError('boom')
        result = send_notification_event(notification_id=created['id'], webhook_url='https://example.com', paths=self.paths, sender=sender)
        self.assertFalse(result['sent'])

    @patch('us_stock_research.event_notifications.time.sleep', return_value=None)
    def test_send_alert_notifications_for_symbol(self, _sleep) -> None:
        manager = AlertManager(paths=self.paths)
        manager.process_signals('AAPL', [Signal(type='急跌预警', level='warning', action='重点关注', value=-6.0, threshold=-5.0, detail='下跌')])
        calls = {}
        def sender(title: str, lines: list[str], webhook_url: str) -> dict:
            calls['title'] = title
            return {'ok': True}
        with patch('us_stock_research.event_notifications.send_post', sender):
            result = send_alert_notifications_for_symbol('AAPL', manager, 'https://example.com', 'cid-alert', paths=self.paths)
        self.assertTrue(result['sent'])
        self.assertEqual(result['event_type'], 'risk_warning')
        self.assertIn('重点关注', ACTION_LEVEL_WARNING)


if __name__ == '__main__':
    unittest.main()
