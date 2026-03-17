from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from typing import Any

from .alert_manager import ACTION_PRIORITY, AlertManager
from .config import DEFAULT_STRATEGY_NAME, ProjectPaths
from .config_store import load_app_config_data, load_strategy_config_data
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .project_status import get_project_master_board
from .results_repo import load_latest_result

VALID_USER_STATUSES = ("watching", "ignored", "held", "closed")
ACTIVE_ALERT_STATUSES = ("triggered", "notified", "acknowledged")
TERMINAL_ALERT_STATUSES = ("resolved", "expired", "historical_reached", "upgraded")

RESEARCH_STATUS_LABELS = {
    "pending": "待研究",
    "running": "待研究",
    "completed": "已研究",
    "reused": "复用",
    "failed": "研究失败",
}


def format_timestamp(value: str | None) -> str:
    if not value:
        return '暂无'
    try:
        return datetime.fromisoformat(value).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return value


def build_stock_rows(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, stock in enumerate(stocks, start=1):
        detail = dict(stock.get('scoreDetail', {}))
        metrics = dict(detail.get('metrics', {}))
        rows.append(
            {
                'Rank': index,
                'Ticker': stock.get('symbol', ''),
                'Company': stock.get('companyName', ''),
                'Price': _round_number(stock.get('price')),
                'PE': _round_number(metrics.get('pe')),
                'PB': _round_number(metrics.get('pb')),
                'ROE %': _round_number(metrics.get('roe'), 100),
                'Score': _round_number(stock.get('score')),
                'Tier': dict(detail.get('tier', {})).get('label', '待研究'),
            }
        )
    return rows


def latest_run_summary(run_data: dict[str, Any] | None) -> dict[str, Any]:
    outputs = dict(run_data.get('outputs', {})) if run_data else {}
    return {
        'generated_at': format_timestamp(str(run_data.get('generatedAt', '')) if run_data else ''),
        'strategy_name': str(run_data.get('strategyName', DEFAULT_STRATEGY_NAME)) if run_data else DEFAULT_STRATEGY_NAME,
        'stock_count': int(run_data.get('stockCount', 0)) if run_data else 0,
        'report_path': str(outputs.get('report', '')),
        'json_path': str(outputs.get('json', '')),
        'watchlist_path': str(outputs.get('watchlist', '')),
    }


def load_lifecycle_summary(paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    with sqlite_connection(paths) as connection:
        state_rows = connection.execute(
            'SELECT lifecycle_state, COUNT(*) FROM stock_master GROUP BY lifecycle_state ORDER BY lifecycle_state'
        ).fetchall()
        queue_rows = connection.execute(
            'SELECT symbol, trigger_priority, status, research_date FROM research_snapshot ORDER BY research_date DESC LIMIT 20'
        ).fetchall()
        notification_rows = connection.execute(
            'SELECT event_type, symbol, send_status, created_at FROM notification_event ORDER BY id DESC LIMIT 20'
        ).fetchall()
        research_rows = connection.execute(
            """
            SELECT
                rs.symbol,
                rs.status,
                rs.prompt_version,
                rs.prompt_template_id,
                rs.research_date,
                ra.confidence_score,
                ra.overall_recommendation,
                rs.trigger_type,
                substr(rs.raw_response, 1, 120),
                ra.next_review_date
            FROM research_snapshot rs
            LEFT JOIN research_analysis ra ON ra.research_snapshot_id = rs.id
            ORDER BY rs.research_date DESC, rs.id DESC
            LIMIT 20
            """
        ).fetchall()
        review_rows = connection.execute(
            'SELECT id, symbol, status, proposed_at FROM suggested_change ORDER BY id DESC LIMIT 20'
        ).fetchall()
        active_rows = connection.execute(
            """
            SELECT symbol, lifecycle_state, latest_score, latest_signal, trade_gate_blocked, current_price, updated_at
            FROM stock_master
            WHERE lifecycle_state IN ('waiting_for_setup', 'buy_ready', 'holding', 'exit_watch')
            ORDER BY updated_at DESC
            LIMIT 50
            """
        ).fetchall()

    state_count_rows = [{'State': str(row[0]), 'Count': int(row[1])} for row in state_rows]
    research_queue_rows = [
        {
            'Symbol': str(row[0]),
            'Priority': str(row[1]),
            'Status': str(row[2]),
            'Research At': format_timestamp(str(row[3] or '')),
        }
        for row in queue_rows
    ]
    active_stock_rows = [
        {
            'Symbol': str(row[0]),
            'State': str(row[1]),
            'Score': _round_number(row[2]),
            'Signal': str(row[3] or ''),
            'Gate': 'Blocked' if int(row[4] or 0) else 'Open',
            'Price': _round_number(row[5]),
            'Updated At': format_timestamp(str(row[6] or '')),
        }
        for row in active_rows
    ]
    notification_event_rows = [
        {
            'Event': str(row[0]),
            'Symbol': str(row[1] or ''),
            'Status': str(row[2]),
            'Created At': format_timestamp(str(row[3] or '')),
        }
        for row in notification_rows
    ]
    review_queue_rows = [
        {
            'ID': int(row[0]),
            'Symbol': str(row[1]),
            'Status': str(row[2]),
            'Proposed At': format_timestamp(str(row[3] or '')),
        }
        for row in review_rows
    ]
    research_result_rows = [
        {
            'Symbol': str(row[0]),
            'Status': str(row[1]),
            'Prompt Version': str(row[2] or ''),
            'Prompt Template': str(row[3] or ''),
            'Research At': format_timestamp(str(row[4] or '')),
            'Confidence': _round_number(row[5]),
            'Recommendation': str(row[6] or ''),
            'Trigger': str(row[7] or ''),
            'Raw Preview': str(row[8] or ''),
            'Next Review': str(row[9] or ''),
        }
        for row in research_rows
    ]

    totals = {
        'state_count': sum(item['Count'] for item in state_count_rows),
        'research_queue_count': len(research_queue_rows),
        'review_queue_count': len(review_queue_rows),
        'notification_count': len(notification_event_rows),
        'active_count': len(active_stock_rows),
        'research_result_count': len(research_result_rows),
    }
    return {
        'state_counts': state_count_rows,
        'research_queue': research_queue_rows,
        'active_rows': active_stock_rows,
        'notifications': notification_event_rows,
        'review_queue': review_queue_rows,
        'research_results': research_result_rows,
        'totals': totals,
    }


def load_dashboard_bundle(
    strategy_name: str = DEFAULT_STRATEGY_NAME,
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    latest = load_latest_result(paths, strategy_name_hint=strategy_name)
    strategy = load_strategy_config_data(strategy_name, paths)
    app_config = load_app_config_data(paths)
    lifecycle = load_lifecycle_summary(paths)
    return {
        'latest': latest,
        'summary': latest_run_summary(latest),
        'rows': build_stock_rows(list(latest.get('stocks', [])) if latest else []),
        'strategy': strategy,
        'app_config': app_config,
        'lifecycle': lifecycle,
    }


def strategy_form_defaults(strategy: dict[str, Any]) -> dict[str, Any]:
    screen = dict(strategy.get('screen', {}))
    ranking = dict(strategy.get('ranking', {}))
    gates = dict(ranking.get('gates', {}))
    return {
        'screen_limit': int(screen.get('limit', 50)),
        'market_cap_min': int(screen.get('market_cap_min', 500_000_000)),
        'market_cap_max': int(screen.get('market_cap_max', 100_000_000_000)),
        'volume_min': int(screen.get('volume_min', 1_000_000)),
        'sector': str(screen.get('sector', 'Technology')),
        'exchange': str(screen.get('exchange', 'NASDAQ')),
        'top_n': int(ranking.get('top_n', 10)),
        'max_pe': float(gates.get('max_pe', 30)),
        'max_pb': float(gates.get('max_pb', 5)),
        'min_valuation_score': float(gates.get('min_valuation_score', 2)),
        'min_roe_for_quality': float(gates.get('min_roe_for_quality', 0.1)),
    }


def apply_strategy_form_values(strategy: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(strategy)
    updated.setdefault('screen', {})
    updated.setdefault('ranking', {})
    updated['ranking'].setdefault('gates', {})

    updated['screen']['limit'] = int(values['screen_limit'])
    updated['screen']['market_cap_min'] = int(values['market_cap_min'])
    updated['screen']['market_cap_max'] = int(values['market_cap_max'])
    updated['screen']['volume_min'] = int(values['volume_min'])
    updated['screen']['sector'] = str(values['sector']).strip()
    updated['screen']['exchange'] = str(values['exchange']).strip()

    updated['ranking']['top_n'] = int(values['top_n'])
    updated['ranking']['gates']['max_pe'] = float(values['max_pe'])
    updated['ranking']['gates']['max_pb'] = float(values['max_pb'])
    updated['ranking']['gates']['min_valuation_score'] = float(values['min_valuation_score'])
    updated['ranking']['gates']['min_roe_for_quality'] = float(values['min_roe_for_quality'])
    return updated


def app_config_form_defaults(app_config: dict[str, Any]) -> dict[str, Any]:
    notifications = dict(app_config.get('notifications', {}))
    feishu = dict(notifications.get('feishu', {}))
    schedule = dict(app_config.get('schedule', {}))
    research = dict(app_config.get('research', {}))
    perplexity = dict(research.get('perplexity', {}))
    return {
        'feishu_enabled': bool(feishu.get('enabled', False)),
        'feishu_webhook_url': str(feishu.get('webhook_url', '')),
        'digest_mode': str(feishu.get('digest_mode', 'top3_only')),
        'schedule_enabled': bool(schedule.get('enabled', False)),
        'schedule_cron': str(schedule.get('cron', '0 9 * * 0')),
        'schedule_timezone': str(schedule.get('timezone', 'Asia/Shanghai')),
        'schedule_strategy': str(schedule.get('run_strategy', DEFAULT_STRATEGY_NAME)),
        'schedule_top_n': int(schedule.get('top_n', 10)),
        'perplexity_enabled': bool(perplexity.get('enabled', False)),
        'perplexity_prompt_template_id': str(perplexity.get('prompt_template_id', 'baseline_perplexity_template')),
        'perplexity_prompt_version': str(perplexity.get('prompt_version', 'v1.0')),
        'perplexity_fallback_to_derived': bool(perplexity.get('fallback_to_derived', True)),
    }


def apply_app_config_form_values(app_config: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(app_config)
    updated.setdefault('notifications', {})
    updated['notifications'].setdefault('feishu', {})
    updated.setdefault('schedule', {})
    updated.setdefault('research', {})
    updated['research'].setdefault('perplexity', {})

    updated['notifications']['feishu']['enabled'] = bool(values['feishu_enabled'])
    updated['notifications']['feishu']['webhook_url'] = str(values['feishu_webhook_url']).strip()
    updated['notifications']['feishu']['digest_mode'] = str(values['digest_mode'])

    updated['schedule']['enabled'] = bool(values['schedule_enabled'])
    updated['schedule']['cron'] = str(values['schedule_cron']).strip()
    updated['schedule']['timezone'] = str(values['schedule_timezone']).strip()
    updated['schedule']['run_strategy'] = str(values['schedule_strategy']).strip()
    updated['schedule']['top_n'] = int(values['schedule_top_n'])

    updated['research']['perplexity']['enabled'] = bool(values['perplexity_enabled'])
    updated['research']['perplexity']['prompt_template_id'] = str(values['perplexity_prompt_template_id']).strip()
    updated['research']['perplexity']['prompt_version'] = str(values['perplexity_prompt_version']).strip()
    updated['research']['perplexity']['fallback_to_derived'] = bool(values['perplexity_fallback_to_derived'])
    return updated


def _round_number(value: Any, multiplier: float = 1.0) -> float | None:
    if value is None or value == '':
        return None
    try:
        return round(float(value) * multiplier, 2)
    except (TypeError, ValueError):
        return None


def load_research_diagnostics(paths: ProjectPaths | None = None) -> dict[str, Any]:
    from .research_engine import build_research_trigger_guidance
    paths = paths or ProjectPaths()
    with sqlite_connection(paths) as connection:
        latest_rows = connection.execute(
            """
            SELECT rs.symbol, rs.research_date, rs.trigger_type, rs.status, ra.next_review_date, ra.overall_recommendation, ra.confidence_score
            FROM research_snapshot rs
            LEFT JOIN research_analysis ra ON ra.research_snapshot_id = rs.id
            WHERE rs.id IN (SELECT MAX(id) FROM research_snapshot GROUP BY symbol)
            ORDER BY rs.research_date DESC
            LIMIT 50
            """
        ).fetchall()
    rows = []
    for row in latest_rows:
        guidance = build_research_trigger_guidance(
            latest_research_at=str(row[1] or ''),
            latest_trigger_type=str(row[2] or ''),
            latest_status=str(row[3] or ''),
            next_review_date=str(row[4] or ''),
        )
        rows.append({
            'Symbol': str(row[0]),
            'Research At': format_timestamp(str(row[1] or '')),
            'Trigger': str(row[2] or ''),
            'Status': str(row[3] or ''),
            'Next Review': str(row[4] or ''),
            'Recommendation': str(row[5] or ''),
            'Confidence': _round_number(row[6]),
            'Freshness': str(guidance.get('freshness', '')),
            'Should Trigger': 'Yes' if guidance.get('should_trigger') else 'No',
            'Reason': str(guidance.get('reason', '')),
        })
    return {
        'rows': rows,
        'needs_trigger_count': sum(1 for item in rows if item['Should Trigger'] == 'Yes'),
        'tracked_symbol_count': len(rows),
    }


def load_project_master_board() -> dict[str, Any]:
    return get_project_master_board()


def get_candidate_pool(
    filters: dict | None = None,
    paths: ProjectPaths | None = None,
) -> list[dict[str, Any]]:
    ensure_schema(paths)
    filters = filters or {}
    params: list[Any] = []
    clauses: list[str] = []

    strategy = filters.get('strategy')
    user_status = filters.get('user_status')
    research_status = filters.get('research_status')

    if strategy:
        clauses.append(
            "EXISTS (SELECT 1 FROM strategy_hit sh2 WHERE sh2.symbol = sm.symbol AND sh2.strategy_name = ?)"
        )
        params.append(strategy)
    if user_status:
        clauses.append("sm.user_status = ?")
        params.append(user_status)

    query = f"""
        WITH hit_summary AS (
            SELECT symbol,
                   MIN(hit_date) AS first_hit_date,
                   MAX(hit_date) AS last_hit_date,
                   COUNT(DISTINCT hit_at) AS computed_hit_count
            FROM strategy_hit
            GROUP BY symbol
        ),
        latest_hit AS (
            SELECT sh.symbol,
                   sh.strategy_name AS latest_hit_strategy,
                   sh.hit_date AS latest_hit_date,
                   sh.screen_payload_json
            FROM strategy_hit sh
            WHERE sh.id = (
                SELECT sh2.id
                FROM strategy_hit sh2
                WHERE sh2.symbol = sh.symbol
                ORDER BY sh2.hit_date DESC, sh2.hit_at DESC, sh2.id DESC
                LIMIT 1
            )
        ),
        latest_research AS (
            SELECT rs.symbol,
                   rs.research_date,
                   rs.status,
                   ra.overall_conclusion,
                   ra.feishu_doc_url,
                   ra.three_sentence_summary,
                   ra.target_price_base,
                   ra.target_price_conservative,
                   ra.target_price_optimistic,
                   ra.stop_loss_condition,
                   ra.reduce_position_condition,
                   ra.invalidation_conditions_json,
                   ra.id AS research_analysis_id,
                   rs.id AS research_snapshot_id
            FROM research_snapshot rs
            LEFT JOIN research_analysis ra ON ra.research_snapshot_id = rs.id
            WHERE rs.id IN (
                SELECT MAX(id)
                FROM research_snapshot
                GROUP BY symbol
            )
        ),
        latest_score AS (
            SELECT sb.symbol, sb.strategy_name, sb.notes_json, sb.detail_json
            FROM scoring_breakdown sb
            WHERE sb.id IN (
                SELECT MAX(id)
                FROM scoring_breakdown
                GROUP BY symbol
            )
        )
        SELECT
            sm.symbol,
            sm.company_name,
            NULLIF(sm.sector, '') AS sector,
            NULLIF(sm.market_cap, 0) AS market_cap_raw,
            hs.first_hit_date,
            hs.last_hit_date,
            COALESCE(sm.hit_count, hs.computed_hit_count) AS hit_count,
            sm.user_status,
            sm.current_price,
            sm.latest_price,
            sm.latest_market_cap,
            sm.price_updated_at,
            ts.price,
            ts.snapshot_date,
            ts.high_52w,
            lh.latest_hit_strategy,
            lh.latest_hit_date,
            lh.screen_payload_json,
            lr.research_date,
            lr.status,
            lr.overall_conclusion,
            lr.feishu_doc_url,
            lr.three_sentence_summary,
            ls.strategy_name,
            ls.notes_json,
            ls.detail_json
        FROM stock_master sm
        JOIN hit_summary hs ON hs.symbol = sm.symbol
        LEFT JOIN latest_hit lh ON lh.symbol = sm.symbol
        LEFT JOIN technical_snapshot ts ON ts.id = (
            SELECT id FROM technical_snapshot t2
            WHERE t2.symbol = sm.symbol
            ORDER BY t2.snapshot_date DESC, t2.id DESC
            LIMIT 1
        )
        LEFT JOIN latest_research lr ON lr.symbol = sm.symbol
        LEFT JOIN latest_score ls ON ls.symbol = sm.symbol
        WHERE 1 = 1
        {'AND ' + ' AND '.join(clauses) if clauses else ''}
        ORDER BY hs.last_hit_date DESC, sm.symbol ASC
    """
    with sqlite_connection(paths) as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    today = date.today().isoformat()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = _build_candidate_item(dict(row), today)
        if research_status and item['research_status'] != research_status:
            continue
        items.append(item)
    return items


def get_portfolio_view(paths: ProjectPaths | None = None) -> dict[str, Any]:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        rows = connection.execute(
            """
            SELECT
                ps.symbol,
                ps.status,
                ps.total_shares,
                ps.avg_cost,
                ps.first_buy_date,
                ps.total_invested,
                sm.company_name,
                sm.current_price,
                ts.price AS snapshot_price,
                ts.snapshot_date,
                ra.overall_conclusion,
                ra.feishu_doc_url
            FROM position_summary ps
            LEFT JOIN stock_master sm ON sm.symbol = ps.symbol
            LEFT JOIN technical_snapshot ts ON ts.id = (
                SELECT id FROM technical_snapshot t2
                WHERE t2.symbol = ps.symbol
                ORDER BY t2.snapshot_date DESC, t2.id DESC
                LIMIT 1
            )
            LEFT JOIN research_snapshot rs ON rs.id = (
                SELECT MAX(id) FROM research_snapshot rs2 WHERE rs2.symbol = ps.symbol
            )
            LEFT JOIN research_analysis ra ON ra.research_snapshot_id = rs.id
            WHERE ps.status = 'open'
            ORDER BY ps.first_buy_date ASC, ps.symbol ASC
            """
        ).fetchall()
        daily_changes = {
            str(row['symbol']): _fetch_daily_change_pct(connection, str(row['symbol']))
            for row in rows
        }
        alerts_by_symbol = _fetch_active_alerts_by_symbol(connection, [str(row['symbol']) for row in rows])

    sections = {"需操作": [], "需关注": [], "正常": []}
    summary = {
        'total_positions': 0,
        'need_action_count': 0,
        'need_attention_count': 0,
        'normal_count': 0,
        'total_invested': 0.0,
        'total_unrealized_pnl': 0.0,
        'total_unrealized_pnl_pct': 0.0,
    }

    for row in rows:
        symbol = str(row['symbol'])
        price = _coalesce_price(row['snapshot_price'], row['current_price'])
        avg_cost = float(row['avg_cost'])
        total_shares = float(row['total_shares'])
        unrealized_pnl = (price - avg_cost) * total_shares if price is not None else None
        unrealized_pnl_pct = ((price - avg_cost) / avg_cost) * 100 if price is not None and avg_cost > 0 else None
        alerts = alerts_by_symbol.get(symbol, [])
        top_action = _top_action(alerts)
        holding_days = _days_since(str(row['first_buy_date']))
        item = {
            'symbol': symbol,
            'company_name': str(row['company_name'] or symbol),
            'avg_cost': avg_cost,
            'total_shares': int(total_shares),
            'first_buy_date': str(row['first_buy_date']),
            'price': price,
            'daily_change_pct': daily_changes.get(symbol),
            'unrealized_pnl': _round_number(unrealized_pnl),
            'unrealized_pnl_pct': _round_number(unrealized_pnl_pct),
            'holding_days': holding_days,
            'active_alerts': alerts,
            'top_action': top_action,
            'latest_conclusion': row['overall_conclusion'],
            'feishu_doc_url': row['feishu_doc_url'],
        }
        if any(alert['signal_level'] == 'action' for alert in alerts):
            section = '需操作'
            summary['need_action_count'] += 1
        elif any(alert['signal_level'] == 'warning' for alert in alerts):
            section = '需关注'
            summary['need_attention_count'] += 1
        else:
            section = '正常'
            summary['normal_count'] += 1
        sections[section].append(item)
        summary['total_positions'] += 1
        summary['total_invested'] += float(row['total_invested'] or 0)
        if unrealized_pnl is not None:
            summary['total_unrealized_pnl'] += unrealized_pnl

    total_invested = summary['total_invested']
    summary['total_invested'] = _round_number(total_invested) or 0.0
    summary['total_unrealized_pnl'] = _round_number(summary['total_unrealized_pnl']) or 0.0
    summary['total_unrealized_pnl_pct'] = _round_number((summary['total_unrealized_pnl'] / total_invested) * 100) if total_invested else 0.0

    return {
        'summary': summary,
        'sections': [
            {'label': '需操作', 'items': sections['需操作']},
            {'label': '需关注', 'items': sections['需关注']},
            {'label': '正常', 'items': sections['正常']},
        ],
    }


def get_historical_trades(paths: ProjectPaths | None = None) -> list[dict[str, Any]]:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        symbols = [
            str(row[0])
            for row in connection.execute(
                "SELECT symbol FROM position_summary WHERE status = 'closed' ORDER BY updated_at DESC, symbol ASC"
            ).fetchall()
        ]
        items = [_build_historical_trade(connection, symbol) for symbol in symbols]
    return [item for item in items if item is not None]


def get_stock_detail(
    symbol: str,
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        basic_row = connection.execute(
            """
            SELECT sm.symbol, sm.company_name, NULLIF(sm.sector, ''), NULLIF(sm.market_cap, 0),
                   COALESCE(ts.price, sm.current_price), sm.exchange, sm.avg_volume, sm.user_status, sm.notes
            FROM stock_master sm
            LEFT JOIN technical_snapshot ts ON ts.id = (
                SELECT id FROM technical_snapshot t2 WHERE t2.symbol = sm.symbol ORDER BY t2.snapshot_date DESC, t2.id DESC LIMIT 1
            )
            WHERE sm.symbol = ?
            """,
            (symbol,),
        ).fetchone()
        hit_rows = connection.execute(
            """
            SELECT hit_date, strategy_name, result, correlation_id
            FROM strategy_hit
            WHERE symbol = ?
            ORDER BY hit_date DESC, id DESC
            """,
            (symbol,),
        ).fetchall()
        latest_research_row = connection.execute(
            """
            SELECT rs.research_date, ra.overall_conclusion, ra.feishu_doc_url, rs.status, rs.raw_response
            FROM research_snapshot rs
            LEFT JOIN research_analysis ra ON ra.research_snapshot_id = rs.id
            WHERE rs.symbol = ?
            ORDER BY rs.research_date DESC, rs.id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        research_rows = connection.execute(
            """
            SELECT rs.research_date, ra.overall_conclusion, ra.feishu_doc_url, rs.status, rs.raw_response
            FROM research_snapshot rs
            LEFT JOIN research_analysis ra ON ra.research_snapshot_id = rs.id
            WHERE rs.symbol = ?
            ORDER BY rs.research_date DESC, rs.id DESC
            """,
            (symbol,),
        ).fetchall()
        alert_rows = connection.execute(
            """
            SELECT id, signal_type, action, status, detail, triggered_at, resolved_at
            FROM alert_event
            WHERE symbol = ?
            ORDER BY triggered_at DESC, id DESC
            """,
            (symbol,),
        ).fetchall()
        trade_rows = connection.execute(
            """
            SELECT trade_type, trade_date, price, quantity, reason
            FROM trade_log
            WHERE symbol = ?
            ORDER BY trade_date DESC, id DESC
            """,
            (symbol,),
        ).fetchall()
        position_row = connection.execute(
            """
            SELECT ps.avg_cost, ps.total_shares, ps.first_buy_date, COALESCE(ts.price, sm.current_price)
            FROM position_summary ps
            LEFT JOIN stock_master sm ON sm.symbol = ps.symbol
            LEFT JOIN technical_snapshot ts ON ts.id = (
                SELECT id FROM technical_snapshot t2 WHERE t2.symbol = ps.symbol ORDER BY t2.snapshot_date DESC, t2.id DESC LIMIT 1
            )
            WHERE ps.symbol = ? AND ps.status = 'open'
            """,
            (symbol,),
        ).fetchone()

    basic = {
        'symbol': symbol,
        'company_name': symbol,
        'sector': None,
        'market_cap': None,
        'price': None,
        'exchange': None,
        'avg_volume': None,
        'user_status': None,
        'notes': None,
    }
    if basic_row is not None:
        basic.update({
            'symbol': str(basic_row[0]),
            'company_name': str(basic_row[1] or symbol),
            'sector': basic_row[2],
            'market_cap': _round_number(basic_row[3]),
            'price': _round_number(basic_row[4]),
            'exchange': basic_row[5],
            'avg_volume': int(basic_row[6]) if basic_row[6] is not None else None,
            'user_status': basic_row[7],
            'notes': basic_row[8],
        })

    latest_research = None
    if latest_research_row is not None:
        latest_research = {
            'conclusion': latest_research_row[1],
            'feishu_doc_url': latest_research_row[2],
            'research_date': latest_research_row[0],
            'quality_level': _map_research_status_to_quality_level(str(latest_research_row[3] or ''), latest_research_row[4]),
        }

    position = None
    if position_row is not None:
        current_price = _round_number(position_row[3])
        avg_cost = float(position_row[0])
        total_shares = int(position_row[1])
        unrealized_pnl = (current_price - avg_cost) * total_shares if current_price is not None else None
        unrealized_pnl_pct = ((current_price - avg_cost) / avg_cost) * 100 if current_price is not None and avg_cost > 0 else None
        position = {
            'avg_cost': avg_cost,
            'total_shares': total_shares,
            'first_buy_date': str(position_row[2]),
            'unrealized_pnl': _round_number(unrealized_pnl),
            'unrealized_pnl_pct': _round_number(unrealized_pnl_pct),
            'holding_days': _days_since(str(position_row[2])),
        }

    return {
        'basic': basic,
        'hit_history': [
            {
                'hit_date': str(row[0]),
                'strategy_name': str(row[1]),
                'conclusion': str(row[2] or ''),
                'hit_count': index + 1,
            }
            for index, row in enumerate(hit_rows)
        ],
        'latest_research': latest_research,
        'research_history': [
            {
                'research_date': str(row[0]),
                'conclusion': row[1],
                'feishu_doc_url': row[2],
                'quality_level': _map_research_status_to_quality_level(str(row[3] or ''), row[4]),
                'fallback_used': _map_research_status_to_quality_level(str(row[3] or ''), row[4]) == 'fallback',
            }
            for row in research_rows
        ],
        'alerts': [
            {
                'id': int(row[0]),
                'signal_type': str(row[1]),
                'action': str(row[2]),
                'status': str(row[3]),
                'detail': row[4],
                'triggered_at': row[5],
                'resolved_at': row[6],
            }
            for row in alert_rows
        ],
        'trades': [
            {
                'trade_type': str(row[0]),
                'trade_date': str(row[1]),
                'price': float(row[2]),
                'quantity': int(row[3]),
                'reason': row[4],
            }
            for row in trade_rows
        ],
        'position': position,
    }


def mark_user_status(
    symbol: str,
    new_status: str,
    paths: ProjectPaths | None = None,
) -> None:
    if new_status not in VALID_USER_STATUSES:
        raise ValueError(f'invalid user_status: {new_status}')
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        connection.execute(
            'UPDATE stock_master SET user_status = ?, updated_at = CURRENT_TIMESTAMP WHERE symbol = ?',
            (new_status, symbol),
        )


def acknowledge_alert(
    alert_id: int,
    paths: ProjectPaths | None = None,
) -> None:
    AlertManager(paths=paths).acknowledge(alert_id)


def resolve_alert(
    alert_id: int,
    paths: ProjectPaths | None = None,
) -> None:
    AlertManager(paths=paths).resolve(alert_id)


def get_stock_notes(
    symbol: str,
    paths: ProjectPaths | None = None,
) -> str | None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute('SELECT notes FROM stock_master WHERE symbol = ?', (symbol,)).fetchone()
    if row is None:
        return None
    return row[0]


def set_stock_notes(
    symbol: str,
    notes: str,
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    normalized_notes = str(notes).strip() or None
    with sqlite_connection(paths) as connection:
        existing = connection.execute('SELECT symbol FROM stock_master WHERE symbol = ?', (symbol,)).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status, notes)
                VALUES (?, ?, 'manual_entry', 0, 'watching', ?)
                """,
                (symbol, symbol, normalized_notes),
            )
        else:
            connection.execute(
                'UPDATE stock_master SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE symbol = ?',
                (normalized_notes, symbol),
            )


def _build_candidate_item(row: dict[str, Any], today: str) -> dict[str, Any]:
    screen_payload = _load_json(row.get('screen_payload_json'), {})
    latest_price = _coalesce_price(row.get('price'), row.get('current_price'), row.get('latest_price'))
    previous_price = _extract_previous_price(screen_payload)
    daily_change_pct = _compute_change_pct(latest_price, previous_price)
    hit_reasons = _extract_hit_reasons(row.get('notes_json'), row.get('detail_json'), screen_payload)
    strategy_name = row.get('strategy_name') or row.get('latest_hit_strategy')
    research_status = _resolve_research_status(str(row.get('status') or ''), row.get('overall_conclusion'), row.get('three_sentence_summary'))
    return {
        'symbol': str(row['symbol']),
        'company_name': str(row['company_name'] or row['symbol']),
        'sector': row.get('sector'),
        'market_cap': _round_number(row.get('latest_market_cap') or row.get('market_cap_raw')),
        'first_hit_date': str(row['first_hit_date']),
        'last_hit_date': str(row['last_hit_date']),
        'hit_count': int(row['hit_count'] or 0),
        'user_status': str(row['user_status'] or 'watching'),
        'price': _round_number(latest_price),
        'daily_change_pct': _round_number(daily_change_pct),
        'pe': _extract_metric(screen_payload, 'pe'),
        'pb': _extract_metric(screen_payload, 'pb'),
        'roe': _extract_metric(screen_payload, 'roe', multiplier=100),
        'strategy_name': strategy_name,
        'hit_reasons': hit_reasons,
        'research_status': research_status,
        'research_date': row.get('research_date'),
        'research_conclusion': row.get('three_sentence_summary') or row.get('overall_conclusion'),
        'feishu_doc_url': row.get('feishu_doc_url'),
        'is_today_hit': str(row['last_hit_date']) == today,
    }


def _fetch_daily_change_pct(connection: Any, symbol: str) -> float | None:
    rows = connection.execute(
        """
        SELECT price
        FROM technical_snapshot
        WHERE symbol = ?
        ORDER BY snapshot_date DESC, id DESC
        LIMIT 2
        """,
        (symbol,),
    ).fetchall()
    if len(rows) < 2:
        return None
    latest = float(rows[0][0])
    previous = float(rows[1][0])
    return _compute_change_pct(latest, previous)


def _fetch_active_alerts_by_symbol(connection: Any, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not symbols:
        return {}
    placeholders = ', '.join('?' for _ in symbols)
    rows = connection.execute(
        f"""
        SELECT symbol, signal_type, signal_level, action, detail
        FROM alert_event
        WHERE symbol IN ({placeholders}) AND status IN ({', '.join('?' for _ in ACTIVE_ALERT_STATUSES)})
        ORDER BY symbol ASC, id ASC
        """,
        (*symbols, *ACTIVE_ALERT_STATUSES),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for row in rows:
        grouped[str(row[0])].append(
            {
                'signal_type': str(row[1]),
                'signal_level': str(row[2]),
                'action': str(row[3]),
                'detail': row[4],
            }
        )
    return grouped


def _top_action(alerts: list[dict[str, Any]]) -> str | None:
    if not alerts:
        return None
    return max(alerts, key=lambda item: ACTION_PRIORITY.get(str(item['action']), 0)).get('action')


def _build_historical_trade(connection: Any, symbol: str) -> dict[str, Any] | None:
    rows = connection.execute(
        """
        SELECT trade_type, trade_date, price, quantity, reason
        FROM trade_log
        WHERE symbol = ?
        ORDER BY trade_date ASC, id ASC
        """,
        (symbol,),
    ).fetchall()
    if not rows:
        return None
    buys = [row for row in rows if str(row[0]) == 'buy']
    sells = [row for row in rows if str(row[0]) == 'sell']
    if not buys or not sells:
        return None
    total_bought_shares = sum(float(row[3]) for row in buys)
    total_bought_cost = sum(float(row[2]) * float(row[3]) for row in buys)
    total_sold_shares = sum(float(row[3]) for row in sells)
    if total_sold_shares <= 0:
        return None
    avg_cost = total_bought_cost / total_bought_shares if total_bought_shares else 0.0
    total_sell_value = sum(float(row[2]) * float(row[3]) for row in sells)
    sell_price = total_sell_value / total_sold_shares
    realized_pnl = total_sell_value - avg_cost * total_sold_shares
    realized_pnl_pct = (realized_pnl / (avg_cost * total_sold_shares)) * 100 if avg_cost > 0 and total_sold_shares > 0 else None
    company_row = connection.execute('SELECT company_name FROM stock_master WHERE symbol = ?', (symbol,)).fetchone()
    return {
        'symbol': symbol,
        'company_name': str(company_row[0]) if company_row is not None else symbol,
        'first_buy_date': str(min(row[1] for row in buys)),
        'last_sell_date': str(max(row[1] for row in sells)),
        'holding_days': _days_between(str(min(row[1] for row in buys)), str(max(row[1] for row in sells))),
        'avg_cost': _round_number(avg_cost) or 0.0,
        'sell_price': _round_number(sell_price) or 0.0,
        'total_shares': int(total_sold_shares),
        'realized_pnl': _round_number(realized_pnl) or 0.0,
        'realized_pnl_pct': _round_number(realized_pnl_pct),
        'buy_reason': next((row[4] for row in buys if row[4]), None),
        'sell_reason': next((row[4] for row in reversed(sells) if row[4]), None),
    }


def _resolve_research_status(status: str, overall_conclusion: Any, summary: Any) -> str:
    if not status:
        return '未研究'
    if status == 'failed':
        return '研究失败'
    if status == 'reused':
        return '复用'
    if status in {'pending', 'running'}:
        return '待研究'
    if status == 'completed':
        text = str(summary or '').strip()
        if text.lower().startswith('fallback') or '降级' in text:
            return '降级研究'
        if overall_conclusion:
            return '已研究'
        return '未研究'
    return RESEARCH_STATUS_LABELS.get(status, '未研究')


def _map_research_status_to_quality_level(status: str, raw_response: Any) -> str:
    if status == 'failed':
        return 'fail'
    raw_text = str(raw_response or '')
    if raw_text.strip().lower().startswith('fallback'):
        return 'fallback'
    if status == 'reused':
        return 'pass'
    return 'pass' if status == 'completed' else status or 'pass'


def _extract_hit_reasons(notes_json: Any, detail_json: Any, screen_payload: dict[str, Any]) -> list[str]:
    notes_payload = _load_json(notes_json, {})
    detail_payload = _load_json(detail_json, {})
    reasons: list[str] = []
    for payload in (notes_payload, detail_payload):
        eligibility = payload.get('eligibility_reasons') or payload.get('reasons') or []
        if isinstance(eligibility, list):
            for item in eligibility:
                text = str(item).strip()
                if text and text not in reasons:
                    reasons.append(text)
    screen_reasons = screen_payload.get('scoreDetail', {}).get('eligibility', {}).get('reasons', [])
    if isinstance(screen_reasons, list):
        for item in screen_reasons:
            text = str(item).strip()
            if text and text not in reasons:
                reasons.append(text)
    return reasons[:3]


def _extract_metric(screen_payload: dict[str, Any], key: str, multiplier: float = 1.0) -> float | None:
    metrics = screen_payload.get('scoreDetail', {}).get('metrics', {})
    if not isinstance(metrics, dict):
        return None
    return _round_number(metrics.get(key), multiplier=multiplier)


def _extract_previous_price(screen_payload: dict[str, Any]) -> float | None:
    for key in ('previousClose', 'previous_close', 'prev_price'):
        value = screen_payload.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _coalesce_price(*values: Any) -> float | None:
    for value in values:
        if value is None or value == '':
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _compute_change_pct(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous in (None, 0):
        return None
    return ((latest - previous) / previous) * 100


def _load_json(raw_value: Any, default: Any) -> Any:
    if raw_value in (None, ''):
        return default
    try:
        return json.loads(str(raw_value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def _days_since(value: str) -> int:
    return _days_between(value, date.today().isoformat())


def _days_between(start: str, end: str) -> int:
    try:
        start_date = date.fromisoformat(start[:10])
        end_date = date.fromisoformat(end[:10])
    except ValueError:
        return 0
    return max((end_date - start_date).days, 0)
