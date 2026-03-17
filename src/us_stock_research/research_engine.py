from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CANONICAL_RECOMMENDATIONS = {'strong_buy', 'buy', 'hold', 'reduce', 'sell', 'watch'}
CANONICAL_VALUATION_VIEWS = {'deep_value', 'undervalued', 'attractive', 'neutral', 'expensive', 'overvalued'}
CANONICAL_IMPACTS = {'low', 'medium', 'high'}
CANONICAL_SEVERITIES = {'low', 'medium', 'high'}
CANONICAL_TIMELINES = {'immediate', 'near_term', 'mid_term', 'long_term'}

from .config import ProjectPaths, load_app_config, load_settings
from .perplexity_client import PerplexityClient, PerplexityClientError
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .time_utils import utc_now


@dataclass(frozen=True)
class DerivedResearchAnalysis:
    bull_thesis: list[dict[str, Any]]
    bear_thesis: list[dict[str, Any]]
    key_risks: list[dict[str, Any]]
    catalysts: list[dict[str, Any]]
    valuation_view: str
    target_price: float | None
    invalidation_conditions: list[str]
    confidence_score: int
    source_list: list[Any]
    next_review_date: str
    overall_recommendation: str
    summary: str
    provider: str = 'derived'
    prompt_template_id: str = 'baseline_perplexity_template'
    prompt_version: str = 'v1.0'
    raw_response: str = ''
    input_context: dict[str, Any] | None = None
    model_name: str = ''
    fallback_used: bool = False


POSITIVE_SECTORS = {"Technology", "Communication Services"}


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_cap_bucket(market_cap: float | None) -> str:
    if market_cap is None:
        return "unknown"
    if market_cap >= 50_000_000_000:
        return "mega"
    if market_cap >= 10_000_000_000:
        return "large"
    if market_cap >= 2_000_000_000:
        return "mid"
    return "small"


def _prompt_template_text(paths: ProjectPaths | None = None) -> str:
    paths = paths or ProjectPaths()
    path = paths.root / 'workflow' / '02-Perplexity研究Prompt.md'
    if not path.exists():
        return ''
    return path.read_text(encoding='utf-8')


def build_research_context(stock: dict[str, Any]) -> dict[str, Any]:
    company_name = str(stock.get('companyName') or stock.get('company_name') or stock.get('name') or '')
    symbol = str(stock.get('symbol') or '').upper()
    ratios = dict(stock.get('ratios', {}))
    return {
        'symbol': symbol,
        'company_name': company_name,
        'sector': stock.get('sector'),
        'exchange': stock.get('exchange'),
        'price': stock.get('price'),
        'market_cap': stock.get('marketCap'),
        'volume': stock.get('volume') or stock.get('avgVolume') or stock.get('volAvg'),
        'ratios': ratios,
    }


def build_perplexity_prompt(stock: dict[str, Any], *, paths: ProjectPaths | None = None) -> str:
    prompt_template = _prompt_template_text(paths)
    compact_context = json.dumps(build_research_context(stock), ensure_ascii=False, sort_keys=True, indent=2)
    schema_hint = """
请只返回一个 JSON 对象，不要输出 markdown，不要输出额外解释，不要使用代码块。
JSON 字段必须完整包含：
- summary_table: 对象，包含 symbol（股票代码）和 price（当前价格，数字或 null）
- three_sentence_summary: 用三句话概括公司现状、核心逻辑、主要风险，120 字以内中文
- bull_thesis: 最多 5 条，元素结构 {point, impact}，impact 只能是 low|medium|high
- bear_thesis: 最多 5 条，元素结构 {point, impact}，impact 只能是 low|medium|high
- top_risks: 最多 5 条，元素结构 {type, detail, severity}，severity 只能是 low|medium|high
- catalysts: 最多 5 条，元素结构 {title, impact, timeline}，impact 只能是 low|medium|high，timeline 只能是 immediate|near_term|mid_term|long_term
- valuation: 对象，包含 valuation_view（只能是 deep_value|undervalued|attractive|neutral|expensive|overvalued）和 target_price（number 或 null）
- earnings_bridge: 对象，描述近期收益变化驱动因素（revenue_growth、margin_change、key_driver 字段，均为字符串）
- tangible_nav: 对象，描述有形净资产情况（per_share 为数字或 null，commentary 为字符串）
- three_scenario_valuation: 对象，包含 target_price_conservative / target_price_base / target_price_optimistic（均为数字或 null）
- trade_plan: 对象，包含 buy_range_low / buy_range_high / max_position_pct（数字或 null）、stop_loss_condition / add_position_condition / reduce_position_condition（字符串）
- overall_conclusion: 只能是 值得投|不值得投|仅高风险偏好 三者之一（中文）
- invalidation_conditions: string[]，最多 5 条，触发「持有逻辑失效」的条件
- confidence_score: 0-100 的整数
- source_list: 3-8 条，元素结构 {title, url}
额外要求：
1. source_list 优先列最新财报、earnings call、公司公告、权威媒体、Sell-side / buy-side 研究来源；
2. 若无法确认具体数字，用 null 代替，不要编造；
3. overall_conclusion 必须严格使用上述三个中文枚举值之一。
""".strip()
    return f"{prompt_template}\n\n---\n\n股票上下文：\n{compact_context}\n\n---\n\n{schema_hint}"



def _normalize_enum(value: Any, *, mapping: dict[str, str], allowed: set[str], default: str) -> str:
    raw = str(value or '').strip()
    if not raw:
        return default
    lowered = raw.lower().replace('-', '_').replace(' ', '_')
    candidate = mapping.get(lowered, mapping.get(raw, lowered))
    return candidate if candidate in allowed else default


def _normalize_recommendation(value: Any) -> str:
    mapping = {
        'strongbuy': 'strong_buy',
        'strong_buy': 'strong_buy',
        'strong buy': 'strong_buy',
        '强烈买入': 'strong_buy',
        'buy': 'buy',
        '买入': 'buy',
        'hold': 'hold',
        '持有': 'hold',
        'watch': 'watch',
        '观察': 'watch',
        'reduce': 'reduce',
        '减持': 'reduce',
        'sell': 'sell',
        '卖出': 'sell',
    }
    return _normalize_enum(value, mapping=mapping, allowed=CANONICAL_RECOMMENDATIONS, default='hold')


def _normalize_valuation_view(value: Any) -> str:
    mapping = {
        'deep_value': 'deep_value',
        'deep value': 'deep_value',
        '极度低估': 'deep_value',
        'undervalued': 'undervalued',
        '低估': 'undervalued',
        'attractive': 'attractive',
        'attractively_valued': 'attractive',
        '估值有吸引力': 'attractive',
        'neutral': 'neutral',
        '中性': 'neutral',
        'expensive': 'expensive',
        '偏贵': 'expensive',
        'overvalued': 'overvalued',
        '高估': 'overvalued',
    }
    return _normalize_enum(value, mapping=mapping, allowed=CANONICAL_VALUATION_VIEWS, default='neutral')


def _normalize_impact(value: Any) -> str:
    mapping = {'low': 'low', 'medium': 'medium', 'high': 'high', '低': 'low', '中': 'medium', '中等': 'medium', '高': 'high'}
    return _normalize_enum(value, mapping=mapping, allowed=CANONICAL_IMPACTS, default='medium')


def _normalize_severity(value: Any) -> str:
    mapping = {'low': 'low', 'medium': 'medium', 'high': 'high', '低': 'low', '中': 'medium', '中等': 'medium', '高': 'high'}
    return _normalize_enum(value, mapping=mapping, allowed=CANONICAL_SEVERITIES, default='medium')


def _normalize_timeline(value: Any) -> str:
    mapping = {
        'immediate': 'immediate',
        'today': 'immediate',
        '1_week': 'immediate',
        'near_term': 'near_term',
        'near term': 'near_term',
        'short_term': 'near_term',
        '2 quarters': 'mid_term',
        'mid_term': 'mid_term',
        'mid term': 'mid_term',
        '6_12_months': 'mid_term',
        'long_term': 'long_term',
        'long term': 'long_term',
        '12m+': 'long_term',
        '近期': 'near_term',
        '中期': 'mid_term',
        '长期': 'long_term',
        '立即': 'immediate',
    }
    return _normalize_enum(value, mapping=mapping, allowed=CANONICAL_TIMELINES, default='near_term')

def _normalize_point_list(items: Any, *, key_name: str = 'point') -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items[:5]:
        if isinstance(item, dict):
            text = str(item.get(key_name) or item.get('title') or item.get('detail') or '').strip()
            impact = _normalize_impact(item.get('impact') or item.get('severity') or 'medium')
            if text:
                normalized.append({key_name: text, 'impact': impact} if key_name != 'detail' else {'type': str(item.get('type') or 'risk'), 'detail': text, 'severity': impact})
        elif isinstance(item, str) and item.strip():
            if key_name == 'detail':
                normalized.append({'type': 'risk', 'detail': item.strip(), 'severity': 'medium'})
            else:
                normalized.append({key_name: item.strip(), 'impact': 'medium'})
    return normalized


def _normalize_catalysts(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items[:5]:
        if isinstance(item, dict):
            title = str(item.get('title') or item.get('catalyst') or '').strip()
            if title:
                normalized.append({'title': title, 'impact': _normalize_impact(item.get('impact') or 'medium'), 'timeline': _normalize_timeline(item.get('timeline') or 'near_term')})
        elif isinstance(item, str) and item.strip():
            normalized.append({'title': item.strip(), 'impact': 'medium', 'timeline': 'near_term'})
    return normalized


def _normalize_source_list(items: Any) -> list[Any]:
    if not isinstance(items, list):
        return []
    out: list[Any] = []
    for item in items[:10]:
        if isinstance(item, dict):
            title = str(item.get('title') or '').strip()
            url = str(item.get('url') or '').strip()
            if title or url:
                out.append({'title': title or url, 'url': url})
        elif isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def normalize_perplexity_payload(payload: dict[str, Any], *, as_of: datetime | None = None) -> DerivedResearchAnalysis:
    as_of = as_of or utc_now()
    bull = _normalize_point_list(payload.get('bull_thesis'), key_name='point')
    bear = _normalize_point_list(payload.get('bear_thesis'), key_name='point')
    risks = _normalize_point_list(payload.get('key_risks'), key_name='detail')
    catalysts = _normalize_catalysts(payload.get('catalysts'))
    invalidation = [str(item).strip() for item in (payload.get('invalidation_conditions') or []) if str(item).strip()][:5]
    summary = str(payload.get('summary') or '').strip() or 'Perplexity 未返回摘要，已使用结构化字段落库。'
    recommendation = _normalize_recommendation(payload.get('overall_recommendation') or 'hold')
    valuation_view = _normalize_valuation_view(payload.get('valuation_view') or 'neutral')
    confidence_score = int(payload.get('confidence_score') or 50)
    target_price = _as_float(payload.get('target_price'))
    sources = _normalize_source_list(payload.get('source_list'))
    if len(sources) < 1:
        sources = [{'title': 'Perplexity research synthesis', 'url': ''}]
    if not invalidation:
        invalidation = ['核心假设失效', '基本面持续恶化']
    return DerivedResearchAnalysis(
        bull_thesis=bull,
        bear_thesis=bear,
        key_risks=risks,
        catalysts=catalysts,
        valuation_view=valuation_view,
        target_price=target_price,
        invalidation_conditions=invalidation,
        confidence_score=max(0, min(100, confidence_score)),
        source_list=sources,
        next_review_date=(as_of + timedelta(days=14)).date().isoformat(),
        overall_recommendation=recommendation,
        summary=summary,
    )


def derive_research_analysis(stock: dict[str, Any], *, as_of: datetime | None = None) -> DerivedResearchAnalysis:
    as_of = as_of or utc_now()
    ratios = dict(stock.get("ratios", {}))

    pe = _as_float(ratios.get("priceToEarningsRatioTTM"))
    pb = _as_float(ratios.get("priceToBookRatioTTM"))
    margin = _as_float(ratios.get("netProfitMarginTTM"))
    debt = _as_float(ratios.get("debtToEquityRatioTTM"))
    current_ratio = _as_float(ratios.get("currentRatioTTM"))
    market_cap = _as_float(stock.get("marketCap"))
    sector = str(stock.get("sector") or "")
    price = _as_float(stock.get("price"))

    bull: list[dict[str, Any]] = []
    bear: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    catalysts: list[dict[str, Any]] = []
    invalidation: list[str] = []
    sources = [
        "FMP stable/company-screener",
        "FMP stable/ratios-ttm",
    ]

    if pe is not None and 0 < pe < 18:
        bull.append({"point": f"PE {pe:.2f} 处于偏低区间，估值具备安全边际", "impact": "high"})
    elif pe is not None and pe > 30:
        bear.append({"point": f"PE {pe:.2f} 偏高，估值修复空间有限", "impact": "medium"})
        risks.append({"type": "valuation", "detail": "高估值回撤风险", "severity": "medium"})

    if pb is not None and pb < 2.5:
        bull.append({"point": f"PB {pb:.2f} 较温和，资产定价不激进", "impact": "medium"})
    elif pb is not None and pb >= 5:
        bear.append({"point": f"PB {pb:.2f} 较高，市场已预付成长预期", "impact": "medium"})

    if margin is not None and margin >= 0.15:
        bull.append({"point": f"净利率 {margin*100:.1f}% 表明利润质量较好", "impact": "high"})
    elif margin is not None and margin < 0.08:
        risks.append({"type": "profitability", "detail": f"净利率仅 {margin*100:.1f}%", "severity": "medium"})
        invalidation.append("利润率持续低于 8%")

    if debt is not None and debt >= 1.5:
        risks.append({"type": "balance_sheet", "detail": f"负债权益比 {debt:.2f} 偏高", "severity": "high"})
        bear.append({"point": "高杠杆削弱抗风险能力", "impact": "high"})
        invalidation.append("债务水平继续恶化")
    elif debt is not None and debt < 0.8:
        bull.append({"point": f"负债权益比 {debt:.2f}，资产负债表稳健", "impact": "medium"})

    if current_ratio is not None and current_ratio < 1.2:
        risks.append({"type": "liquidity", "detail": f"流动比率 {current_ratio:.2f} 偏低", "severity": "medium"})
        invalidation.append("流动性进一步走弱")

    bucket = _market_cap_bucket(market_cap)
    if bucket in {"large", "mega"}:
        bull.append({"point": "大市值公司流动性和机构覆盖更好", "impact": "medium"})
    elif bucket == "small":
        risks.append({"type": "liquidity", "detail": "小市值带来更高波动与流动性风险", "severity": "medium"})

    if sector in POSITIVE_SECTORS:
        catalysts.append({"title": f"{sector} 板块仍具备成长叙事", "impact": "medium", 'timeline': 'mid_term'})
    else:
        catalysts.append({"title": "行业轮动需持续观察", "impact": "low", 'timeline': 'near_term'})

    if price is not None:
        catalysts.append({"title": f"现价 {price:.2f}，适合持续观察技术企稳信号", "impact": "low", 'timeline': 'near_term'})

    confidence_base = 55
    confidence_base += 10 if len(bull) >= 3 else 0
    confidence_base -= 8 if len(risks) >= 3 else 0
    confidence_base += 5 if sector in POSITIVE_SECTORS else 0
    confidence = max(25, min(85, confidence_base))

    if len(bull) > len(bear) + len(risks) / 2:
        recommendation = "buy"
        valuation_view = "attractive"
    elif risks:
        recommendation = "hold"
        valuation_view = "neutral"
    else:
        recommendation = "watch"
        valuation_view = "neutral"

    target_price = round(price * 1.18, 2) if price and recommendation == "buy" else (round(price * 1.08, 2) if price else None)
    if not invalidation:
        invalidation = ["核心财务指标明显恶化", "技术面再次转弱"]

    summary = "；".join([
        bull[0]["point"] if bull else "估值和质量信号中性",
        risks[0]["detail"] if risks else "当前未发现高优先级结构性风险",
    ])

    return DerivedResearchAnalysis(
        bull_thesis=bull[:5],
        bear_thesis=bear[:5],
        key_risks=risks[:5],
        catalysts=catalysts[:5],
        valuation_view=valuation_view,
        target_price=target_price,
        invalidation_conditions=invalidation[:5],
        confidence_score=confidence,
        source_list=sources,
        next_review_date=(as_of + timedelta(days=14)).date().isoformat(),
        overall_recommendation=recommendation,
        summary=summary,
    )


def run_deep_research(stock: dict[str, Any], *, paths: ProjectPaths | None = None, force_provider: str | None = None) -> DerivedResearchAnalysis:
    paths = paths or ProjectPaths()
    app_config = load_app_config(paths)
    settings = load_settings()
    perplexity_cfg = dict(dict(app_config.get('research', {})).get('perplexity', {}))
    enabled = bool(perplexity_cfg.get('enabled', False))
    fallback = bool(perplexity_cfg.get('fallback_to_derived', True))
    prompt_template_id = str(perplexity_cfg.get('prompt_template_id', 'baseline_perplexity_template'))
    prompt_version = str(perplexity_cfg.get('prompt_version', 'v1.0'))
    provider = force_provider or ('perplexity' if enabled and settings.perplexity_api_key else 'derived')
    context = build_research_context(stock)

    if provider == 'perplexity':
        try:
            prompt = build_perplexity_prompt(stock, paths=paths)
            client = PerplexityClient(
                settings.perplexity_api_key,
                settings.perplexity_base_url,
                settings.perplexity_model,
                settings.perplexity_timeout,
            )
            result = client.deep_research(prompt=prompt)
            normalized = normalize_perplexity_payload(result.structured)
            return DerivedResearchAnalysis(
                bull_thesis=normalized.bull_thesis,
                bear_thesis=normalized.bear_thesis,
                key_risks=normalized.key_risks,
                catalysts=normalized.catalysts,
                valuation_view=normalized.valuation_view,
                target_price=normalized.target_price,
                invalidation_conditions=normalized.invalidation_conditions,
                confidence_score=normalized.confidence_score,
                source_list=normalized.source_list,
                next_review_date=normalized.next_review_date,
                overall_recommendation=normalized.overall_recommendation,
                summary=normalized.summary,
                provider='perplexity',
                prompt_template_id=prompt_template_id,
                prompt_version=prompt_version,
                raw_response=result.raw_text,
                input_context=context,
                model_name=result.model,
                fallback_used=False,
            )
        except PerplexityClientError:
            if not fallback:
                raise
    derived = derive_research_analysis(stock)
    return DerivedResearchAnalysis(
        bull_thesis=derived.bull_thesis,
        bear_thesis=derived.bear_thesis,
        key_risks=derived.key_risks,
        catalysts=derived.catalysts,
        valuation_view=derived.valuation_view,
        target_price=derived.target_price,
        invalidation_conditions=derived.invalidation_conditions,
        confidence_score=derived.confidence_score,
        source_list=derived.source_list,
        next_review_date=derived.next_review_date,
        overall_recommendation=derived.overall_recommendation,
        summary=derived.summary,
        provider='derived',
        prompt_template_id=prompt_template_id,
        prompt_version=prompt_version,
        raw_response=derived.summary,
        input_context=context,
        model_name='derived-local',
        fallback_used=(provider == 'perplexity'),
    )


def analysis_to_db_payload(analysis: DerivedResearchAnalysis) -> dict[str, Any]:
    return {
        "bull_thesis_json": json.dumps(analysis.bull_thesis, ensure_ascii=False, sort_keys=True),
        "bear_thesis_json": json.dumps(analysis.bear_thesis, ensure_ascii=False, sort_keys=True),
        "key_risks_json": json.dumps(analysis.key_risks, ensure_ascii=False, sort_keys=True),
        "catalysts_json": json.dumps(analysis.catalysts, ensure_ascii=False, sort_keys=True),
        "valuation_view": analysis.valuation_view,
        "target_price": analysis.target_price,
        "invalidation_conditions_json": json.dumps(analysis.invalidation_conditions, ensure_ascii=False, sort_keys=True),
        "confidence_score": analysis.confidence_score,
        "source_list_json": json.dumps(analysis.source_list, ensure_ascii=False, sort_keys=True),
        "next_review_date": analysis.next_review_date,
        "overall_recommendation": analysis.overall_recommendation,
        "provider": analysis.provider,
        "prompt_template_id": analysis.prompt_template_id,
        "prompt_version": analysis.prompt_version,
        "raw_response": analysis.raw_response,
        "input_context_json": json.dumps(analysis.input_context or {}, ensure_ascii=False, sort_keys=True),
        "model_name": analysis.model_name,
        "fallback_used": analysis.fallback_used,
    }



def build_research_trigger_guidance(*, latest_research_at: str | None, latest_trigger_type: str | None, latest_status: str | None, next_review_date: str | None) -> dict[str, Any]:
    now = utc_now().date()
    if not latest_research_at:
        return {'should_trigger': True, 'reason': '从未研究过，建议立即触发', 'freshness': 'missing'}
    try:
        latest_date = datetime.fromisoformat(str(latest_research_at).replace('Z', '')).date()
    except ValueError:
        return {'should_trigger': True, 'reason': '历史研究时间异常，建议重新触发', 'freshness': 'unknown'}
    age_days = (now - latest_date).days
    freshness = 'fresh' if age_days <= 7 else 'aging' if age_days <= 14 else 'stale'
    should_trigger = age_days > 14 or latest_status != 'completed'
    reason = f'最近一次研究距今 {age_days} 天'
    if next_review_date:
        try:
            due_date = datetime.fromisoformat(str(next_review_date)).date()
            if due_date <= now:
                should_trigger = True
                reason = f'已到复查日 {due_date.isoformat()}，建议重跑研究'
        except ValueError:
            pass
    if latest_status != 'completed':
        reason = f'最近一次研究状态为 {latest_status}，建议重新触发'
    if age_days <= 7 and latest_status == 'completed':
        reason = f'最近 {age_days} 天内已完成研究，可复用当前结论'
    return {
        'should_trigger': should_trigger,
        'reason': reason,
        'freshness': freshness,
        'age_days': age_days,
        'latest_trigger_type': latest_trigger_type or '',
    }


GATE_FIELDS = [
    "summary_table",
    "three_sentence_summary",
    "bull_thesis",
    "overall_conclusion",
    "top_risks",
    "valuation",
]

QUALITY_FIELDS = [
    "earnings_bridge",
    "tangible_nav",
    "three_scenario_valuation",
    "trade_plan",
]

STRUCTURED_FIELD_NAMES = [
    "tangible_book_value_per_share",
    "price_to_tbv",
    "normalized_eps",
    "normalized_earnings_yield",
    "net_debt_to_ebitda",
    "interest_coverage",
    "goodwill_pct",
    "intangible_pct",
    "tangible_net_asset_positive",
    "safety_margin_source",
    "buy_range_low",
    "buy_range_high",
    "max_position_pct",
    "target_price_conservative",
    "target_price_base",
    "target_price_optimistic",
    "stop_loss_condition",
    "add_position_condition",
    "reduce_position_condition",
    "overall_conclusion",
    "top_risks_json",
    "invalidation_conditions_json",
    "three_sentence_summary",
    "refinancing_risk",
]


_VALID_OVERALL_CONCLUSIONS = frozenset({'值得投', '不值得投', '仅高风险偏好'})


def _normalize_overall_conclusion(value: Any) -> str | None:
    """Return value only if it is a canonical overall_conclusion; otherwise None."""
    if value is None:
        return None
    val_str = str(value).strip()
    return val_str if val_str in _VALID_OVERALL_CONCLUSIONS else None


def _is_missing_quality_value(value: Any) -> bool:
    if value is None or value == '' or value == []:
        return True
    if isinstance(value, dict):
        return len(value) == 0
    return False


def validate_research_quality(result: dict) -> tuple[str, list[str]]:
    issues: list[str] = []
    for field in GATE_FIELDS:
        if _is_missing_quality_value(result.get(field)):
            issues.append(field)
    if issues:
        return 'fail', issues

    for field in QUALITY_FIELDS:
        if _is_missing_quality_value(result.get(field)):
            issues.append(field)
    if issues:
        return 'partial', issues
    return 'pass', []


def _json_string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return None


def _extract_nested_value(payload: dict[str, Any], *paths: tuple[str, ...] | str) -> Any:
    for path in paths:
        keys = (path,) if isinstance(path, str) else path
        current: Any = payload
        found = True
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                found = False
                break
            current = current[key]
        if found:
            return current
    return None


def extract_structured_fields(raw_result: dict) -> dict:
    payload = raw_result or {}
    return {
        'tangible_book_value_per_share': _as_float(_extract_nested_value(payload, 'tangible_book_value_per_share', ('valuation', 'tangible_book_value_per_share'))),
        'price_to_tbv': _as_float(_extract_nested_value(payload, 'price_to_tbv', ('valuation', 'price_to_tbv'))),
        'normalized_eps': _as_float(_extract_nested_value(payload, 'normalized_eps', ('valuation', 'normalized_eps'))),
        'normalized_earnings_yield': _as_float(_extract_nested_value(payload, 'normalized_earnings_yield', ('valuation', 'normalized_earnings_yield'))),
        'net_debt_to_ebitda': _as_float(_extract_nested_value(payload, 'net_debt_to_ebitda', ('valuation', 'net_debt_to_ebitda'))),
        'interest_coverage': _as_float(_extract_nested_value(payload, 'interest_coverage', ('valuation', 'interest_coverage'))),
        'goodwill_pct': _as_float(_extract_nested_value(payload, 'goodwill_pct', ('valuation', 'goodwill_pct'))),
        'intangible_pct': _as_float(_extract_nested_value(payload, 'intangible_pct', ('valuation', 'intangible_pct'))),
        'tangible_net_asset_positive': 1 if _extract_nested_value(payload, 'tangible_net_asset_positive', ('valuation', 'tangible_net_asset_positive')) in (True, 1, '1') else 0 if _extract_nested_value(payload, 'tangible_net_asset_positive', ('valuation', 'tangible_net_asset_positive')) in (False, 0, '0') else None,
        'safety_margin_source': _extract_nested_value(payload, 'safety_margin_source', ('valuation', 'safety_margin_source')),
        'buy_range_low': _as_float(_extract_nested_value(payload, 'buy_range_low', ('trade_plan', 'buy_range_low'))),
        'buy_range_high': _as_float(_extract_nested_value(payload, 'buy_range_high', ('trade_plan', 'buy_range_high'))),
        'max_position_pct': _as_float(_extract_nested_value(payload, 'max_position_pct', ('trade_plan', 'max_position_pct'))),
        'target_price_conservative': _as_float(_extract_nested_value(payload, 'target_price_conservative', ('three_scenario_valuation', 'target_price_conservative'))),
        'target_price_base': _as_float(_extract_nested_value(payload, 'target_price_base', ('three_scenario_valuation', 'target_price_base'))),
        'target_price_optimistic': _as_float(_extract_nested_value(payload, 'target_price_optimistic', ('three_scenario_valuation', 'target_price_optimistic'))),
        'stop_loss_condition': _extract_nested_value(payload, 'stop_loss_condition', ('trade_plan', 'stop_loss_condition')),
        'add_position_condition': _extract_nested_value(payload, 'add_position_condition', ('trade_plan', 'add_position_condition')),
        'reduce_position_condition': _extract_nested_value(payload, 'reduce_position_condition', ('trade_plan', 'reduce_position_condition')),
        'overall_conclusion': _normalize_overall_conclusion(_extract_nested_value(payload, 'overall_conclusion')),
        'top_risks_json': _json_string_or_none(_extract_nested_value(payload, 'top_risks_json', 'top_risks')),
        'invalidation_conditions_json': _json_string_or_none(_extract_nested_value(payload, 'invalidation_conditions_json', 'invalidation_conditions')),
        'three_sentence_summary': _extract_nested_value(payload, 'three_sentence_summary'),
        'refinancing_risk': _extract_nested_value(payload, 'refinancing_risk'),
    }


@dataclass(frozen=True)
class TwoLayerResearchResult:
    symbol: str
    markdown_report: str
    structured_fields: dict
    quality_level: str
    quality_issues: list[str]
    fallback_used: bool
    provider: str
    prompt_template_id: str
    prompt_version: str
    error_message: str | None


def _fallback_two_layer_payload(symbol: str, stock_context: dict[str, Any]) -> dict[str, Any]:
    derived = derive_research_analysis(stock_context)
    price = _as_float(stock_context.get('price'))
    return {
        'summary_table': {'symbol': symbol, 'price': price},
        'three_sentence_summary': derived.summary,
        'bull_thesis': derived.bull_thesis,
        'overall_conclusion': '值得投' if derived.overall_recommendation in {'strong_buy', 'buy'} else '不值得投' if derived.overall_recommendation == 'sell' else '仅高风险偏好',
        'top_risks': derived.key_risks or [{'type': 'general', 'detail': '需持续跟踪财报与行业景气度', 'severity': 'medium'}],
        'valuation': {
            'valuation_view': derived.valuation_view,
            'target_price': derived.target_price,
            'tangible_book_value_per_share': None,
            'price_to_tbv': None,
            'normalized_eps': None,
            'normalized_earnings_yield': None,
            'net_debt_to_ebitda': None,
            'interest_coverage': None,
            'goodwill_pct': None,
            'intangible_pct': None,
            'tangible_net_asset_positive': None,
            'safety_margin_source': None,
        },
        'earnings_bridge': {'status': 'derived'},
        'tangible_nav': {'status': 'derived'},
        'three_scenario_valuation': {
            'target_price_conservative': round(price * 0.9, 2) if price else None,
            'target_price_base': derived.target_price,
            'target_price_optimistic': round(price * 1.2, 2) if price else None,
        },
        'trade_plan': {
            'buy_range_low': round(price * 0.95, 2) if price else None,
            'buy_range_high': round(price * 1.02, 2) if price else None,
            'max_position_pct': 10.0,
            'stop_loss_condition': derived.invalidation_conditions[0] if derived.invalidation_conditions else None,
            'add_position_condition': '基本面改善且技术形态确认',
            'reduce_position_condition': '估值透支或风险上升',
        },
        'refinancing_risk': '中',
        'invalidation_conditions': derived.invalidation_conditions,
        'markdown_report': derived.summary,
    }


def execute_research_with_two_layer_output(
    symbol: str,
    stock_context: dict,
    skip_dedup: bool = False,
    paths: ProjectPaths | None = None,
) -> TwoLayerResearchResult:
    paths = paths or ProjectPaths()
    app_config = load_app_config(paths)
    settings = load_settings()
    perplexity_cfg = dict(dict(app_config.get('research', {})).get('perplexity', {}))
    prompt_template_id = str(perplexity_cfg.get('prompt_template_id', 'baseline_perplexity_template'))
    prompt_version = str(perplexity_cfg.get('prompt_version', 'v1.0'))
    markdown_report = ''
    structured_fields = {field: None for field in STRUCTURED_FIELD_NAMES}
    quality_level = 'fail'
    quality_issues: list[str] = []
    fallback_used = False
    provider = 'derived'
    error_message: str | None = None

    try:
        prompt = build_perplexity_prompt(stock_context, paths=paths)
        client = PerplexityClient(
            settings.perplexity_api_key,
            settings.perplexity_base_url,
            settings.perplexity_model,
            settings.perplexity_timeout,
        )
        result = client.deep_research(prompt=prompt)
        raw_payload = dict(getattr(result, 'structured', {}) or {})
        # Backfill summary_table and valuation if Perplexity returned empty dicts
        if not raw_payload.get('summary_table'):
            raw_payload['summary_table'] = {
                'symbol': symbol,
                'price': _as_float(stock_context.get('price')),
            }
        if not raw_payload.get('valuation'):
            raw_payload['valuation'] = {'valuation_view': 'neutral', 'target_price': None}
        markdown_report = str(raw_payload.get('markdown_report') or getattr(result, 'raw_text', '') or '')
        structured_fields = extract_structured_fields(raw_payload)
        quality_level, quality_issues = validate_research_quality(raw_payload)
        provider = 'perplexity'
    except PerplexityClientError as exc:
        fallback_used = True
        error_message = str(exc)
        provider = 'perplexity_fallback'
        try:
            fallback_payload = _fallback_two_layer_payload(symbol, stock_context)
            markdown_report = str(fallback_payload.get('markdown_report') or fallback_payload.get('three_sentence_summary') or '')
            structured_fields = extract_structured_fields(fallback_payload)
            quality_level, quality_issues = validate_research_quality(fallback_payload)
            if quality_level == 'fail':
                structured_fields = {field: None for field in STRUCTURED_FIELD_NAMES}
        except Exception as fallback_exc:  # noqa: BLE001
            quality_level = 'fail'
            quality_issues = []
            markdown_report = ''
            structured_fields = {field: None for field in STRUCTURED_FIELD_NAMES}
            error_message = f'{error_message}; fallback_failed: {fallback_exc}'
    except Exception as exc:  # noqa: BLE001
        quality_level = 'fail'
        quality_issues = []
        markdown_report = ''
        structured_fields = {field: None for field in STRUCTURED_FIELD_NAMES}
        provider = 'error'
        error_message = str(exc)

    # markdown_report must never be an empty string (task requirement).
    # All failure paths may produce '' — provide a minimal fallback here.
    if not markdown_report or not markdown_report.strip():
        markdown_report = f"# Research Unavailable\n\n{error_message or '研究报告生成失败，请查看 error_message 字段。'}"

    return TwoLayerResearchResult(
        symbol=symbol,
        markdown_report=markdown_report,
        structured_fields=structured_fields,
        quality_level=quality_level,
        quality_issues=quality_issues,
        fallback_used=fallback_used,
        provider=provider,
        prompt_template_id=prompt_template_id,
        prompt_version=prompt_version,
        error_message=error_message,
    )


def save_two_layer_result(
    symbol: str,
    result: TwoLayerResearchResult,
    input_data: dict | None = None,
    paths: ProjectPaths | None = None,
) -> None:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    now = utc_now().isoformat()
    status = 'completed' if result.quality_level != 'fail' else 'failed'
    with sqlite_connection(paths) as connection:
        cursor = connection.execute(
            """
            INSERT INTO research_snapshot (
                symbol, research_date, trigger_type, trigger_priority,
                prompt_template_id, prompt_version, strategy_id, input_data_json,
                raw_response, status, error_message, retry_count, expires_at
            ) VALUES (?, ?, 'manual', 'P0', ?, ?, 'two_layer_research', ?, ?, ?, ?, 0, ?)
            """,
            (
                symbol,
                now,
                result.prompt_template_id,
                result.prompt_version,
                json.dumps(input_data, ensure_ascii=False, sort_keys=True) if input_data is not None else '{}',
                result.markdown_report,
                status,
                result.error_message,
                now,
            ),
        )
        if result.quality_level == 'fail':
            return
        columns = [
            'research_snapshot_id', 'symbol', 'next_review_date', 'overall_recommendation',
            *STRUCTURED_FIELD_NAMES,
        ]
        values = [
            int(cursor.lastrowid),
            symbol,
            now[:10],
            'hold',
            *[result.structured_fields.get(field) for field in STRUCTURED_FIELD_NAMES],
        ]
        placeholders = ', '.join('?' for _ in columns)
        connection.execute(
            f"INSERT INTO research_analysis ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
