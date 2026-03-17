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

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.research_engine import TwoLayerResearchResult  # noqa: E402
from us_stock_research.tracking_workflow import execute_reresearch  # noqa: E402


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


def make_result(*, quality_level: str = 'pass', overall_conclusion: str = '值得投') -> TwoLayerResearchResult:
    return TwoLayerResearchResult(
        symbol='AAPL',
        markdown_report='# report',
        structured_fields={
            'overall_conclusion': overall_conclusion,
            'invalidation_conditions_json': '[]',
        },
        quality_level=quality_level,
        quality_issues=[],
        fallback_used=False,
        provider='perplexity',
        prompt_template_id='tpl',
        prompt_version='v1',
        error_message=None,
    )


class FakeAlertManager:
    instances = []

    def __init__(self, paths=None) -> None:
        self.paths = paths
        self.calls = []
        self.__class__.instances.append(self)

    def process_signals(self, symbol, new_signals):
        self.calls.append((symbol, new_signals))


class ReresearchTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeAlertManager.instances = []
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status, current_price, market_cap, avg_volume) VALUES ('AAPL', 'Apple Inc', 'strategy', 0, 'held', 100, 1000000000, 1000000)"
            )
            connection.execute(
                "INSERT INTO research_snapshot (symbol, research_date, trigger_type, trigger_priority, prompt_template_id, prompt_version, strategy_id, input_data_json, raw_response, status, retry_count, expires_at) VALUES ('AAPL', '2026-03-01T00:00:00', 'manual', 'P0', 'tpl', 'v1', 'two_layer_research', '{}', 'raw', 'completed', 0, '2026-03-01T00:00:00')"
            )
            connection.execute(
                "INSERT INTO research_analysis (research_snapshot_id, symbol, overall_conclusion, invalidation_conditions_json, confidence_score, next_review_date) VALUES (1, 'AAPL', '值得投', '[]', 80, '2026-04-01')"
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', return_value=make_result(quality_level='fail'))
    def test_execute_reresearch_fail_quality(self, _mock_execute) -> None:
        result = execute_reresearch('AAPL', paths=self.paths)
        self.assertFalse(result['success'])
        self.assertEqual(result['doc_url'], '')

    @patch('us_stock_research.tracking_workflow.create_notification_event')
    @patch('us_stock_research.tracking_workflow.write_doc_url_to_db')
    @patch('us_stock_research.tracking_workflow.create_research_doc', return_value='https://feishu.test/docx/abc')
    @patch('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', return_value=make_result())
    def test_execute_reresearch_success(self, _mock_execute, _mock_doc, _mock_write, mock_notify) -> None:
        result = execute_reresearch('AAPL', paths=self.paths)
        self.assertTrue(result['success'])
        self.assertEqual(result['doc_url'], 'https://feishu.test/docx/abc')
        mock_notify.assert_called_once()

    @patch('us_stock_research.tracking_workflow.create_notification_event')
    @patch('us_stock_research.tracking_workflow.write_doc_url_to_db')
    @patch('us_stock_research.tracking_workflow.create_research_doc', return_value='https://feishu.test/docx/abc')
    @patch('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', return_value=make_result(overall_conclusion='不值得投'))
    def test_execute_reresearch_conclusion_flip(self, _mock_execute, _mock_doc, _mock_write, _mock_notify) -> None:
        result = execute_reresearch('AAPL', paths=self.paths)
        self.assertTrue(result['conclusion_flipped'])
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT overall_conclusion FROM research_analysis WHERE symbol = 'AAPL' ORDER BY id DESC LIMIT 1").fetchone()
            alert_row = connection.execute("SELECT signal_type, action, detail FROM alert_event WHERE symbol = 'AAPL' AND signal_type = '持有逻辑失效' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], '不值得投')
        self.assertIsNotNone(alert_row)
        self.assertEqual(alert_row[0], '持有逻辑失效')
        self.assertEqual(alert_row[1], '考虑清仓')
        self.assertIn('重研究结论从值得投变为不值得投', alert_row[2] or '')

    @patch('us_stock_research.tracking_workflow.create_notification_event')
    @patch('us_stock_research.tracking_workflow.write_doc_url_to_db')
    @patch('us_stock_research.tracking_workflow.create_research_doc', return_value='https://feishu.test/docx/abc')
    @patch('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', return_value=make_result(overall_conclusion='值得投'))
    def test_execute_reresearch_no_flip(self, _mock_execute, _mock_doc, _mock_write, _mock_notify) -> None:
        result = execute_reresearch('AAPL', paths=self.paths)
        self.assertFalse(result['conclusion_flipped'])

    @patch('us_stock_research.tracking_workflow.create_notification_event')
    @patch('us_stock_research.tracking_workflow.create_research_doc', return_value='')
    @patch('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', return_value=make_result())
    def test_execute_reresearch_feishu_unavailable(self, _mock_execute, _mock_doc, mock_notify) -> None:
        result = execute_reresearch('AAPL', paths=self.paths)
        self.assertTrue(result['success'])
        self.assertEqual(result['doc_url'], '')
        mock_notify.assert_called_once()

    @patch('us_stock_research.tracking_workflow.execute_research_with_two_layer_output', side_effect=RuntimeError('boom'))
    def test_execute_reresearch_never_raises(self, _mock_execute) -> None:
        result = execute_reresearch('AAPL', paths=self.paths)
        self.assertEqual(result, {'success': False, 'doc_url': '', 'conclusion_flipped': False})


if __name__ == '__main__':
    unittest.main()
