from __future__ import annotations

from .time_utils import utc_now
from typing import Any


BASE_WEIGHTS = {
    'fundamental_quality': 0.25,
    'valuation_attractiveness': 0.20,
    'research_conclusion': 0.15,
    'catalyst': 0.10,
    'risk': 0.15,
    'technical_timing': 0.10,
    'execution_priority': 0.05,
}


def _to_float(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_range(value: float | None, levels: list[tuple[float, float]], *, reverse: bool = False, default: float = 0.0) -> float:
    if value is None:
        return default
    for threshold, score in levels:
        if reverse:
            if value < threshold:
                return score
        else:
            if value >= threshold:
                return score
    return default


def _fundamental_quality(ratios: dict[str, Any]) -> tuple[float, dict[str, float]]:
    roe = _to_float(ratios.get('roeRatioTTM') or ratios.get('returnOnEquityTTM'))
    margin = _to_float(ratios.get('netProfitMarginTTM'))
    debt = _to_float(ratios.get('debtToEquityRatioTTM') or ratios.get('debtEquityRatioTTM'))
    current_ratio = _to_float(ratios.get('currentRatioTTM'))

    roe_score = _score_range(roe, [(0.20, 35), (0.15, 28), (0.10, 20), (0.05, 10)])
    margin_score = _score_range(margin, [(0.30, 30), (0.20, 24), (0.15, 18), (0.10, 12)])
    debt_score = _score_range(debt, [(0.3, 20), (0.5, 16), (1.0, 12), (1.5, 6)], reverse=True)
    current_ratio_score = _score_range(current_ratio, [(2.0, 15), (1.5, 12), (1.2, 9), (1.0, 5)])

    total = roe_score + margin_score + debt_score + current_ratio_score
    return float(total), {
        'fq_roe_score': float(roe_score),
        'fq_margin_score': float(margin_score),
        'fq_debt_score': float(debt_score),
        'fq_current_ratio_score': float(current_ratio_score),
    }


def _valuation_attractiveness(ratios: dict[str, Any]) -> tuple[float, dict[str, float]]:
    pe = _to_float(ratios.get('priceToEarningsRatioTTM') or ratios.get('peRatioTTM'))
    pb = _to_float(ratios.get('priceToBookRatioTTM'))
    ev = _to_float(ratios.get('enterpriseValueMultipleTTM'))

    if pe is None or pe < 0:
        pe_score = 0
    elif pe < 10:
        pe_score = 50
    elif pe < 15:
        pe_score = 40
    elif pe < 20:
        pe_score = 30
    elif pe < 25:
        pe_score = 20
    elif pe < 30:
        pe_score = 10
    else:
        pe_score = 0

    if pb is None:
        pb_score = 0
    elif pb < 1.5:
        pb_score = 30
    elif pb < 2.5:
        pb_score = 24
    elif pb < 3.5:
        pb_score = 18
    elif pb < 5.0:
        pb_score = 10
    else:
        pb_score = 0

    if ev is None:
        ev_score = 0
    elif ev < 8:
        ev_score = 20
    elif ev < 12:
        ev_score = 15
    elif ev < 16:
        ev_score = 10
    elif ev < 20:
        ev_score = 5
    else:
        ev_score = 0

    total = pe_score + pb_score + ev_score
    return float(total), {
        'va_pe_score': float(pe_score),
        'va_pb_score': float(pb_score),
        'va_ev_ebitda_score': float(ev_score),
    }


def _research_conclusion(analysis: dict[str, Any] | None) -> float:
    if not analysis:
        return 0.0
    confidence = max(0, min(int(analysis.get('confidence_score', 0) or 0), 100)) * 0.4
    bull = len(list(analysis.get('bull_thesis', [])))
    bear = len(list(analysis.get('bear_thesis', [])))
    total = bull + bear
    bull_bear = (bull / total * 30) if total > 0 else 15
    high_impact = sum(1 for item in list(analysis.get('catalysts', [])) if str(item.get('impact', '')).lower() == 'high')
    catalyst_strength = min(high_impact * 10, 30)
    return float(confidence + bull_bear + catalyst_strength)


def _catalyst_score(analysis: dict[str, Any] | None, earnings_days: int | None) -> float:
    if earnings_days is None:
        earnings_score = 5
    elif earnings_days <= 14:
        earnings_score = 40
    elif earnings_days <= 30:
        earnings_score = 25
    elif earnings_days <= 60:
        earnings_score = 15
    else:
        earnings_score = 5

    sector_score = 20
    positive_catalysts = 0
    if analysis:
        positive_catalysts = sum(1 for item in list(analysis.get('catalysts', [])) if str(item.get('sentiment', '')).lower() == 'positive')
    news_score = min(positive_catalysts * 10, 30)
    return float(earnings_score + sector_score + news_score)


def _risk_score(analysis: dict[str, Any] | None, atr_pct: float | None, holding_count_by_sector: int = 0) -> float:
    if holding_count_by_sector < 2:
        concentration = 30
    elif holding_count_by_sector < 3:
        concentration = 20
    elif holding_count_by_sector < 4:
        concentration = 10
    else:
        concentration = 0

    if atr_pct is None:
        volatility = 15
    elif atr_pct < 3:
        volatility = 35
    elif atr_pct < 5:
        volatility = 25
    elif atr_pct < 8:
        volatility = 15
    else:
        volatility = 5

    risk_count = len(list((analysis or {}).get('key_risks', [])))
    if risk_count == 0:
        research_risk = 35
    elif risk_count == 1:
        research_risk = 28
    elif risk_count == 2:
        research_risk = 21
    elif risk_count == 3:
        research_risk = 14
    else:
        research_risk = 7

    return float(concentration + volatility + research_risk)


def _execution_priority(market_cap: float | None, avg_volume: float | None, missing_dimensions: list[str]) -> float:
    if market_cap is None:
        market_cap_score = 0
    elif market_cap > 10_000_000_000:
        market_cap_score = 40
    elif market_cap > 5_000_000_000:
        market_cap_score = 30
    elif market_cap > 2_000_000_000:
        market_cap_score = 20
    elif market_cap > 500_000_000:
        market_cap_score = 10
    else:
        market_cap_score = 0

    if avg_volume is None:
        liquidity_score = 5
    elif avg_volume > 5_000_000:
        liquidity_score = 30
    elif avg_volume > 2_000_000:
        liquidity_score = 22
    elif avg_volume > 1_000_000:
        liquidity_score = 15
    else:
        liquidity_score = 5

    missing_count = len(missing_dimensions)
    if missing_count == 0:
        completeness = 30
    elif missing_count == 1:
        completeness = 20
    elif missing_count == 2:
        completeness = 10
    else:
        completeness = 0

    return float(market_cap_score + liquidity_score + completeness)


def _is_earnings_season(now: datetime) -> bool:
    month = now.month
    day = now.day
    return (month in {1, 4, 7, 10} and day >= 15) or (month in {2, 5, 8, 11} and day <= 15)


def _apply_dynamic_weights(base_weights: dict[str, float], *, market_trend: str, earnings_season: bool) -> tuple[dict[str, float], list[dict[str, Any]], str]:
    weights = dict(base_weights)
    adjustments: list[dict[str, Any]] = []
    profile = 'default'

    if market_trend == 'bear':
        profile = 'bear_market'
        for dimension, delta in {
            'valuation_attractiveness': 0.05,
            'technical_timing': 0.05,
            'catalyst': -0.05,
            'execution_priority': -0.05,
        }.items():
            weights[dimension] = max(0.0, weights[dimension] + delta)
            adjustments.append({'rule_id': 'WGT_001', 'rule_name': 'bear_market', 'dimension': dimension, 'delta': delta, 'status': 'applied'})

    if earnings_season:
        if profile == 'default':
            profile = 'earnings_season'
        for dimension, delta in {
            'catalyst': 0.05,
            'research_conclusion': 0.05,
            'valuation_attractiveness': -0.05,
            'execution_priority': -0.05,
        }.items():
            weights[dimension] = max(0.0, weights[dimension] + delta)
            adjustments.append({'rule_id': 'WGT_002', 'rule_name': 'earnings_season', 'dimension': dimension, 'delta': delta, 'status': 'applied'})

    weights['execution_priority'] = min(weights['execution_priority'], 0.10)
    weights['risk'] = min(weights['risk'], 0.25)
    return weights, adjustments, profile


def _redistribute_missing(weights: dict[str, float], missing_dimensions: list[str]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    adjustments: list[dict[str, Any]] = []
    result = dict(weights)
    for dimension in missing_dimensions:
        if dimension == 'research_conclusion':
            freed = result.get(dimension, 0.0)
            result[dimension] = 0.0
            for target, delta in [('fundamental_quality', freed / 3), ('valuation_attractiveness', freed / 3), ('risk', freed / 3)]:
                result[target] += delta
                adjustments.append({'rule_id': 'MISS_001', 'rule_name': 'missing_research', 'dimension': target, 'delta': delta, 'status': 'applied'})
        elif dimension == 'technical_timing':
            freed = result.get(dimension, 0.0)
            result[dimension] = 0.0
            for target, delta in [('risk', freed / 2), ('fundamental_quality', freed / 2)]:
                result[target] += delta
                adjustments.append({'rule_id': 'MISS_002', 'rule_name': 'missing_technical', 'dimension': target, 'delta': delta, 'status': 'applied'})
    total = sum(result.values()) or 1.0
    normalized = {key: value / total for key, value in result.items()}
    return normalized, adjustments


def build_scoring_payload(
    stock: dict[str, Any],
    *,
    market_trend: str = 'default',
    technical_timing: float = 0.0,
    technical_signal: str = 'wait',
    price_stale: bool = False,
    research_analysis: dict[str, Any] | None = None,
    earnings_days_until: int | None = None,
    holding_count_by_sector: int = 0,
    avg_volume: float | None = None,
    market_cap: float | None = None,
) -> dict[str, Any]:
    ratios = dict(stock.get('ratios', {}))
    now = utc_now()

    fundamental_quality, fq_details = _fundamental_quality(ratios)
    valuation_attractiveness, va_details = _valuation_attractiveness(ratios)
    research_conclusion = _research_conclusion(research_analysis)
    catalyst = _catalyst_score(research_analysis, earnings_days_until)
    risk = _risk_score(research_analysis, _to_float(stock.get('atr_pct')) or _to_float((stock.get('technical', {}) or {}).get('atr_pct')) or None, holding_count_by_sector)
    technical_timing_value = float(technical_timing or 0)

    missing_dimensions: list[str] = []
    if not research_analysis:
        missing_dimensions.append('research_conclusion')
    if price_stale:
        missing_dimensions.append('technical_timing')

    execution_priority = _execution_priority(
        market_cap if market_cap is not None else _to_float(stock.get('marketCap')),
        avg_volume if avg_volume is not None else _to_float(stock.get('volume') or stock.get('avgVolume') or stock.get('volAvg')),
        missing_dimensions,
    )

    dimensions = {
        'fundamental_quality': float(fundamental_quality),
        'valuation_attractiveness': float(valuation_attractiveness),
        'research_conclusion': float(research_conclusion),
        'catalyst': float(catalyst),
        'risk': float(risk),
        'technical_timing': technical_timing_value,
        'execution_priority': float(execution_priority),
    }

    weights, weight_adjustments, weight_profile = _apply_dynamic_weights(
        BASE_WEIGHTS,
        market_trend='bear' if market_trend == 'bear' else 'default',
        earnings_season=_is_earnings_season(now),
    )
    applied_weights, missing_adjustments = _redistribute_missing(weights, missing_dimensions)
    weight_adjustments.extend(missing_adjustments)

    total_score = sum(dimensions[name] * applied_weights[name] for name in BASE_WEIGHTS)
    score_change_reason = None
    if missing_dimensions:
        score_change_reason = 'missing_dimensions_redistributed'
    elif technical_signal in {'strong_buy', 'buy'}:
        score_change_reason = 'technical_signal_improved'

    return {
        'formula_version': 'v1.0',
        'weight_profile': weight_profile,
        'applied_weights': applied_weights,
        'weight_adjustments': weight_adjustments,
        'trigger_context': {
            'market_trend': market_trend,
            'earnings_season': _is_earnings_season(now),
            'missing_dimensions': missing_dimensions,
        },
        'dimensions': dimensions,
        'details': {
            **fq_details,
            **va_details,
        },
        'missing_dimensions': missing_dimensions,
        'partial_score': bool(missing_dimensions),
        'total_score': round(float(total_score), 2),
        'score_change_reason': score_change_reason,
    }
