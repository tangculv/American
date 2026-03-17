from __future__ import annotations

from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.feishu_doc import (  # noqa: E402
    FeishuDocError,
    build_doc_title,
    create_research_doc,
    write_doc_url_to_db,
)
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402


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


class FeishuDocTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.paths = make_paths(Path(self.temp_dir.name))
        ensure_schema(self.paths)
        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO research_snapshot (symbol, research_date, trigger_type, trigger_priority, prompt_template_id, prompt_version, strategy_id, input_data_json, raw_response, status, retry_count, expires_at) VALUES ('AAPL', '2026-03-17T00:00:00', 'manual', 'P0', 'tpl', 'v1', 'two_layer_research', '{}', 'raw', 'completed', 0, '2026-03-17T00:00:00')"
            )
            connection.execute(
                "INSERT INTO research_analysis (research_snapshot_id, symbol, invalidation_conditions_json, confidence_score, next_review_date) VALUES (1, 'AAPL', '[]', 80, '2026-04-01')"
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_title_normal(self) -> None:
        title = build_doc_title('AAPL', 'Apple Inc', 'pass', date_str='2026-03-17')
        self.assertEqual(title, '[AAPL] Apple Inc - 深度研究报告 (2026-03-17)')

    def test_build_title_fallback(self) -> None:
        title = build_doc_title('AAPL', 'Apple Inc', 'fallback', date_str='2026-03-17')
        self.assertTrue(title.startswith('[降级] [AAPL]'))

    def test_build_title_reresearch(self) -> None:
        title = build_doc_title('AAPL', 'Apple Inc', 'pass', title_prefix='重研究', date_str='2026-03-17')
        self.assertIn('重研究报告', title)

    def test_build_title_fallback_reresearch(self) -> None:
        title = build_doc_title('AAPL', 'Apple Inc', 'fallback', title_prefix='重研究', date_str='2026-03-17')
        self.assertEqual(title, '[降级] [AAPL] Apple Inc - 重研究报告 (2026-03-17)')

    @patch.dict(os.environ, {}, clear=True)
    def test_create_doc_no_config(self) -> None:
        self.assertEqual(create_research_doc('AAPL', 'Apple Inc', '# report', 'pass'), '')

    @patch.dict(os.environ, {'FEISHU_APP_ID': 'app', 'FEISHU_APP_SECRET': 'secret'}, clear=True)
    @patch('us_stock_research.feishu_doc._get_tenant_access_token', side_effect=FeishuDocError('boom'))
    def test_create_doc_api_error(self, _mock_token) -> None:
        with self.assertRaises(FeishuDocError):
            create_research_doc('AAPL', 'Apple Inc', '# report', 'pass')

    @patch.dict(os.environ, {'FEISHU_APP_ID': 'app', 'FEISHU_APP_SECRET': 'secret'}, clear=True)
    @patch('us_stock_research.feishu_doc._create_feishu_doc', return_value='https://feishu.test/docx/abc')
    @patch('us_stock_research.feishu_doc._get_tenant_access_token', return_value='tenant-token')
    def test_create_doc_success(self, _mock_token, _mock_create) -> None:
        url = create_research_doc('AAPL', 'Apple Inc', '# report', 'pass')
        self.assertEqual(url, 'https://feishu.test/docx/abc')

    def test_write_doc_url_to_db(self) -> None:
        write_doc_url_to_db('AAPL', 'https://feishu.test/docx/abc', paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT feishu_doc_url FROM research_analysis WHERE symbol = 'AAPL' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], 'https://feishu.test/docx/abc')


if __name__ == '__main__':
    unittest.main()
