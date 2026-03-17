from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from .config import ProjectPaths, load_app_config
from .lifecycle import transition_stock_state
from .models.audit import append_audit_log
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .research_engine import analysis_to_db_payload, run_deep_research
from .technical_analysis import TechnicalSnapshot
from .time_utils import utc_now, utc_now_iso


def _utc_now_iso() -> str:
    return utc_now_iso()


def persist_technical_snapshot(
    *,
    symbol: str,
    snapshot: TechnicalSnapshot,
    price: float | None,
    snapshot_date: str | None = None,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> None:
    effective_date = snapshot_date or utc_now().date().isoformat()
    sql = """
    INSERT INTO technical_snapshot (
        symbol,
        snapshot_date,
        price,
        ma_5,
        ma_10,
        ma_20,
        ma_50,
        ma_200,
        ma_20_slope,
        rsi_14,
        macd_line,
        macd_signal,
        macd_histogram,
        atr_14,
        atr_pct,
        bb_upper,
        bb_lower,
        volume_ratio,
        high_52w,
        low_52w,
        daily_trend,
        weekly_trend,
        trend_strength_days,
        signal,
        gate_is_blocked,
        gate_block_reasons_json,
        gate_blocked_since
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol, snapshot_date) DO UPDATE SET
        price = excluded.price,
        ma_5 = excluded.ma_5,
        ma_10 = excluded.ma_10,
        ma_20 = excluded.ma_20,
        ma_50 = excluded.ma_50,
        ma_200 = excluded.ma_200,
        ma_20_slope = excluded.ma_20_slope,
        rsi_14 = excluded.rsi_14,
        macd_line = excluded.macd_line,
        macd_signal = excluded.macd_signal,
        macd_histogram = excluded.macd_histogram,
        atr_14 = excluded.atr_14,
        atr_pct = excluded.atr_pct,
        bb_upper = excluded.bb_upper,
        bb_lower = excluded.bb_lower,
        volume_ratio = excluded.volume_ratio,
        high_52w = excluded.high_52w,
        low_52w = excluded.low_52w,
        daily_trend = excluded.daily_trend,
        weekly_trend = excluded.weekly_trend,
        trend_strength_days = excluded.trend_strength_days,
        signal = excluded.signal,
        gate_is_blocked = excluded.gate_is_blocked,
        gate_block_reasons_json = excluded.gate_block_reasons_json,
        gate_blocked_since = excluded.gate_blocked_since
    """
    params = (
        symbol,
        effective_date,
        float(price or 0),
        snapshot.ma_5,
        snapshot.ma_10,
        snapshot.ma_20,
        snapshot.ma_50,
        snapshot.ma_200,
        snapshot.ma_20_slope,
        snapshot.rsi_14,
        snapshot.macd_line,
        snapshot.macd_signal,
        snapshot.macd_histogram,
        snapshot.atr_14,
        snapshot.atr_pct,
        snapshot.bb_upper,
        snapshot.bb_lower,
        snapshot.volume_ratio,
        snapshot.high_52w,
        snapshot.low_52w,
        snapshot.daily_trend,
        snapshot.weekly_trend,
        snapshot.trend_strength_days,
        snapshot.signal,
        1 if snapshot.gate_is_blocked else 0,
        json.dumps(snapshot.gate_block_reasons, ensure_ascii=False, sort_keys=True),
        _utc_now_iso() if snapshot.gate_is_blocked else None,
    )
    if connection is not None:
        connection.execute(sql, params)
        return
    with sqlite_connection(paths) as db:
        db.execute(sql, params)


def apply_post_scoring_state_machine(
    *,
    symbol: str,
    technical_snapshot: TechnicalSnapshot,
    correlation_id: str,
    scored_at: str,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> str:
    next_state = 'waiting_for_setup' if technical_snapshot.gate_is_blocked else 'buy_ready'
    transition_stock_state(
        symbol=symbol,
        from_state='scored',
        to_state=next_state,
        trigger_source='technical_gate',
        correlation_id=correlation_id,
        payload={
            'technical_signal': technical_snapshot.signal,
            'gate_is_blocked': technical_snapshot.gate_is_blocked,
            'gate_block_reasons': technical_snapshot.gate_block_reasons,
        },
        paths=paths,
        connection=connection,
    )
    connection.execute(
        """
        UPDATE stock_master
        SET lifecycle_state = ?,
            current_state = ?,
            lifecycle_changed_at = ?,
            latest_signal = ?,
            trade_gate_blocked = ?,
            first_technical_at = COALESCE(first_technical_at, ?),
            updated_at = ?
        WHERE symbol = ?
        """,
        (
            next_state,
            next_state,
            scored_at,
            technical_snapshot.signal,
            1 if technical_snapshot.gate_is_blocked else 0,
            scored_at,
            scored_at,
            symbol,
        ),
    )
    return next_state


def enqueue_research(
    *,
    symbol: str,
    strategy_id: str,
    correlation_id: str,
    trigger_type: str = 'new_entry',
    trigger_priority: str = 'P1-C',
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> int:
    now = utc_now()
    expires_at = now + timedelta(days=14)
    sql = """
    INSERT INTO research_snapshot (
        symbol,
        research_date,
        trigger_type,
        trigger_priority,
        prompt_template_id,
        prompt_version,
        strategy_id,
        input_data_json,
        status,
        retry_count,
        expires_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    app_config = load_app_config(paths)
    perplexity_cfg = dict(dict(app_config.get('research', {})).get('perplexity', {}))
    prompt_template_id = str(perplexity_cfg.get('prompt_template_id', 'baseline_perplexity_template'))
    prompt_version = str(perplexity_cfg.get('prompt_version', 'v1.0'))
    params = (
        symbol,
        now.isoformat(),
        trigger_type,
        trigger_priority,
        prompt_template_id,
        prompt_version,
        strategy_id,
        json.dumps({'symbol': symbol}, ensure_ascii=False, sort_keys=True),
        'pending',
        0,
        expires_at.isoformat(),
    )
    if connection is None:
        with sqlite_connection(paths) as db:
            cursor = db.execute(sql, params)
            append_audit_log(
                entity_type='research_snapshot',
                entity_key=f'{symbol}:{cursor.lastrowid}',
                action='research_enqueued',
                previous_state='',
                new_state='queued_for_research',
                correlation_id=correlation_id,
                payload={'symbol': symbol, 'strategy_id': strategy_id},
                connection=db,
            )
            return int(cursor.lastrowid)

    cursor = connection.execute(sql, params)
    append_audit_log(
        entity_type='research_snapshot',
        entity_key=f'{symbol}:{cursor.lastrowid}',
        action='research_enqueued',
        previous_state='',
        new_state='queued_for_research',
        correlation_id=correlation_id,
        payload={'symbol': symbol, 'strategy_id': strategy_id},
        connection=connection,
    )
    return int(cursor.lastrowid)




def persist_research_analysis_result(
    *,
    symbol: str,
    analysis: Any,
    research_snapshot_id: int,
    correlation_id: str,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> dict[str, Any]:
    payload = analysis_to_db_payload(analysis)
    sql = """
    INSERT INTO research_analysis (
        research_snapshot_id,
        symbol,
        bull_thesis_json,
        bear_thesis_json,
        key_risks_json,
        catalysts_json,
        valuation_view,
        target_price,
        invalidation_conditions_json,
        confidence_score,
        source_list_json,
        next_review_date,
        overall_recommendation
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(research_snapshot_id) DO UPDATE SET
        bull_thesis_json = excluded.bull_thesis_json,
        bear_thesis_json = excluded.bear_thesis_json,
        key_risks_json = excluded.key_risks_json,
        catalysts_json = excluded.catalysts_json,
        valuation_view = excluded.valuation_view,
        target_price = excluded.target_price,
        invalidation_conditions_json = excluded.invalidation_conditions_json,
        confidence_score = excluded.confidence_score,
        source_list_json = excluded.source_list_json,
        next_review_date = excluded.next_review_date,
        overall_recommendation = excluded.overall_recommendation
    """
    params = (
        research_snapshot_id,
        symbol,
        payload['bull_thesis_json'],
        payload['bear_thesis_json'],
        payload['key_risks_json'],
        payload['catalysts_json'],
        payload['valuation_view'],
        payload['target_price'],
        payload['invalidation_conditions_json'],
        payload['confidence_score'],
        payload['source_list_json'],
        payload['next_review_date'],
        payload['overall_recommendation'],
    )

    snapshot_sql = "UPDATE research_snapshot SET raw_response = ?, input_data_json = ?, status = 'completed' WHERE id = ?"
    snapshot_params = (
        payload.get('raw_response') or analysis.summary,
        payload.get('input_context_json') or json.dumps({'symbol': symbol}, ensure_ascii=False, sort_keys=True),
        research_snapshot_id,
    )

    if connection is None:
        with sqlite_connection(paths) as db:
            db.execute(sql, params)
            db.execute(snapshot_sql, snapshot_params)
            append_audit_log(
                entity_type='research_analysis',
                entity_key=f'{symbol}:{research_snapshot_id}',
                action='research_completed',
                previous_state='queued_for_research',
                new_state='researched',
                correlation_id=correlation_id,
                payload={
                    'symbol': symbol,
                    'research_snapshot_id': research_snapshot_id,
                    'provider': payload.get('provider'),
                    'model_name': payload.get('model_name', ''),
                    'fallback_used': payload.get('fallback_used', False),
                },
                connection=db,
            )
    else:
        connection.execute(sql, params)
        connection.execute(snapshot_sql, snapshot_params)
        append_audit_log(
            entity_type='research_analysis',
            entity_key=f'{symbol}:{research_snapshot_id}',
            action='research_completed',
            previous_state='queued_for_research',
            new_state='researched',
            correlation_id=correlation_id,
            payload={
                'symbol': symbol,
                'research_snapshot_id': research_snapshot_id,
                'provider': payload.get('provider'),
                'model_name': payload.get('model_name', ''),
                'fallback_used': payload.get('fallback_used', False),
            },
            connection=connection,
        )

    return {
        'confidence_score': analysis.confidence_score,
        'bull_thesis': analysis.bull_thesis,
        'bear_thesis': analysis.bear_thesis,
        'key_risks': analysis.key_risks,
        'catalysts': analysis.catalysts,
        'summary': analysis.summary,
        'provider': analysis.provider,
        'model_name': getattr(analysis, 'model_name', ''),
        'fallback_used': getattr(analysis, 'fallback_used', False),
    }


def persist_research_analysis(
    *,
    symbol: str,
    stock: dict[str, Any],
    research_snapshot_id: int,
    correlation_id: str,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> dict[str, Any]:
    analysis = run_deep_research(stock, paths=paths)
    return persist_research_analysis_result(
        symbol=symbol,
        analysis=analysis,
        research_snapshot_id=research_snapshot_id,
        correlation_id=correlation_id,
        paths=paths,
        connection=connection,
    )


def ensure_phase2_artifacts(paths: ProjectPaths | None = None) -> None:
    ensure_schema(paths)
