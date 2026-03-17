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

from us_stock_research.config import ProjectPaths, save_app_config  # noqa: E402
from us_stock_research.event_notifications import build_event_payload, create_notification_event  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.perplexity_client import PerplexityClientError  # noqa: E402
from us_stock_research.research_engine import (  # noqa: E402
    build_perplexity_prompt,
    build_research_trigger_guidance,
    normalize_perplexity_payload,
    run_deep_research,
)
from us_stock_research.ui_data import load_lifecycle_summary  # noqa: E402
from us_stock_research.workflow_engine import enqueue_research, persist_research_analysis  # noqa: E402


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


class FakePerplexityClient:
    def __init__(self, *args, **kwargs):
        pass

    def deep_research(self, *, prompt: str, system_prompt: str = ''):
        class Result:
            model = 'sonar-pro'
            raw_text = '{"summary":"Zoom 研究完成"}'
            structured = {
                'bull_thesis': [{'point': '企业客户续费改善', 'impact': 'high'}],
                'bear_thesis': [{'point': '宏观预算仍有压力', 'impact': 'medium'}],
                'key_risks': [{'type': 'demand', 'detail': 'SMB 需求恢复慢', 'severity': 'medium'}],
                'catalysts': [{'title': 'AI 会议产品变现', 'impact': 'high', 'timeline': '2 quarters'}],
                'valuation_view': 'undervalued',
                'target_price': 92.5,
                'invalidation_conditions': ['大型客户流失加速'],
                'confidence_score': 78,
                'source_list': [{'title': 'Latest earnings call', 'url': 'https://example.com/earnings'}],
                'overall_recommendation': 'buy',
                'summary': 'Zoom 研究完成',
            }
        return Result()


class RaisePerplexityClient:
    def __init__(self, *args, **kwargs):
        pass

    def deep_research(self, *, prompt: str, system_prompt: str = ''):
        raise PerplexityClientError('boom')


def fake_load_settings():
    from us_stock_research.config import AppSettings

    return AppSettings(
        fmp_api_key='',
        perplexity_api_key='test-perplexity-key',
        perplexity_base_url='https://api.perplexity.ai',
        perplexity_model='sonar-pro',
        perplexity_timeout=45,
    )


class PerplexityResearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        ensure_schema(self.paths)
        save_app_config(
            {
                'research': {
                    'perplexity': {
                        'enabled': True,
                        'prompt_template_id': 'baseline_perplexity_template',
                        'prompt_version': 'v1.1',
                        'fallback_to_derived': True,
                    }
                }
            },
            self.paths,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def sample_stock(self) -> dict[str, object]:
        return {
            'symbol': 'ZM',
            'companyName': 'Zoom Video Communications',
            'sector': 'Technology',
            'exchange': 'NASDAQ',
            'price': 75.2,
            'marketCap': 22000000000,
            'volume': 3000000,
            'ratios': {
                'priceToEarningsRatioTTM': 15.0,
                'priceToBookRatioTTM': 2.4,
                'netProfitMarginTTM': 0.19,
                'debtToEquityRatioTTM': 0.2,
                'currentRatioTTM': 2.3,
            },
        }

    def test_build_research_trigger_guidance_marks_stale_research(self) -> None:
        guidance = build_research_trigger_guidance(
            latest_research_at='2026-02-20T10:00:00',
            latest_trigger_type='manual_research',
            latest_status='completed',
            next_review_date='2026-03-01',
        )
        self.assertEqual(guidance['freshness'], 'stale')
        self.assertTrue(guidance['should_trigger'])

    def test_build_perplexity_prompt_contains_strict_schema(self) -> None:
        prompt = build_perplexity_prompt(self.sample_stock(), paths=self.paths)
        self.assertIn('overall_conclusion: 只能是 值得投|不值得投|仅高风险偏好', prompt)
        self.assertIn('source_list: 3-8 条', prompt)
        self.assertIn('three_sentence_summary', prompt)

    def test_normalize_perplexity_payload_normalizes_enums(self) -> None:
        analysis = normalize_perplexity_payload({
            'bull_thesis': [{'point': '增长恢复', 'impact': '高'}],
            'bear_thesis': [],
            'key_risks': [{'type': 'macro', 'detail': '预算收紧', 'severity': '中等'}],
            'catalysts': [{'title': '新品发布', 'impact': 'High', 'timeline': '2 quarters'}],
            'valuation_view': '低估',
            'target_price': 100,
            'invalidation_conditions': ['test'],
            'confidence_score': 60,
            'source_list': [],
            'overall_recommendation': '买入',
            'summary': 'ok',
        })
        self.assertEqual(analysis.valuation_view, 'undervalued')
        self.assertEqual(analysis.bull_thesis[0]['impact'], 'high')
        self.assertEqual(analysis.key_risks[0]['severity'], 'medium')
        self.assertEqual(analysis.catalysts[0]['timeline'], 'mid_term')
        self.assertEqual(analysis.overall_recommendation, 'buy')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', FakePerplexityClient)
    def test_run_deep_research_uses_perplexity_when_enabled(self) -> None:
        analysis = run_deep_research(self.sample_stock(), paths=self.paths)
        self.assertEqual(analysis.provider, 'perplexity')
        self.assertEqual(analysis.prompt_version, 'v1.1')
        self.assertEqual(analysis.confidence_score, 78)
        self.assertEqual(analysis.overall_recommendation, 'buy')
        self.assertTrue(analysis.raw_response)
        self.assertEqual(analysis.model_name, 'sonar-pro')
        self.assertFalse(analysis.fallback_used)

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', RaisePerplexityClient)
    def test_run_deep_research_falls_back_to_derived(self) -> None:
        analysis = run_deep_research(self.sample_stock(), paths=self.paths)
        self.assertEqual(analysis.provider, 'derived')
        self.assertTrue(analysis.confidence_score > 0)
        self.assertTrue(analysis.fallback_used)

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', FakePerplexityClient)
    def test_persist_research_analysis_records_perplexity_result_and_ui_can_read(self) -> None:
        with get_connection(self.paths) as connection:
            snapshot_id = enqueue_research(symbol='ZM', strategy_id='low_valuation_quality', correlation_id='cid-1', paths=self.paths, connection=connection)
            result = persist_research_analysis(
                symbol='ZM',
                stock=self.sample_stock(),
                research_snapshot_id=snapshot_id,
                correlation_id='cid-1',
                paths=self.paths,
                connection=connection,
            )
            create_notification_event(
                event_type='research_completed',
                payload=build_event_payload(event_type='research_completed', symbol='ZM', summary='研究完成', correlation_id='cid-1', facts={'confidence_score': 78}),
                correlation_id='cid-1',
                symbol='ZM',
                dedupe_key='research_completed:zm:test',
                paths=self.paths,
                connection=connection,
            )
            row = connection.execute('SELECT raw_response, prompt_version, status, input_data_json FROM research_snapshot WHERE id = ?', (snapshot_id,)).fetchone()
            analysis_row = connection.execute('SELECT confidence_score, overall_recommendation FROM research_analysis WHERE research_snapshot_id = ?', (snapshot_id,)).fetchone()
        self.assertEqual(result['confidence_score'], 78)
        self.assertEqual(result['provider'], 'perplexity')
        self.assertEqual(result['fallback_used'], False)
        self.assertEqual(row[1], 'v1.1')
        self.assertEqual(row[2], 'completed')
        self.assertIn('summary', row[0])
        self.assertIn('company_name', row[3])
        self.assertEqual(int(analysis_row[0]), 78)
        self.assertEqual(str(analysis_row[1]), 'buy')

        lifecycle = load_lifecycle_summary(self.paths)
        self.assertGreaterEqual(lifecycle['totals']['research_result_count'], 1)
        self.assertEqual(lifecycle['research_results'][0]['Symbol'], 'ZM')

    def test_normalize_perplexity_payload_normalizes_chinese_recommendation(self) -> None:
        analysis = normalize_perplexity_payload({
            'bull_thesis': [],
            'bear_thesis': [],
            'key_risks': [],
            'catalysts': [],
            'valuation_view': 'undervalued',
            'target_price': 100,
            'invalidation_conditions': ['test'],
            'confidence_score': 60,
            'source_list': [],
            'overall_recommendation': '买入',
            'summary': 'ok',
        })
        self.assertEqual(analysis.overall_recommendation, 'buy')


if __name__ == '__main__':
    unittest.main()
