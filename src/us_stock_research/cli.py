from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from typing import Any

from .config import DEFAULT_STRATEGY_NAME, ProjectPaths, list_strategy_names
from .event_notifications import (
    build_daily_summary_notification,
    build_event_payload,
    create_notification_event,
    flush_pending_notifications,
    send_alert_notifications_for_symbol,
)
from .feishu_doc import FeishuDocError, create_research_doc, write_doc_url_to_db
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .position_manager import get_position, record_buy, record_sell
from .research_engine import execute_research_with_two_layer_output, save_two_layer_result
from .research_queue import RESEARCH_INTERVAL_SECONDS, build_research_batch
from .service import run_screening
from .tracking_workflow import execute_reresearch, run_daily_monitoring
from .alert_manager import AlertManager
from .utils import new_correlation_id




def positive_score(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return max(float(value), 0.0)


def numeric_value(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None or value == '':
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def derive_roe(ratios: dict[str, Any]) -> float | None:
    roe = numeric_value(ratios, 'roeRatioTTM', 'returnOnEquityTTM')
    if roe is not None:
        return roe
    net_margin = numeric_value(ratios, 'netProfitMarginTTM')
    asset_turnover = numeric_value(ratios, 'assetTurnoverTTM')
    leverage = numeric_value(ratios, 'financialLeverageRatioTTM')
    if net_margin is not None and asset_turnover is not None and leverage is not None:
        dupont_roe = net_margin * asset_turnover * leverage
        if 0 < dupont_roe <= 10:
            return dupont_roe
    net_income_per_share = numeric_value(ratios, 'netIncomePerShareTTM')
    equity_per_share = numeric_value(ratios, 'shareholdersEquityPerShareTTM')
    if net_income_per_share is not None and equity_per_share is not None and equity_per_share > 0:
        per_share_roe = net_income_per_share / equity_per_share
        if 0 < per_share_roe <= 10:
            return per_share_roe
    if net_margin is not None and asset_turnover is not None:
        debt_to_assets = numeric_value(ratios, 'debtToAssetsRatioTTM')
        if debt_to_assets is not None and debt_to_assets < 1:
            estimated_leverage = 1 / (1 - debt_to_assets)
            estimated_roe = net_margin * asset_turnover * estimated_leverage
            if 0 < estimated_roe <= 10:
                return estimated_roe
    return None


def current_ratio_score(current_ratio: float | None) -> tuple[float, str]:
    if current_ratio is None:
        return 0.0, '流动比率数据缺失'
    if current_ratio >= 2.0:
        return 10.0, f'流动比率 {current_ratio:.2f}，短期偿债能力强'
    if current_ratio >= 1.5:
        return 7.0, f'流动比率 {current_ratio:.2f}，流动性良好'
    if current_ratio >= 1.2:
        return 4.0, f'流动比率 {current_ratio:.2f}，流动性尚可'
    return 0.0, f'流动比率 {current_ratio:.2f}，流动性偏弱'


def debt_score(debt_to_equity: float | None) -> tuple[float, str]:
    if debt_to_equity is None:
        return 0.0, '负债率数据缺失'
    if debt_to_equity < 0:
        return 0.0, f'负债权益比 {debt_to_equity:.2f}，数据异常'
    if debt_to_equity < 1.0:
        return 20.0, f'负债权益比 {debt_to_equity:.2f}，财务结构稳健'
    if debt_to_equity < 1.5:
        return 12.0, f'负债权益比 {debt_to_equity:.2f}，杠杆可接受'
    if debt_to_equity < 2.0:
        return 5.0, f'负债权益比 {debt_to_equity:.2f}，杠杆偏高'
    return 0.0, f'负债权益比 {debt_to_equity:.2f}，杠杆过高'


def format_market_cap(value: float | int | None) -> str:
    if value is None:
        return 'N/A'
    value = float(value)
    if value >= 1_000_000_000_000:
        return f'${value / 1_000_000_000_000:.2f}T'
    return f'${value / 1_000_000_000:.2f}B'


def market_cap_score(market_cap: float | None) -> tuple[float, str]:
    if market_cap is None or market_cap <= 0:
        return 0.0, '市值数据缺失'
    if market_cap >= 10_000_000_000:
        return 10.0, f'市值 {format_market_cap(market_cap)}，流动性和稳定性较好'
    if market_cap >= 5_000_000_000:
        return 5.0, f'市值 {format_market_cap(market_cap)}，具备中大盘基础'
    return 0.0, f'市值 {format_market_cap(market_cap)}，规模偏小'


def pe_score(pe: float | None) -> tuple[float, str]:
    if pe is None:
        return 0.0, 'PE 数据缺失'
    if pe <= 0:
        return 0.0, f'PE {pe:.2f}，盈利异常或估值无效'
    if pe < 15:
        score = 40 * (1 - pe / 15)
        return round(score, 2), f'PE {pe:.2f}，估值便宜'
    if pe < 25:
        score = 20 * (1 - pe / 25)
        return round(score, 2), f'PE {pe:.2f}，估值合理'
    if pe < 30:
        score = max(20 * (1 - pe / 25), 0)
        return round(score, 2), f'PE {pe:.2f}，估值略高'
    return 0.0, f'PE {pe:.2f}，估值偏高'


def pb_score(pb: float | None) -> tuple[float, str]:
    if pb is None:
        return 0.0, 'PB 数据缺失'
    if pb <= 0:
        return 0.0, f'PB {pb:.2f}，账面价值无效'
    if pb < 2:
        return 10.0, f'PB {pb:.2f}，资产定价便宜'
    if pb < 5:
        return 0.0, f'PB {pb:.2f}，资产定价可接受'
    return 0.0, f'PB {pb:.2f}，资产定价偏高'


def profitability_score(roe: float | None, net_margin: float | None) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    roe_available = roe is not None and roe > 0
    if roe is None:
        reasons.append('ROE 数据缺失，盈利能力评分降权')
    elif roe > 0.20:
        score += 30.0
        reasons.append(f'ROE {roe * 100:.1f}%，盈利能力优秀')
    elif roe > 0.10:
        score += 20.0
        reasons.append(f'ROE {roe * 100:.1f}%，盈利能力良好')
    elif roe > 0:
        reasons.append(f'ROE {roe * 100:.1f}%，盈利能力一般')
    else:
        reasons.append(f'ROE {roe * 100:.1f}%，盈利质量不足')

    if net_margin is None:
        reasons.append('净利率数据缺失')
    elif net_margin > 0.20:
        margin_score = 10.0 if roe_available else 3.0
        score += margin_score
        suffix = '' if roe_available else '（ROE缺失，保守加分）'
        reasons.append(f'净利率 {net_margin * 100:.1f}%，利润率优秀{suffix}')
    elif net_margin > 0.15:
        margin_score = 5.0 if roe_available else 1.5
        score += margin_score
        suffix = '' if roe_available else '（ROE缺失，保守加分）'
        reasons.append(f'净利率 {net_margin * 100:.1f}%，利润率良好{suffix}')
    elif net_margin > 0:
        reasons.append(f'净利率 {net_margin * 100:.1f}%，利润率一般')
    else:
        reasons.append(f'净利率 {net_margin * 100:.1f}%，利润率偏弱')
    return round(score, 2), reasons


def calculate_score(stock: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    ratios = stock.get('ratios', {})
    pe = numeric_value(ratios, 'priceToEarningsRatioTTM')
    pb = numeric_value(ratios, 'priceToBookRatioTTM')
    roe = derive_roe(ratios)
    net_margin = numeric_value(ratios, 'netProfitMarginTTM')
    debt_to_equity = numeric_value(ratios, 'debtToEquityRatioTTM')
    current_ratio = numeric_value(ratios, 'currentRatioTTM')
    market_cap = numeric_value(stock, 'marketCap')
    valuation_total = 0.0
    valuation_notes: list[str] = []
    pe_points, pe_reason = pe_score(pe)
    pb_points, pb_reason = pb_score(pb)
    valuation_total += pe_points + pb_points
    valuation_notes.extend([pe_reason, pb_reason])
    profitability_total, profitability_notes = profitability_score(roe, net_margin)
    health_total = 0.0
    health_notes: list[str] = []
    debt_points, debt_reason = debt_score(debt_to_equity)
    current_ratio_points, current_ratio_reason = current_ratio_score(current_ratio)
    health_total += debt_points + current_ratio_points
    health_notes.extend([debt_reason, current_ratio_reason])
    scale_total, scale_reason = market_cap_score(market_cap)
    total = round(valuation_total + profitability_total + health_total + scale_total, 2)
    detail = {
        'valuation': {'score': round(valuation_total, 2), 'notes': valuation_notes},
        'profitability': {'score': round(profitability_total, 2), 'notes': profitability_notes},
        'financial_health': {'score': round(health_total, 2), 'notes': health_notes},
        'scale': {'score': round(scale_total, 2), 'notes': [scale_reason]},
        'metrics': {
            'pe': pe, 'pb': pb, 'roe': roe, 'netProfitMargin': net_margin,
            'debtToEquity': debt_to_equity, 'currentRatio': current_ratio, 'marketCap': market_cap,
        },
    }
    return total, detail


def ranking_gates(ranking: dict[str, Any] | None) -> dict[str, Any]:
    raw_gates = ranking.get('gates', {}) if isinstance(ranking, dict) else {}
    return {
        'max_pe': float(raw_gates.get('max_pe', 30)),
        'max_pb': float(raw_gates.get('max_pb', 5)),
        'min_valuation_score': float(raw_gates.get('min_valuation_score', 2)),
        'require_positive_pe': bool(raw_gates.get('require_positive_pe', True)),
        'require_positive_pb': bool(raw_gates.get('require_positive_pb', True)),
        'min_roe_for_quality': float(raw_gates.get('min_roe_for_quality', 0.10)),
    }


def evaluate_candidate_eligibility(detail: dict[str, Any], ranking: dict[str, Any] | None = None) -> dict[str, Any]:
    gates = ranking_gates(ranking)
    metrics = detail.get('metrics', {})
    valuation = detail.get('valuation', {})
    reasons: list[str] = []
    pe = metrics.get('pe')
    pb = metrics.get('pb')
    valuation_score = float(valuation.get('score', 0) or 0)
    if gates['require_positive_pe'] and (pe is None or pe <= 0):
        reasons.append('PE 不可用，无法满足低估值策略要求')
    elif pe is not None and pe > gates['max_pe']:
        reasons.append(f"PE {pe:.2f} 超过门槛 {gates['max_pe']:.2f}")
    if gates['require_positive_pb'] and (pb is None or pb <= 0):
        reasons.append('PB 不可用，无法满足低估值策略要求')
    elif pb is not None and pb > gates['max_pb']:
        reasons.append(f"PB {pb:.2f} 超过门槛 {gates['max_pb']:.2f}")
    if valuation_score < gates['min_valuation_score']:
        reasons.append(f"估值得分 {valuation_score:.2f} 低于门槛 {gates['min_valuation_score']:.2f}")
    return {'passed': not reasons, 'reasons': reasons or ['通过估值门槛'], 'gates': gates}


def candidate_tier(detail: dict[str, Any], ranking: dict[str, Any] | None = None) -> dict[str, str | bool]:
    gates = ranking_gates(ranking)
    metrics = detail.get('metrics', {})
    roe = metrics.get('roe')
    if roe is None:
        return {'code': 'roe_pending', 'label': 'ROE待补充', 'summary': '估值通过，但 ROE 缺失，需补充盈利质量验证', 'strict_quality_pass': False}
    if roe >= gates['min_roe_for_quality']:
        return {'code': 'strict_pass', 'label': '严格通过', 'summary': f"估值通过，且 ROE 达到 {gates['min_roe_for_quality'] * 100:.0f}% 质量线", 'strict_quality_pass': True}
    return {'code': 'quality_watch', 'label': '质量待观察', 'summary': f"估值通过，但 ROE 低于 {gates['min_roe_for_quality'] * 100:.0f}% 质量线", 'strict_quality_pass': False}


def stock_status(stock: dict[str, Any], index: int) -> str:
    tier = stock.get('scoreDetail', {}).get('tier', {})
    code = tier.get('code')
    if code == 'strict_pass':
        return '通过' if index <= 3 else '待研究'
    if code == 'roe_pending':
        return 'ROE待补充'
    if code == 'quality_watch':
        return '质量待观察'
    return '待研究'


def enrich_candidates(client: Any, candidates: list[dict[str, Any]], ranking: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    for candidate in candidates:
        symbol = candidate.get('symbol')
        if not symbol:
            continue
        ratios = client.ratios_ttm(symbol)
        if not ratios:
            continue
        stock = dict(candidate)
        stock['ratios'] = ratios
        score, detail = calculate_score(stock)
        eligibility = evaluate_candidate_eligibility(detail, ranking)
        detail['eligibility'] = eligibility
        detail['tier'] = candidate_tier(detail, ranking) if eligibility['passed'] else {'code': 'rejected', 'label': '已拒绝', 'summary': '未通过估值门槛，不进入候选池', 'strict_quality_pass': False}
        stock['score'] = score
        stock['scoreDetail'] = detail
        evaluated.append(stock)
    evaluated.sort(key=lambda item: item.get('score', 0), reverse=True)
    return [stock for stock in evaluated if stock.get('scoreDetail', {}).get('eligibility', {}).get('passed')]

def evaluate_candidates(client: Any, candidates: list[dict[str, Any]], ranking: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    for candidate in candidates:
        symbol = candidate.get('symbol')
        if not symbol:
            continue
        ratios = client.ratios_ttm(symbol)
        if not ratios:
            continue
        stock = dict(candidate)
        stock['ratios'] = ratios
        score, detail = calculate_score(stock)
        eligibility = evaluate_candidate_eligibility(detail, ranking)
        detail['eligibility'] = eligibility
        detail['tier'] = candidate_tier(detail, ranking) if eligibility['passed'] else {'code': 'rejected', 'label': '已拒绝', 'summary': '未通过估值门槛，不进入候选池', 'strict_quality_pass': False}
        stock['score'] = score
        stock['scoreDetail'] = detail
        evaluated.append(stock)
    return sorted(evaluated, key=lambda item: item.get('score', 0), reverse=True)


def format_currency(value: float | int | None) -> str:
    if value is None:
        return 'N/A'
    return f'${float(value):,.2f}'


def format_ratio(value: float | int | None, multiplier: float = 1.0, suffix: str = '') -> str:
    if value is None:
        return 'N/A'
    return f'{float(value) * multiplier:.2f}{suffix}'


def recommendation(score: float) -> str:
    if score >= 60:
        return '✅ 强烈关注'
    if score >= 45:
        return '⚠️ 优先观察'
    if score >= 30:
        return '🟡 可跟踪'
    return '❌ 暂不优先'


def build_candidate_markdown(stocks: list[dict[str, Any]], timestamp: datetime, strategy_name: str) -> str:
    top_n = min(len(stocks), 15)
    lines = ['---', 'title: 美股候选股筛选结果', f'generated: {timestamp.strftime("%Y-%m-%d")}', 'data_source: FMP stable/company-screener + ratios-ttm', f'strategy: {strategy_name}', '---', '', '# 美股候选股筛选结果', '', f'**生成时间**: {timestamp.strftime("%Y-%m-%d %H:%M:%S")}', f'**候选数量**: {len(stocks)}', f'**策略**: {strategy_name}', '', '---', '', f'## Top {top_n} 候选股', '', '| Rank | Ticker | Company | Price | PE | PB | ROE | D/E | Current Ratio | Score | Status |', '|------|--------|---------|-------|----|----|-----|-----|---------------|-------|--------|']
    for index, stock in enumerate(stocks[:top_n], start=1):
        metrics = stock['scoreDetail']['metrics']
        lines.append(f"| {index} | {stock.get('symbol', '')} | {stock.get('companyName', '')} | {format_currency(stock.get('price'))} | {format_ratio(metrics.get('pe'))} | {format_ratio(metrics.get('pb'))} | {format_ratio(metrics.get('roe'), 100, '%')} | {format_ratio(metrics.get('debtToEquity'))} | {format_ratio(metrics.get('currentRatio'))} | {stock.get('score', 0):.2f} | {stock['scoreDetail']['tier']['label']} |")
    return '\n'.join(lines) + '\n'


def build_top3_markdown(stocks: list[dict[str, Any]], timestamp: datetime, strategy_name: str) -> str:
    lines = ['# 本周 Top 3 候选股', '', f'**筛选日期**：{timestamp.strftime("%Y-%m-%d")}', f'**策略**：{strategy_name}', '']
    for index, stock in enumerate(stocks[:3], start=1):
        lines.extend([f"## Top {index}: {stock.get('symbol', '')} - {stock.get('companyName', '')}", '', f"- 候选分层: {stock['scoreDetail']['tier']['label']}", f"- 评分: {stock.get('score', 0):.2f}", ''])
    return '\n'.join(lines) + '\n'


def build_watchlist_markdown(stocks: list[dict[str, Any]], timestamp: datetime, strategy_name: str) -> str:
    lines = ['# 候选股清单', '', f'**策略**：{strategy_name}', '', '| # | Ticker | 公司名称 | 评分 | 状态 |', '|---|--------|----------|------|------|']
    for index, stock in enumerate(stocks[:20], start=1):
        lines.append(f"| {index} | {stock.get('symbol', '')} | {stock.get('companyName', '')} | {stock.get('score', 0):.2f} | {stock_status(stock, index)} |")
    return '\n'.join(lines) + '\n'


def write_outputs(paths: ProjectPaths, stocks: list[dict[str, Any]], strategy_name: str, timestamp: datetime | None = None) -> dict[str, Any]:
    timestamp = timestamp or datetime.now()
    slug = timestamp.strftime('%Y%m%d_%H%M%S')
    json_path = paths.outputs_dir / f'FMP筛选结果_{slug}.json'
    report_path = paths.outputs_dir / f'FMP筛选报告_{slug}.md'
    candidate_path = paths.watchlist_dir / '候选股-自动筛选.md'
    top3_path = paths.watchlist_dir / '本周Top3.md'
    watchlist_path = paths.watchlist_dir / '候选股.md'
    payload = json.dumps(stocks, ensure_ascii=False, indent=2)
    json_path.write_text(payload, encoding='utf-8')
    report_path.write_text(build_candidate_markdown(stocks, timestamp, strategy_name), encoding='utf-8')
    candidate_path.write_text(build_candidate_markdown(stocks, timestamp, strategy_name), encoding='utf-8')
    top3_path.write_text(build_top3_markdown(stocks, timestamp, strategy_name), encoding='utf-8')
    watchlist_path.write_text(build_watchlist_markdown(stocks, timestamp, strategy_name), encoding='utf-8')
    return {'json': json_path, 'report': report_path, 'candidate': candidate_path, 'top3': top3_path, 'watchlist': watchlist_path}

def _today_str() -> str:
    return date.today().isoformat()


def _prompt_text(label: str, default: str | None = None) -> str:
    prompt = f"{label}"
    if default is not None:
        prompt += f" [{default}]"
    prompt += ": "
    value = input(prompt).strip()
    if value:
        return value
    return default or ""


def _prompt_float(label: str, default: float | None = None) -> float:
    raw_default = None if default is None else str(default)
    value = _prompt_text(label, raw_default)
    return float(value)


def _prompt_int(label: str, default: int | None = None) -> int:
    raw_default = None if default is None else str(default)
    value = _prompt_text(label, raw_default)
    return int(value)


def _load_stock_context(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT symbol, company_name, sector, exchange,
                   COALESCE(current_price, latest_price),
                   COALESCE(market_cap, latest_market_cap),
                   avg_volume
            FROM stock_master
            WHERE symbol = ?
            """,
            (symbol,),
        ).fetchone()
    if row is None:
        return {
            'symbol': symbol,
            'company_name': symbol,
            'sector': None,
            'exchange': None,
            'price': None,
            'marketCap': None,
            'volume': None,
        }
    return {
        'symbol': str(row[0]),
        'company_name': str(row[1] or symbol),
        'sector': row[2],
        'exchange': row[3],
        'price': row[4],
        'marketCap': row[5],
        'volume': row[6],
    }


def _effective_quality_level(result: Any) -> str:
    return 'fallback' if bool(getattr(result, 'fallback_used', False)) else str(getattr(result, 'quality_level', 'fail'))


def _create_doc_for_result(symbol: str, company_name: str, result: Any, paths: ProjectPaths | None = None, title_prefix: str | None = None) -> str:
    quality_level = _effective_quality_level(result)
    if quality_level == 'fail':
        return ''
    try:
        doc_url = create_research_doc(
            symbol=symbol,
            company_name=company_name,
            markdown_report=str(getattr(result, 'markdown_report', '') or ''),
            quality_level=quality_level,
            title_prefix=title_prefix,
        )
    except FeishuDocError:
        return ''
    if doc_url:
        write_doc_url_to_db(symbol, doc_url, paths=paths)
    return doc_url


def _build_batch_result_item(symbol: str, status: str, summary: str, doc_url: str = '', reuse_date: str | None = None) -> dict[str, Any]:
    payload = {'symbol': symbol, 'status': status, 'summary': summary, 'doc_url': doc_url}
    if reuse_date:
        payload['reuse_date'] = reuse_date
    return payload


def print_run_summary(result: dict[str, Any]) -> None:
    print('===== 执行摘要 =====')
    print(f"候选: {int(result.get('candidate_count', 0))}")
    print(f"queued: {int(result.get('queued_count', 0))} | reused: {int(result.get('reused_count', 0))} | pending: {int(result.get('pending_count', 0))} | ignored: {int(result.get('ignored_count', 0))}")
    print(f"研究完成: {int(result.get('researched_count', 0))} | 成功文档: {int(result.get('doc_count', 0))}")
    if result.get('summary_notification_sent') is not None:
        print(f"汇总通知: {'yes' if result.get('summary_notification_sent') else 'no'}")
    print('====================')


def cmd_run(notify: bool = False, strategy_name: str = DEFAULT_STRATEGY_NAME, limit_override: int | None = None, top_n: int = 10, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    screening = run_screening(strategy_name, limit_override=limit_override, top_n=top_n, paths=paths)
    candidates = list(screening.get('stocks') or [])
    batch = build_research_batch(candidates, paths=paths)
    correlation_id = new_correlation_id()
    batch_results: list[dict[str, Any]] = []
    researched_count = 0
    doc_count = 0

    for item in batch.get('reused', []):
        batch_results.append(_build_batch_result_item(str(item.get('symbol')), 'reused', '复用历史研究', reuse_date=item.get('last_research_date')))
    for item in batch.get('pending_next_batch', []):
        batch_results.append(_build_batch_result_item(str(item.get('symbol')), 'pending', '超过日配额，顺延下一批'))
    for item in batch.get('ignored', []):
        batch_results.append(_build_batch_result_item(str(item.get('symbol')), 'pending', '用户已忽略'))

    queued = list(batch.get('queued', []))
    for index, item in enumerate(queued):
        symbol = str(item.get('symbol') or '').strip().upper()
        if not symbol:
            continue
        stock_context = _load_stock_context(symbol, paths=paths)
        result = execute_research_with_two_layer_output(symbol, stock_context, paths=paths)
        save_two_layer_result(symbol, result, input_data=stock_context, paths=paths)
        researched_count += 1
        quality_level = _effective_quality_level(result)
        doc_url = _create_doc_for_result(symbol, str(stock_context.get('company_name') or symbol), result, paths=paths)
        if doc_url:
            doc_count += 1
        status = {'fail': 'failed', 'pass': 'success', 'fallback': 'fallback', 'partial': 'fallback'}.get(quality_level, 'pending')
        summary = f'quality={quality_level}'
        batch_results.append(_build_batch_result_item(symbol, status, summary, doc_url=doc_url))
        if len(queued) > 1 and index < len(queued) - 1:
            time.sleep(RESEARCH_INTERVAL_SECONDS)

    should_send_summary = notify or any(item.get('status') in {'success', 'fallback', 'reused'} for item in batch_results)
    summary_notification_sent = False
    if should_send_summary:
        notification = build_daily_summary_notification(batch_results, correlation_id, paths=paths)
        summary_notification_sent = bool(notification.get('created'))

    result_payload = {
        'candidate_count': len(candidates),
        'queued_count': len(batch.get('queued', [])),
        'reused_count': len(batch.get('reused', [])),
        'pending_count': len(batch.get('pending_next_batch', [])),
        'ignored_count': len(batch.get('ignored', [])),
        'researched_count': researched_count,
        'doc_count': doc_count,
        'summary_notification_sent': summary_notification_sent,
        'batch_results': batch_results,
    }
    print_run_summary(result_payload)
    flush_pending_notifications(paths=paths)
    return 0


def cmd_research(symbol: str, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    normalized_symbol = symbol.strip().upper()
    stock_context = _load_stock_context(normalized_symbol, paths=paths)
    result = execute_research_with_two_layer_output(normalized_symbol, stock_context, skip_dedup=True, paths=paths)
    save_two_layer_result(normalized_symbol, result, input_data=stock_context, paths=paths)
    quality_level = _effective_quality_level(result)
    doc_url = _create_doc_for_result(normalized_symbol, str(stock_context.get('company_name') or normalized_symbol), result, paths=paths)
    if quality_level != 'fail':
        company_name = str(stock_context.get('company_name') or normalized_symbol)
        conclusion = getattr(result, 'structured_fields', {}).get('overall_conclusion') or ''
        correlation_id = new_correlation_id()
        payload = build_event_payload(
            event_type='research_completed',
            symbol=normalized_symbol,
            company_name=company_name,
            summary=f'[{normalized_symbol}] {company_name} 研究完成 — {conclusion}',
            correlation_id=correlation_id,
            facts={'quality_level': quality_level, 'overall_conclusion': conclusion, 'doc_url': doc_url},
        )
        create_notification_event(event_type='research_completed', payload=payload, correlation_id=correlation_id, symbol=normalized_symbol, paths=paths)
    print(json.dumps({'symbol': normalized_symbol, 'quality_level': quality_level, 'doc_url': doc_url}, ensure_ascii=False))
    flush_pending_notifications(paths=paths)
    return 0


def cmd_monitor(paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    monitoring = run_daily_monitoring(paths=paths)
    reresearch_done: list[str] = []
    for symbol in list(monitoring.get('reresearch_triggered', [])):
        execute_reresearch(str(symbol), paths=paths)
        reresearch_done.append(str(symbol))

    with sqlite_connection(paths) as connection:
        symbols = [str(row[0]) for row in connection.execute("SELECT symbol FROM position_summary WHERE status = 'open' ORDER BY symbol").fetchall()]
    import os
    from dotenv import load_dotenv
    load_dotenv()
    alert_manager = AlertManager(paths=paths)
    webhook_url = os.getenv('FEISHU_WEBHOOK_URL', '').strip()
    correlation_id = new_correlation_id()
    for symbol in symbols:
        send_alert_notifications_for_symbol(symbol, alert_manager, webhook_url, correlation_id, paths=paths)

    flush_pending_notifications(paths=paths)
    summary = {
        'monitored': int(monitoring.get('monitored', 0)),
        'signals_detected': int(monitoring.get('signals_detected', 0)),
        'reresearch_triggered': reresearch_done,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def cmd_buy(symbol: str, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    normalized_symbol = symbol.strip().upper()
    price = _prompt_float('price')
    quantity = _prompt_int('quantity')
    trade_date = _prompt_text('date', _today_str())
    reason = _prompt_text('reason', '')
    record_buy(normalized_symbol, price, quantity, trade_date, reason or None, paths=paths)
    correlation_id = new_correlation_id()
    payload = build_event_payload(
        event_type='buy_confirmation',
        symbol=normalized_symbol,
        summary=f'[{normalized_symbol}] 买入确认',
        correlation_id=correlation_id,
        facts={'price': price, 'quantity': quantity, 'trade_date': trade_date, 'reason': reason},
    )
    create_notification_event(event_type='buy_confirmation', payload=payload, correlation_id=correlation_id, symbol=normalized_symbol, paths=paths)
    flush_pending_notifications(paths=paths)
    print(f'已买入 {normalized_symbol}: {quantity} @ {price} on {trade_date}')
    return 0


def cmd_sell(symbol: str, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    normalized_symbol = symbol.strip().upper()
    price = _prompt_float('price')
    quantity = _prompt_int('quantity')
    trade_date = _prompt_text('date', _today_str())
    reason = _prompt_text('reason', '')
    before = get_position(normalized_symbol, paths=paths)
    before_realized = 0.0 if before is None else float(before.get('realized_pnl', 0.0))
    record_sell(normalized_symbol, price, quantity, trade_date, reason or None, paths=paths)
    after = get_position(normalized_symbol, paths=paths)
    after_realized = 0.0 if after is None else float(after.get('realized_pnl', 0.0))
    realized_delta = after_realized - before_realized
    print(f'已卖出 {normalized_symbol}: {quantity} @ {price} on {trade_date} | realized_pnl={realized_delta:.2f}')
    return 0


def cmd_ignore(symbol: str, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    normalized_symbol = symbol.strip().upper()
    with sqlite_connection(paths) as connection:
        row = connection.execute('SELECT symbol FROM stock_master WHERE symbol = ?', (normalized_symbol,)).fetchone()
        if row is None:
            print(f'{normalized_symbol} 不在候选池，可先买入或研究')
            return 0
        connection.execute("UPDATE stock_master SET user_status = 'ignored' WHERE symbol = ?", (normalized_symbol,))
    print(f'{normalized_symbol} 已标记为 ignored')
    return 0


def cmd_unignore(symbol: str, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    normalized_symbol = symbol.strip().upper()
    with sqlite_connection(paths) as connection:
        connection.execute("UPDATE stock_master SET user_status = 'watching' WHERE symbol = ?", (normalized_symbol,))
    print(f'{normalized_symbol} 已恢复为 watching')
    return 0


def _latest_snapshot_for_symbol(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any] | None:
    paths = paths or ProjectPaths()
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT price, unrealized_pnl, unrealized_pnl_pct, snapshot_date
            FROM daily_position_snapshot
            WHERE symbol = ?
            ORDER BY snapshot_date DESC, id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    return {'price': row[0], 'unrealized_pnl': row[1], 'unrealized_pnl_pct': row[2], 'snapshot_date': row[3]}


def _active_alert_summary(symbol: str, paths: ProjectPaths | None = None) -> dict[str, str]:
    paths = paths or ProjectPaths()
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT signal_level, action
            FROM alert_event
            WHERE symbol = ? AND status NOT IN ('resolved', 'expired', 'historical_reached', 'upgraded')
            ORDER BY CASE signal_level WHEN 'action' THEN 0 ELSE 1 END, id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    if row is None:
        return {'bucket': '正常', 'action': ''}
    level = str(row[0] or '')
    action = str(row[1] or '')
    if level == 'action':
        return {'bucket': '需操作', 'action': action}
    return {'bucket': '需关注', 'action': action}


def cmd_status(paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        rows = connection.execute(
            """
            SELECT symbol, total_shares, avg_cost, first_buy_date, total_invested, realized_pnl
            FROM position_summary
            WHERE status = 'open'
            ORDER BY symbol
            """
        ).fetchall()
    total_invested = 0.0
    total_unrealized = 0.0
    rendered: dict[str, list[str]] = {'需操作': [], '需关注': [], '正常': []}
    today = date.today()
    for row in rows:
        symbol = str(row[0])
        shares = int(row[1])
        avg_cost = float(row[2])
        first_buy_date = str(row[3])
        invested = float(row[4])
        snapshot = _latest_snapshot_for_symbol(symbol, paths=paths)
        price = float(snapshot['price']) if snapshot and snapshot.get('price') is not None else avg_cost
        unrealized_pnl = float(snapshot['unrealized_pnl']) if snapshot and snapshot.get('unrealized_pnl') is not None else (price - avg_cost) * shares
        unrealized_pct = float(snapshot['unrealized_pnl_pct']) if snapshot and snapshot.get('unrealized_pnl_pct') is not None else ((price - avg_cost) / avg_cost * 100 if avg_cost else 0.0)
        total_invested += invested
        total_unrealized += unrealized_pnl
        try:
            hold_days = (today - date.fromisoformat(first_buy_date[:10])).days
        except ValueError:
            hold_days = 0
        alert = _active_alert_summary(symbol, paths=paths)
        action_text = f"  {alert['action']}" if alert['action'] else ''
        line = f"  {symbol}  ${price:.0f} ({unrealized_pct:+.1f}%)  持有 {hold_days} 天{action_text}"
        rendered[alert['bucket']].append(line)

    total_pct = (total_unrealized / total_invested * 100) if total_invested else 0.0
    print('===== 持仓概况 =====')
    print(f"总持仓：{len(rows)} 只 | 总投入：${total_invested:,.0f} | 未实现盈亏：{total_unrealized:+,.0f} ({total_pct:+.1f}%)")
    for bucket in ('需操作', '需关注', '正常'):
        print(f'{bucket}：')
        for line in rendered[bucket]:
            print(line)
    print('====================')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='us_stock_research', description='美股选股体系 CLI')
    subparsers = parser.add_subparsers(dest='command')

    run_parser = subparsers.add_parser('run', help='全流程：筛选→去重→研究→飞书文档→通知（成功才发汇总）')
    run_parser.add_argument('--strategy', default=DEFAULT_STRATEGY_NAME)
    run_parser.add_argument('--limit', type=int, default=None)
    run_parser.add_argument('--top-n', type=int, default=10)

    run_notify_parser = subparsers.add_parser('run-and-notify', help='全流程并始终发送通知')
    run_notify_parser.add_argument('--strategy', default=DEFAULT_STRATEGY_NAME)
    run_notify_parser.add_argument('--limit', type=int, default=None)
    run_notify_parser.add_argument('--top-n', type=int, default=10)

    screen_parser = subparsers.add_parser('screen', help='仅筛选，不研究不通知')
    screen_parser.add_argument('--strategy', default=DEFAULT_STRATEGY_NAME)
    screen_parser.add_argument('--limit', type=int, default=None)
    screen_parser.add_argument('--top-n', type=int, default=10)

    research_parser = subparsers.add_parser('research', help='指定单只股票立即研究')
    research_parser.add_argument('--symbol', dest='symbol', default=None)
    research_parser.add_argument('--provider', default='auto', choices=['auto', 'perplexity', 'derived'])
    research_parser.add_argument('--persist', action='store_true')
    research_parser.add_argument('--show-prompt', action='store_true')
    research_parser.add_argument('--show-input', action='store_true')

    monitor_parser = subparsers.add_parser('monitor', help='所有持仓的日常监控')

    buy_parser = subparsers.add_parser('buy', help='录入买入')
    buy_parser.add_argument('symbol')

    sell_parser = subparsers.add_parser('sell', help='录入卖出')
    sell_parser.add_argument('symbol')

    ignore_parser = subparsers.add_parser('ignore', help='将股票标记为已忽略')
    ignore_parser.add_argument('symbol')

    unignore_parser = subparsers.add_parser('unignore', help='取消忽略，恢复关注中')
    unignore_parser.add_argument('symbol')

    subparsers.add_parser('status', help='打印持仓概况')
    subparsers.add_parser('research-diagnostics', help='Show research freshness and trigger guidance')
    subparsers.add_parser('list-strategies', help='List available strategy files')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == 'list-strategies':
        strategies = list_strategy_names(ProjectPaths())
        if not strategies:
            print('No strategies found.')
            return 1
        for strategy in strategies:
            print(strategy)
        return 0
    if args.command == 'run':
        return cmd_run(notify=False, strategy_name=args.strategy, limit_override=args.limit, top_n=args.top_n)
    if args.command == 'run-and-notify':
        return cmd_run(notify=True, strategy_name=args.strategy, limit_override=args.limit, top_n=args.top_n)
    if args.command == 'screen':
        result = run_screening(args.strategy, limit_override=args.limit, top_n=args.top_n, paths=ProjectPaths())
        print(json.dumps({'stockCount': result.get('stockCount', 0), 'strategyName': result.get('strategyName')}, ensure_ascii=False))
        flush_pending_notifications()
        return 0
    if args.command == 'research':
        symbol = args.symbol
        if not symbol:
            parser.error('research requires SYMBOL or --symbol')
        return cmd_research(symbol)
    if args.command == 'monitor':
        return cmd_monitor()
    if args.command == 'buy':
        return cmd_buy(args.symbol)
    if args.command == 'sell':
        return cmd_sell(args.symbol)
    if args.command == 'ignore':
        return cmd_ignore(args.symbol)
    if args.command == 'unignore':
        return cmd_unignore(args.symbol)
    if args.command == 'status':
        return cmd_status()
    if args.command == 'research-diagnostics':
        print(json.dumps({'status': 'not_implemented_in_task10'}, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0
