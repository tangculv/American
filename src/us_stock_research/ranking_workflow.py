from __future__ import annotations

import json
from .time_utils import utc_now_iso
from typing import Any
from uuid import uuid4

from .config import ProjectPaths
from .event_notifications import build_event_payload, create_notification_event
from .models.audit import append_audit_log
from .models.database import sqlite_connection
from .models.schema import ensure_schema

SCOPE_STATE_MAP = {
    "research_priority": ("queued_for_research",),
    "buy_priority": ("waiting_for_setup", "buy_ready"),
    "holding_monitor": ("holding", "exit_watch"),
    "global_overview": ("shortlisted", "queued_for_research", "researched", "scored", "waiting_for_setup", "buy_ready"),
}


def _utc_now_iso() -> str:
    return utc_now_iso()


def _load_universe(connection: Any, scope: str) -> tuple[list[dict[str, Any]], list[str]]:
    states = SCOPE_STATE_MAP[scope]
    placeholders = ",".join("?" for _ in states)
    rows = connection.execute(
        f"""
        SELECT
            sm.symbol,
            sm.company_name,
            sm.lifecycle_state,
            sm.first_discovered_at,
            sm.trade_gate_blocked,
            sm.latest_signal,
            sb.id AS scoring_id,
            sb.total_score,
            sb.research_conclusion,
            sb.technical_timing,
            sb.strategy_name,
            sb.scored_at
        FROM stock_master sm
        LEFT JOIN scoring_breakdown sb
          ON sb.id = (
              SELECT id FROM scoring_breakdown s2
              WHERE s2.symbol = sm.symbol
              ORDER BY s2.score_date DESC, s2.id DESC
              LIMIT 1
          )
        WHERE sm.lifecycle_state IN ({placeholders})
        """,
        states,
    ).fetchall()

    universe: list[dict[str, Any]] = []
    excluded: list[str] = []
    for row in rows:
        payload = {key: row[key] for key in row.keys()}
        if payload.get("scoring_id") is None:
            excluded.append(str(payload["symbol"]))
            continue
        universe.append(payload)
    return universe, excluded


def _sort_universe(universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        universe,
        key=lambda row: (
            -float(row.get("total_score") or 0),
            -float(row.get("research_conclusion") or 0),
            -float(row.get("technical_timing") or 0),
            str(row.get("first_discovered_at") or "9999-12-31T23:59:59"),
            str(row.get("symbol") or ""),
        ),
    )


def _tie_break_trace(current: dict[str, Any], other: dict[str, Any] | None) -> list[dict[str, Any]]:
    if other is None or float(current.get("total_score") or 0) != float(other.get("total_score") or 0):
        return []
    steps = []
    fields = [
        (1, "research_conclusion"),
        (2, "technical_timing"),
        (3, "first_discovered_at"),
        (4, "symbol"),
    ]
    decided = False
    for step, field in fields:
        self_value = current.get(field)
        other_value = other.get(field)
        if decided:
            steps.append({"step": step, "field": field, "skipped": True, "reason": "step_already_decided"})
            continue
        winner = "tie"
        if field in {"research_conclusion", "technical_timing"}:
            if float(self_value or 0) > float(other_value or 0):
                winner = "self"
                decided = True
            elif float(self_value or 0) < float(other_value or 0):
                winner = "other"
                decided = True
        else:
            if str(self_value or "") < str(other_value or ""):
                winner = "self"
                decided = True
            elif str(self_value or "") > str(other_value or ""):
                winner = "other"
                decided = True
        steps.append({"step": step, "field": field, "self": self_value, "other": other_value, "winner": winner})
    return steps


def _rank_reason_1(row: dict[str, Any]) -> str:
    dimensions = {
        "研究结论": float(row.get("research_conclusion") or 0),
        "技术时机": float(row.get("technical_timing") or 0),
        "总分": float(row.get("total_score") or 0),
    }
    winner = max(dimensions.items(), key=lambda item: item[1])
    return f"{winner[0]}最强，当前 {winner[1]:.2f}"


def _rank_reason_2(row: dict[str, Any]) -> str:
    dimensions = {
        "研究结论": float(row.get("research_conclusion") or 0),
        "技术时机": float(row.get("technical_timing") or 0),
    }
    loser = min(dimensions.items(), key=lambda item: item[1])
    return f"{loser[0]}偏弱，当前 {loser[1]:.2f}"


def _rank_reason_3(row: dict[str, Any]) -> str | None:
    if int(row.get("trade_gate_blocked") or 0):
        return "trade_gate 当前阻断"
    return None


def build_ranking_snapshot(*, scope: str, paths: ProjectPaths | None = None, correlation_id: str) -> dict[str, Any]:
    if scope not in SCOPE_STATE_MAP:
        raise ValueError(f"unsupported ranking scope: {scope}")
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    batch_id = str(uuid4())
    generated_at = _utc_now_iso()

    with sqlite_connection(paths) as connection:
        universe, excluded = _load_universe(connection, scope)
        ordered = _sort_universe(universe)
        universe_size = len(ordered)

        for index, row in enumerate(ordered, start=1):
            next_row = ordered[index] if index < universe_size else None
            tie_trace = _tie_break_trace(row, next_row)
            vs_next = None
            if next_row is not None:
                diff = round(float(row.get("total_score") or 0) - float(next_row.get("total_score") or 0), 2)
                vs_next = f"比第{index + 1}名{next_row['symbol']}高{diff:.2f}分"
            connection.execute(
                """
                INSERT INTO ranking_snapshot (
                    symbol,
                    ranking_date,
                    ranking_scope,
                    rank,
                    total_score,
                    rank_reason_1,
                    rank_reason_2,
                    rank_reason_3,
                    tie_break_trace_json,
                    strategy_name,
                    generated_at,
                    correlation_id,
                    rank_position,
                    snapshot_batch_id,
                    scoring_id,
                    universe_size,
                    rank_percentile,
                    trade_gate_status,
                    actionable,
                    vs_next_rank,
                    excluded_symbols_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["symbol"],
                    generated_at,
                    scope,
                    index,
                    float(row.get("total_score") or 0),
                    _rank_reason_1(row),
                    _rank_reason_2(row),
                    _rank_reason_3(row),
                    json.dumps(tie_trace, ensure_ascii=False, sort_keys=True),
                    str(row.get("strategy_name") or scope),
                    generated_at,
                    correlation_id,
                    index,
                    batch_id,
                    int(row["scoring_id"]),
                    universe_size,
                    ((universe_size - index + 1) / universe_size * 100) if universe_size else 0,
                    "blocked" if int(row.get("trade_gate_blocked") or 0) else "unblocked",
                    0 if int(row.get("trade_gate_blocked") or 0) else 1,
                    vs_next,
                    json.dumps(excluded, ensure_ascii=False, sort_keys=True),
                    generated_at,
                ),
            )

        append_audit_log(
            entity_type="ranking_snapshot_batch",
            entity_key=f"{scope}:{batch_id}",
            action="ranking_snapshot_built",
            correlation_id=correlation_id,
            payload={
                "scope": scope,
                "snapshot_batch_id": batch_id,
                "universe_size": universe_size,
                "excluded_symbols": excluded,
                "generated_at": generated_at,
                "status": "partial" if excluded else "ok",
            },
            created_at=generated_at,
            connection=connection,
        )

        if ordered:
            leader = ordered[0]
            latest_score = float(leader.get("total_score") or 0)
            previous = connection.execute(
                """
                SELECT total_score
                FROM ranking_snapshot
                WHERE symbol = ? AND ranking_scope = ? AND snapshot_batch_id <> ?
                ORDER BY generated_at DESC, id DESC
                LIMIT 1
                """,
                (leader["symbol"], scope, batch_id),
            ).fetchone()
            if previous is not None:
                delta = round(latest_score - float(previous[0] or 0), 2)
                if abs(delta) >= 5:
                    create_notification_event(
                        event_type="score_change_significant",
                        payload=build_event_payload(
                            event_type="score_change_significant",
                            symbol=leader["symbol"],
                            summary=f"{leader['symbol']} 评分显著变化",
                            correlation_id=correlation_id,
                            facts={
                                "ranking_scope": scope,
                                "previous_score": float(previous[0] or 0),
                                "current_score": latest_score,
                                "delta": delta,
                                "rank": 1,
                            },
                            actions=[{"action": "view_ranking", "label": "查看最新排序"}],
                        ),
                        correlation_id=correlation_id,
                        symbol=leader["symbol"],
                        dedupe_key=f"score_change_significant:{scope}:{leader['symbol']}:{generated_at[:10]}",
                        paths=paths,
                        connection=connection,
                    )

        return {
            "scope": scope,
            "snapshot_batch_id": batch_id,
            "generated_at": generated_at,
            "universe_size": universe_size,
            "excluded_symbols": excluded,
        }
