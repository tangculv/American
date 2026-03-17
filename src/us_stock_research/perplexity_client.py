from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


class PerplexityClientError(RuntimeError):
    """Raised when the Perplexity client cannot complete a request."""


@dataclass(frozen=True)
class PerplexityResearchResult:
    structured: dict[str, Any]
    raw_text: str
    model: str


class PerplexityClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 45) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip('/')
        self.model = model.strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                'Authorization': f'Bearer {self.api_key}' if self.api_key else '',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'ClaudeCode US Stock Research MVP',
            }
        )

    def deep_research(self, *, prompt: str, system_prompt: str = '') -> PerplexityResearchResult:
        if not self.api_key:
            raise PerplexityClientError('PERPLEXITY_API_KEY is missing. Please set it in .env or your shell environment.')
        url = f"{self.base_url}/chat/completions"
        body = {
            'model': self.model,
            'temperature': 0.2,
            'messages': [
                {'role': 'system', 'content': system_prompt or 'You are a precise equity research analyst.'},
                {'role': 'user', 'content': prompt},
            ],
            'response_format': {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'us_stock_research_analysis',
                    'schema': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'summary_table': {'type': 'object', 'additionalProperties': True},
                            'three_sentence_summary': {'type': 'string'},
                            'bull_thesis': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'point': {'type': 'string'}, 'impact': {'type': 'string'}}, 'required': ['point', 'impact']}},
                            'bear_thesis': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'point': {'type': 'string'}, 'impact': {'type': 'string'}}, 'required': ['point', 'impact']}},
                            'top_risks': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'type': {'type': 'string'}, 'detail': {'type': 'string'}, 'severity': {'type': 'string'}}, 'required': ['type', 'detail', 'severity']}},
                            'catalysts': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'title': {'type': 'string'}, 'impact': {'type': 'string'}, 'timeline': {'type': 'string'}}, 'required': ['title', 'impact', 'timeline']}},
                            'valuation': {'type': 'object', 'additionalProperties': True},
                            'earnings_bridge': {'type': 'object', 'additionalProperties': True},
                            'tangible_nav': {'type': 'object', 'additionalProperties': True},
                            'three_scenario_valuation': {
                                'type': 'object',
                                'additionalProperties': False,
                                'properties': {
                                    'target_price_conservative': {'type': ['number', 'null']},
                                    'target_price_base': {'type': ['number', 'null']},
                                    'target_price_optimistic': {'type': ['number', 'null']},
                                },
                                'required': ['target_price_conservative', 'target_price_base', 'target_price_optimistic'],
                            },
                            'trade_plan': {
                                'type': 'object',
                                'additionalProperties': False,
                                'properties': {
                                    'buy_range_low': {'type': ['number', 'null']},
                                    'buy_range_high': {'type': ['number', 'null']},
                                    'max_position_pct': {'type': ['number', 'null']},
                                    'stop_loss_condition': {'type': 'string'},
                                    'add_position_condition': {'type': 'string'},
                                    'reduce_position_condition': {'type': 'string'},
                                },
                                'required': ['buy_range_low', 'buy_range_high', 'max_position_pct', 'stop_loss_condition', 'add_position_condition', 'reduce_position_condition'],
                            },
                            'invalidation_conditions': {'type': 'array', 'items': {'type': 'string'}},
                            'confidence_score': {'type': 'integer'},
                            'source_list': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'properties': {'title': {'type': 'string'}, 'url': {'type': 'string'}}, 'required': ['title', 'url']}},
                            'overall_conclusion': {'type': 'string'},
                        },
                        'required': ['summary_table', 'three_sentence_summary', 'bull_thesis', 'bear_thesis', 'top_risks', 'catalysts', 'valuation', 'earnings_bridge', 'tangible_nav', 'three_scenario_valuation', 'trade_plan', 'invalidation_conditions', 'confidence_score', 'source_list', 'overall_conclusion'],
                    },
                },
            },
        }
        try:
            response = self.session.post(url, json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise PerplexityClientError(f'Request failed for {url}: {exc}') from exc
        except ValueError as exc:
            raise PerplexityClientError(f'Invalid JSON response from {url}') from exc

        try:
            content = payload['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise PerplexityClientError('Unexpected Perplexity response structure') from exc

        if isinstance(content, list):
            raw_text = ''.join(part.get('text', '') if isinstance(part, dict) else str(part) for part in content)
        else:
            raw_text = str(content)

        try:
            structured = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise PerplexityClientError('Perplexity did not return valid structured JSON') from exc

        return PerplexityResearchResult(structured=structured, raw_text=raw_text, model=self.model)
