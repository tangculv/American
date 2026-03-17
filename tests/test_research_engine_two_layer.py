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

from us_stock_research.config import AppSettings, ProjectPaths, save_app_config  # noqa: E402
from us_stock_research.models import ensure_schema, get_connection  # noqa: E402
from us_stock_research.perplexity_client import PerplexityClientError  # noqa: E402
from us_stock_research.research_engine import (  # noqa: E402
    GATE_FIELDS,
    QUALITY_FIELDS,
    TwoLayerResearchResult,
    execute_research_with_two_layer_output,
    extract_structured_fields,
    save_two_layer_result,
    validate_research_quality,
)


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


class FakePerplexityResult:
    model = 'sonar-pro'
    raw_text = '# Markdown report\n\n完整研究'
    structured = {
        'summary_table': {'symbol': 'AAA', 'price': 100},
        'three_sentence_summary': '第一句。第二句。第三句。',
        'bull_thesis': [{'point': '护城河稳固', 'impact': 'high'}],
        'overall_conclusion': '值得投',
        'top_risks': [{'type': 'macro', 'detail': '宏观波动', 'severity': 'medium'}],
        'valuation': {
            'tangible_book_value_per_share': 12.3,
            'price_to_tbv': 1.5,
            'normalized_eps': 4.2,
            'normalized_earnings_yield': 0.08,
            'net_debt_to_ebitda': 1.2,
            'interest_coverage': 8.0,
            'goodwill_pct': 0.1,
            'intangible_pct': 0.2,
            'tangible_net_asset_positive': True,
            'safety_margin_source': 'tbv',
        },
        'earnings_bridge': {'revenue': 'stable'},
        'tangible_nav': {'value': 10},
        'three_scenario_valuation': {
            'target_price_conservative': 90,
            'target_price_base': 110,
            'target_price_optimistic': 130,
        },
        'trade_plan': {
            'buy_range_low': 95,
            'buy_range_high': 105,
            'max_position_pct': 12,
            'stop_loss_condition': '跌破关键支撑',
            'add_position_condition': '业绩超预期',
            'reduce_position_condition': '估值过热',
        },
        'invalidation_conditions': ['逻辑失效'],
        'refinancing_risk': '低',
        'markdown_report': '# Markdown report\n\n完整研究',
    }


class FakePerplexityClient:
    def __init__(self, *args, **kwargs):
        pass

    def deep_research(self, *, prompt: str, system_prompt: str = ''):
        return FakePerplexityResult()


class RaisePerplexityClient:
    def __init__(self, *args, **kwargs):
        pass

    def deep_research(self, *, prompt: str, system_prompt: str = ''):
        raise PerplexityClientError('primary failed')


class CrashPerplexityClient:
    def __init__(self, *args, **kwargs):
        pass

    def deep_research(self, *, prompt: str, system_prompt: str = ''):
        raise RuntimeError('boom')


def fake_load_settings() -> AppSettings:
    return AppSettings(
        fmp_api_key='',
        perplexity_api_key='demo',
        perplexity_base_url='https://api.perplexity.ai',
        perplexity_model='sonar-pro',
        perplexity_timeout=30,
    )


class ResearchEngineTwoLayerTests(unittest.TestCase):
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
                        'prompt_version': 'v2.0',
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
            'symbol': 'AAA',
            'companyName': 'AAA Inc',
            'sector': 'Technology',
            'exchange': 'NASDAQ',
            'price': 100.0,
            'marketCap': 20000000000,
            'volume': 1000000,
            'ratios': {
                'priceToEarningsRatioTTM': 15.0,
                'priceToBookRatioTTM': 2.0,
                'netProfitMarginTTM': 0.2,
                'debtToEquityRatioTTM': 0.4,
                'currentRatioTTM': 2.0,
            },
        }

    def complete_quality_payload(self) -> dict:
        return dict(FakePerplexityResult.structured)

    def test_validate_quality_pass(self) -> None:
        level, issues = validate_research_quality(self.complete_quality_payload())
        self.assertEqual(level, 'pass')
        self.assertEqual(issues, [])

    def test_validate_quality_partial(self) -> None:
        payload = self.complete_quality_payload()
        payload.pop(QUALITY_FIELDS[0])
        level, issues = validate_research_quality(payload)
        self.assertEqual(level, 'partial')
        self.assertIn(QUALITY_FIELDS[0], issues)

    def test_validate_quality_fail_gate_missing(self) -> None:
        payload = self.complete_quality_payload()
        payload.pop(GATE_FIELDS[0])
        level, issues = validate_research_quality(payload)
        self.assertEqual(level, 'fail')
        self.assertIn(GATE_FIELDS[0], issues)

    def test_validate_quality_empty_string_treated_as_missing(self) -> None:
        payload = self.complete_quality_payload()
        payload['three_sentence_summary'] = ''
        level, _ = validate_research_quality(payload)
        self.assertEqual(level, 'fail')

    def test_validate_quality_none_treated_as_missing(self) -> None:
        payload = self.complete_quality_payload()
        payload['overall_conclusion'] = None
        level, _ = validate_research_quality(payload)
        self.assertEqual(level, 'fail')

    def test_validate_quality_empty_list_treated_as_missing(self) -> None:
        payload = self.complete_quality_payload()
        payload['bull_thesis'] = []
        level, _ = validate_research_quality(payload)
        self.assertEqual(level, 'fail')

    def test_extract_fields_complete(self) -> None:
        fields = extract_structured_fields(self.complete_quality_payload())
        self.assertEqual(fields['tangible_book_value_per_share'], 12.3)
        self.assertEqual(fields['target_price_base'], 110)
        self.assertEqual(fields['overall_conclusion'], '值得投')
        self.assertEqual(fields['refinancing_risk'], '低')

    def test_extract_fields_partial(self) -> None:
        fields = extract_structured_fields({'overall_conclusion': '不值得投'})
        self.assertEqual(fields['overall_conclusion'], '不值得投')
        self.assertIsNone(fields['target_price_base'])
        self.assertIsNone(fields['top_risks_json'])

    def test_extract_fields_empty_input(self) -> None:
        fields = extract_structured_fields({})
        self.assertTrue(all(value is None for value in fields.values()))

    def test_extract_overall_conclusion_valid(self) -> None:
        for value in ['值得投', '不值得投', '仅高风险偏好']:
            with self.subTest(value=value):
                fields = extract_structured_fields({'overall_conclusion': value})
                self.assertEqual(fields['overall_conclusion'], value)

    def test_extract_json_fields_serialized(self) -> None:
        fields = extract_structured_fields({
            'top_risks': [{'type': 'macro'}],
            'invalidation_conditions': ['失效条件'],
        })
        self.assertEqual(fields['top_risks_json'], '[{"type": "macro"}]')
        self.assertEqual(fields['invalidation_conditions_json'], '["失效条件"]')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', FakePerplexityClient)
    def test_execute_returns_two_layer_result(self) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertIsInstance(result, TwoLayerResearchResult)
        self.assertTrue(result.markdown_report)
        self.assertIsInstance(result.structured_fields, dict)

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', FakePerplexityClient)
    def test_execute_quality_pass_on_complete_result(self) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertEqual(result.quality_level, 'pass')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', RaisePerplexityClient)
    def test_execute_fallback_on_client_error(self) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, 'perplexity_fallback')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', CrashPerplexityClient)
    def test_execute_never_raises(self) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertIsInstance(result, TwoLayerResearchResult)
        self.assertEqual(result.quality_level, 'fail')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', FakePerplexityClient)
    def test_execute_records_prompt_template_id(self) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertEqual(result.prompt_template_id, 'baseline_perplexity_template')
        self.assertEqual(result.prompt_version, 'v2.0')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', RaisePerplexityClient)
    def test_fallback_result_still_validates(self) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertEqual(result.quality_level, 'pass')

    @patch('us_stock_research.research_engine.load_settings', fake_load_settings)
    @patch('us_stock_research.research_engine.PerplexityClient', RaisePerplexityClient)
    @patch('us_stock_research.research_engine._fallback_two_layer_payload', side_effect=RuntimeError('fallback boom'))
    def test_fallback_fail_returns_fail_level(self, _fallback) -> None:
        result = execute_research_with_two_layer_output('AAA', self.sample_stock(), paths=self.paths)
        self.assertEqual(result.quality_level, 'fail')
        self.assertTrue(result.fallback_used)

    def make_result(self, quality_level: str = 'pass') -> TwoLayerResearchResult:
        return TwoLayerResearchResult(
            symbol='AAA',
            markdown_report='# report',
            structured_fields=extract_structured_fields(self.complete_quality_payload()),
            quality_level=quality_level,
            quality_issues=[],
            fallback_used=False,
            provider='perplexity',
            prompt_template_id='baseline_perplexity_template',
            prompt_version='v2.0',
            error_message=None,
        )

    def test_save_result_writes_research_snapshot(self) -> None:
        save_two_layer_result('AAA', self.make_result(), paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT status, raw_response FROM research_snapshot WHERE symbol='AAA' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], 'completed')
        self.assertEqual(row[1], '# report')

    def test_save_result_writes_research_analysis(self) -> None:
        save_two_layer_result('AAA', self.make_result(), paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT overall_conclusion, target_price_base FROM research_analysis WHERE symbol='AAA' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], '值得投')
        self.assertEqual(row[1], 110)

    def test_save_result_fail_not_write_analysis(self) -> None:
        save_two_layer_result('AAA', self.make_result(quality_level='fail'), paths=self.paths)
        with get_connection(self.paths) as connection:
            count = connection.execute("SELECT COUNT(*) FROM research_analysis WHERE symbol='AAA'").fetchone()[0]
            status = connection.execute("SELECT status FROM research_snapshot WHERE symbol='AAA' ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(int(count), 0)
        self.assertEqual(status, 'failed')

    def test_save_result_saves_input_snapshot(self) -> None:
        save_two_layer_result('AAA', self.make_result(), input_data={'symbol': 'AAA', 'price': 100}, paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT input_data_json FROM research_snapshot WHERE symbol='AAA' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], '{"price": 100, "symbol": "AAA"}')

    def test_save_result_input_snapshot_none(self) -> None:
        save_two_layer_result('AAA', self.make_result(), input_data=None, paths=self.paths)
        with get_connection(self.paths) as connection:
            row = connection.execute("SELECT input_data_json FROM research_snapshot WHERE symbol='AAA' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], '{}')


if __name__ == '__main__':
    unittest.main()
