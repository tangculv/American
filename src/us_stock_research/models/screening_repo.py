from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..config import ProjectPaths
from ..lifecycle import transition_stock_state
from ..scoring_engine import build_scoring_payload
from ..technical_analysis import infer_basic_technical_snapshot, technical_timing_score
from ..utils.validators import ensure_non_empty_string
from ..workflow_engine import enqueue_research, persist_research_analysis, persist_technical_snapshot
from .audit import append_audit_log
from .database import sqlite_connection
from .lifecycle_repo import upsert_stock_core
from .schema import ensure_schema

PROTECTED_ACTIVE_STATES = {
    "queued_for_research",
    "researched",
    "scored",
    "waiting_for_setup",
    "buy_ready",
    "holding",
    "exit_watch",
    "exited",
}


def _current_state(connection: Any, symbol: str) -> str | None:
    row = connection.execute(
        "SELECT lifecycle_state FROM stock_master WHERE symbol = ?",
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0])



def _resolved_state(existing_state: str | None, screening_passed: bool) -> str:
    if existing_state in PROTECTED_ACTIVE_STATES:
        return existing_state
    return "shortlisted" if screening_passed else "rejected"



def _upsert_stock_master(
    connection: Any,
    *,
    stock: dict[str, Any],
    run_at_iso: str,
    correlation_id: str,
    state: str,
) -> None:
    upsert_stock_core(
        stock=stock,
        lifecycle_state=state,
        correlation_id=correlation_id,
        run_at_iso=run_at_iso,
        connection=connection,
    )



def _upsert_strategy_hit(
    connection: Any,
    *,
    symbol: str,
    strategy_key: str,
    hit_at: str,
    correlation_id: str,
    stock: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO strategy_hit (
            symbol,
            strategy_id,
            strategy_name,
            strategy_version,
            hit_date,
            hit_at,
            screening_params_json,
            initial_score,
            result,
            rejection_reason,
            correlation_id,
            screen_payload_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, strategy_name, hit_at) DO UPDATE SET
            strategy_id = excluded.strategy_id,
            strategy_version = excluded.strategy_version,
            hit_date = excluded.hit_date,
            screening_params_json = excluded.screening_params_json,
            initial_score = excluded.initial_score,
            result = excluded.result,
            rejection_reason = excluded.rejection_reason,
            correlation_id = excluded.correlation_id,
            screen_payload_json = excluded.screen_payload_json
        """,
        (
            symbol,
            strategy_key,
            strategy_key,
            "v1.0",
            hit_at[:10],
            hit_at,
            json.dumps({"source": "screening_repo"}, ensure_ascii=False, sort_keys=True),
            None,
            "pending",
            None,
            correlation_id,
            json.dumps(stock, ensure_ascii=False, sort_keys=True),
            hit_at,
        ),
    )



def _upsert_scoring_breakdown(
    connection: Any,
    *,
    stock: dict[str, Any],
    strategy_key: str,
    scored_at: str,
    correlation_id: str,
    ranking: dict[str, Any] | None,
    screening_passed: bool,
) -> None:
    symbol = ensure_non_empty_string(stock.get("symbol"), "symbol")
    detail = dict(stock.get("scoreDetail", {}))
    tier = detail.get("tier", {}) if isinstance(detail.get("tier"), dict) else {}
    eligibility = detail.get("eligibility", {}) if isinstance(detail.get("eligibility"), dict) else {}
    technical_snapshot = infer_basic_technical_snapshot(stock)
    research_row = connection.execute(
        """
        SELECT ra.confidence_score, ra.bull_thesis_json, ra.bear_thesis_json, ra.key_risks_json, ra.catalysts_json
        FROM research_analysis ra
        JOIN research_snapshot rs ON rs.id = ra.research_snapshot_id
        WHERE ra.symbol = ?
        ORDER BY rs.research_date DESC, ra.id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    research_analysis = None
    if research_row is not None:
        research_analysis = {
            'confidence_score': int(research_row[0] or 0),
            'bull_thesis': json.loads(research_row[1] or '[]'),
            'bear_thesis': json.loads(research_row[2] or '[]'),
            'key_risks': json.loads(research_row[3] or '[]'),
            'catalysts': json.loads(research_row[4] or '[]'),
        }
    scoring_payload = build_scoring_payload(
        stock,
        market_trend='default',
        technical_timing=technical_timing_score(technical_snapshot),
        technical_signal=technical_snapshot.signal,
        price_stale=technical_snapshot.price_stale,
        research_analysis=research_analysis,
        avg_volume=stock.get('volume') or stock.get('avgVolume') or stock.get('volAvg'),
        market_cap=stock.get('marketCap'),
    )
    notes_payload = {
        "eligibility_reasons": eligibility.get("reasons", []),
        "tier": tier,
    }
    weights_payload = {
        "model": "baseline_v1_scoring_bridge",
        "ranking": ranking or {},
    }
    connection.execute(
        """
        INSERT INTO scoring_breakdown (
            symbol,
            strategy_name,
            strategy_id,
            score_date,
            scored_at,
            correlation_id,
            fundamental_quality,
            fq_roe_score,
            fq_margin_score,
            fq_debt_score,
            fq_current_ratio_score,
            valuation_attractiveness,
            va_pe_score,
            va_pb_score,
            va_ev_ebitda_score,
            research_conclusion,
            catalyst,
            risk,
            technical_timing,
            execution_priority,
            weight_profile,
            formula_version,
            applied_weights_json,
            weight_adjustments_json,
            trigger_context_json,
            source_snapshot_refs_json,
            total_score,
            missing_dimensions_json,
            partial_score,
            passed_screening,
            tier_code,
            detail_json,
            weights_json,
            notes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, strategy_name, score_date) DO UPDATE SET
            strategy_id = excluded.strategy_id,
            score_date = excluded.score_date,
            correlation_id = excluded.correlation_id,
            fundamental_quality = excluded.fundamental_quality,
            fq_roe_score = excluded.fq_roe_score,
            fq_margin_score = excluded.fq_margin_score,
            fq_debt_score = excluded.fq_debt_score,
            fq_current_ratio_score = excluded.fq_current_ratio_score,
            valuation_attractiveness = excluded.valuation_attractiveness,
            va_pe_score = excluded.va_pe_score,
            va_pb_score = excluded.va_pb_score,
            va_ev_ebitda_score = excluded.va_ev_ebitda_score,
            research_conclusion = excluded.research_conclusion,
            catalyst = excluded.catalyst,
            risk = excluded.risk,
            technical_timing = excluded.technical_timing,
            execution_priority = excluded.execution_priority,
            weight_profile = excluded.weight_profile,
            formula_version = excluded.formula_version,
            applied_weights_json = excluded.applied_weights_json,
            weight_adjustments_json = excluded.weight_adjustments_json,
            trigger_context_json = excluded.trigger_context_json,
            source_snapshot_refs_json = excluded.source_snapshot_refs_json,
            total_score = excluded.total_score,
            missing_dimensions_json = excluded.missing_dimensions_json,
            partial_score = excluded.partial_score,
            passed_screening = excluded.passed_screening,
            tier_code = excluded.tier_code,
            detail_json = excluded.detail_json,
            weights_json = excluded.weights_json,
            notes_json = excluded.notes_json
        """,
        (
            symbol,
            strategy_key,
            strategy_key,
            scored_at,
            scored_at,
            correlation_id,
            float(scoring_payload["dimensions"]["fundamental_quality"]),
            float(scoring_payload["details"].get("fq_roe_score", 0)),
            float(scoring_payload["details"].get("fq_margin_score", 0)),
            float(scoring_payload["details"].get("fq_debt_score", 0)),
            float(scoring_payload["details"].get("fq_current_ratio_score", 0)),
            float(scoring_payload["dimensions"]["valuation_attractiveness"]),
            float(scoring_payload["details"].get("va_pe_score", 0)),
            float(scoring_payload["details"].get("va_pb_score", 0)),
            float(scoring_payload["details"].get("va_ev_ebitda_score", 0)),
            float(scoring_payload["dimensions"]["research_conclusion"]),
            float(scoring_payload["dimensions"]["catalyst"]),
            float(scoring_payload["dimensions"]["risk"]),
            float(scoring_payload["dimensions"]["technical_timing"]),
            float(scoring_payload["dimensions"]["execution_priority"]),
            str(scoring_payload["weight_profile"]),
            str(scoring_payload["formula_version"]),
            json.dumps(scoring_payload["applied_weights"], ensure_ascii=False, sort_keys=True),
            json.dumps(scoring_payload["weight_adjustments"], ensure_ascii=False, sort_keys=True),
            json.dumps(scoring_payload["trigger_context"], ensure_ascii=False, sort_keys=True),
            json.dumps({'research_analysis': bool(research_analysis)}, ensure_ascii=False, sort_keys=True),
            float(scoring_payload["total_score"]),
            json.dumps(scoring_payload["missing_dimensions"], ensure_ascii=False, sort_keys=True),
            1 if scoring_payload["partial_score"] else 0,
            1 if screening_passed else 0,
            str(tier.get("code") or ("screening_pass" if screening_passed else "rejected")),
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
            json.dumps(weights_payload, ensure_ascii=False, sort_keys=True),
            json.dumps({**notes_payload, 'score_change_reason': scoring_payload.get('score_change_reason')}, ensure_ascii=False, sort_keys=True),
        ),
    )



def _upsert_ranking_snapshot(
    connection: Any,
    *,
    stock: dict[str, Any],
    strategy_key: str,
    generated_at: str,
    correlation_id: str,
    rank_position: int,
) -> None:
    symbol = ensure_non_empty_string(stock.get("symbol"), "symbol")
    detail = dict(stock.get("scoreDetail", {}))
    eligibility = detail.get("eligibility", {}) if isinstance(detail.get("eligibility"), dict) else {}
    tie_break_trace = {
        "score": float(stock.get("score", 0) or 0),
        "eligibility_passed": bool(eligibility.get("passed")),
        "tier_code": detail.get("tier", {}).get("code") if isinstance(detail.get("tier"), dict) else None,
        "symbol": symbol,
    }
    connection.execute(
        """
        INSERT INTO ranking_snapshot (
            strategy_name,
            generated_at,
            correlation_id,
            symbol,
            rank_position,
            total_score,
            tie_break_trace_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_name, generated_at, symbol) DO UPDATE SET
            correlation_id = excluded.correlation_id,
            rank_position = excluded.rank_position,
            total_score = excluded.total_score,
            tie_break_trace_json = excluded.tie_break_trace_json
        """,
        (
            strategy_key,
            generated_at,
            correlation_id,
            symbol,
            rank_position,
            float(stock.get("score", 0) or 0),
            json.dumps(tie_break_trace, ensure_ascii=False, sort_keys=True),
        ),
    )



def persist_screening_run(
    *,
    strategy_key: str,
    strategy_display_name: str,
    screened_stocks: list[dict[str, Any]],
    ranked_stocks: list[dict[str, Any]],
    generated_at: datetime,
    correlation_id: str,
    ranking: dict[str, Any] | None = None,
    paths: ProjectPaths | None = None,
) -> dict[str, int]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    strategy_key = ensure_non_empty_string(strategy_key, "strategy_key")
    strategy_display_name = ensure_non_empty_string(strategy_display_name, "strategy_display_name")
    run_at_iso = generated_at.replace(microsecond=0).isoformat()
    ranked_positions = {
        ensure_non_empty_string(stock.get("symbol"), "symbol"): index
        for index, stock in enumerate(ranked_stocks, start=1)
    }

    with sqlite_connection(paths) as connection:
        for stock in screened_stocks:
            symbol = ensure_non_empty_string(stock.get("symbol"), "symbol")
            existing_state = _current_state(connection, symbol)
            detail = stock.get("scoreDetail", {}) if isinstance(stock.get("scoreDetail"), dict) else {}
            eligibility = detail.get("eligibility", {}) if isinstance(detail.get("eligibility"), dict) else {}
            screening_passed = bool(eligibility.get("passed"))
            resolved_state = _resolved_state(existing_state, screening_passed)

            _upsert_stock_master(
                connection,
                stock=stock,
                run_at_iso=run_at_iso,
                correlation_id=correlation_id,
                state=resolved_state,
            )
            _upsert_strategy_hit(
                connection,
                symbol=symbol,
                strategy_key=strategy_key,
                hit_at=run_at_iso,
                correlation_id=correlation_id,
                stock=stock,
            )
            _upsert_scoring_breakdown(
                connection,
                stock=stock,
                strategy_key=strategy_key,
                scored_at=run_at_iso,
                correlation_id=correlation_id,
                ranking=ranking,
                screening_passed=screening_passed,
            )

            append_audit_log(
                entity_type="stock",
                entity_key=symbol,
                action="screening_hit_recorded",
                previous_state=str(existing_state or ""),
                new_state=resolved_state,
                correlation_id=correlation_id,
                payload={
                    "strategy_key": strategy_key,
                    "strategy_display_name": strategy_display_name,
                    "screening_passed": screening_passed,
                    "score": float(stock.get("score", 0) or 0),
                },
                created_at=run_at_iso,
                paths=paths,
                connection=connection,
            )

            if existing_state not in PROTECTED_ACTIVE_STATES:
                transition_stock_state(
                    symbol=symbol,
                    from_state="discovered",
                    to_state=resolved_state,
                    trigger_source="screening_run",
                    correlation_id=correlation_id,
                    paths=paths,
                    payload={
                        "strategy_key": strategy_key,
                        "strategy_display_name": strategy_display_name,
                        "screening_passed": screening_passed,
                    },
                    connection=connection,
                )
                connection.execute(
                    """
                    UPDATE stock_master
                    SET lifecycle_state = ?, current_state = ?, lifecycle_changed_at = ?, updated_at = ?
                    WHERE symbol = ?
                    """,
                    (resolved_state, resolved_state, run_at_iso, run_at_iso, symbol),
                )
                if screening_passed:
                    connection.execute(
                        """
                        UPDATE stock_master
                        SET entry_date = COALESCE(entry_date, ?),
                            updated_at = ?
                        WHERE symbol = ?
                        """,
                        (run_at_iso, run_at_iso, symbol),
                    )
                    research_snapshot_id = enqueue_research(
                        symbol=symbol,
                        strategy_id=strategy_key,
                        correlation_id=correlation_id,
                        paths=paths,
                        connection=connection,
                    )
                    persist_research_analysis(
                        symbol=symbol,
                        stock=stock,
                        research_snapshot_id=research_snapshot_id,
                        correlation_id=correlation_id,
                        paths=paths,
                        connection=connection,
                    )
                    connection.execute(
                        """
                        UPDATE stock_master
                        SET first_research_at = COALESCE(first_research_at, ?),
                            updated_at = ?
                        WHERE symbol = ?
                        """,
                        (run_at_iso, run_at_iso, symbol),
                    )
                    technical_snapshot = infer_basic_technical_snapshot(stock)
                    persist_technical_snapshot(
                        symbol=symbol,
                        snapshot=technical_snapshot,
                        price=stock.get("price"),
                        snapshot_date=run_at_iso[:10],
                        paths=paths,
                        connection=connection,
                    )
                    connection.execute(
                        """
                        UPDATE stock_master
                        SET latest_signal = ?,
                            trade_gate_blocked = ?,
                            first_technical_at = COALESCE(first_technical_at, ?),
                            updated_at = ?
                        WHERE symbol = ?
                        """,
                        (
                            technical_snapshot.signal,
                            1 if technical_snapshot.gate_is_blocked else 0,
                            run_at_iso,
                            run_at_iso,
                            symbol,
                        ),
                    )
                connection.execute(
                    """
                    UPDATE strategy_hit
                    SET result = ?, initial_score = ?, rejection_reason = ?
                    WHERE symbol = ? AND strategy_name = ? AND hit_at = ?
                    """,
                    (
                        "shortlisted" if screening_passed else "rejected",
                        float(stock.get("score", 0) or 0),
                        None if screening_passed else "screening_gate_failed",
                        symbol,
                        strategy_key,
                        run_at_iso,
                    ),
                )
            else:
                append_audit_log(
                    entity_type="stock",
                    entity_key=symbol,
                    action="screening_state_preserved",
                    previous_state=existing_state,
                    new_state=existing_state,
                    correlation_id=correlation_id,
                    payload={
                        "strategy_key": strategy_key,
                        "strategy_display_name": strategy_display_name,
                        "requested_state": resolved_state,
                    },
                    created_at=run_at_iso,
                    paths=paths,
                    connection=connection,
                )
                connection.execute(
                    """
                    UPDATE stock_master
                    SET lifecycle_state = ?, current_state = ?, updated_at = ?
                    WHERE symbol = ?
                    """,
                    (existing_state, existing_state, run_at_iso, symbol),
                )
                connection.execute(
                    """
                    UPDATE strategy_hit
                    SET result = ?, initial_score = ?, rejection_reason = ?
                    WHERE symbol = ? AND strategy_name = ? AND hit_at = ?
                    """,
                    (
                        "shortlisted" if screening_passed else "rejected",
                        float(stock.get("score", 0) or 0),
                        None if screening_passed else "screening_gate_failed",
                        symbol,
                        strategy_key,
                        run_at_iso,
                    ),
                )

            if screening_passed and symbol in ranked_positions:
                _upsert_ranking_snapshot(
                    connection,
                    stock=stock,
                    strategy_key=strategy_key,
                    generated_at=run_at_iso,
                    correlation_id=correlation_id,
                    rank_position=ranked_positions[symbol],
                )

        append_audit_log(
            entity_type="screening_run",
            entity_key=f"{strategy_key}:{run_at_iso}",
            action="screening_persisted",
            correlation_id=correlation_id,
            payload={
                "strategy_key": strategy_key,
                "strategy_display_name": strategy_display_name,
                "screened_count": len(screened_stocks),
                "ranked_count": len(ranked_stocks),
            },
            created_at=run_at_iso,
            paths=paths,
            connection=connection,
        )

    return {
        "screenedCount": len(screened_stocks),
        "rankedCount": len(ranked_stocks),
    }
