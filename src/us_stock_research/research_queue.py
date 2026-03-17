from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
import time
from typing import Any
from zoneinfo import ZoneInfo

from .config import ProjectPaths
from .event_notifications import build_event_payload, create_notification_event
from .models.audit import append_audit_log
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .time_utils import utc_now

PRIORITY_ORDER = {
    "P0": 0,
    "P1-B": 1,
    "P1-C": 2,
    "P1-A": 3,
    "P2": 4,
}
SOFT_DAILY_BUDGET = 20
HARD_DAILY_BUDGET = 50
MAX_CONCURRENT_SLOTS = 3
BACKLOG_ALERT_THRESHOLD = 50
RECOVERY_REORDER_HOUR_ET = 9
RECOVERY_REORDER_MINUTE_ET = 0
RECOVERY_TIMEZONE = "America/New_York"


MAX_DAILY_RESEARCH = 15
DEDUP_DAYS = 10
RESEARCH_INTERVAL_SECONDS = 5
DEDUP_SIGNIFICANT_CHANGE_PCT = 5.0
RESEARCH_TIMEZONE = "America/New_York"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueueTask:
    id: int
    symbol: str
    trigger_type: str
    trigger_priority: str
    status: str
    retry_count: int
    research_date: str
    error_message: str | None = None



def _utc_now():
    return utc_now()



def _utc_now_iso() -> str:
    return _utc_now().isoformat()



def _sort_key(task: dict[str, Any]) -> tuple[Any, ...]:
    priority = str(task.get("trigger_priority") or "P2")
    trigger_type = str(task.get("trigger_type") or "")
    if priority == "P1-B":
        severity = -abs(float(task.get("crash_pct") or 0))
        return (PRIORITY_ORDER[priority], severity, str(task.get("research_date") or ""), str(task.get("symbol") or ""))
    if priority == "P1-C":
        return (PRIORITY_ORDER[priority], str(task.get("earnings_at") or ""), str(task.get("symbol") or ""))
    if priority == "P1-A":
        return (PRIORITY_ORDER[priority], str(task.get("first_discovered_at") or ""), str(task.get("symbol") or ""))
    if priority == "P2":
        return (PRIORITY_ORDER[priority], str(task.get("last_research_at") or ""), str(task.get("symbol") or ""))
    if priority == "P0":
        return (PRIORITY_ORDER[priority], str(task.get("research_date") or ""), str(task.get("symbol") or ""))
    return (99, trigger_type, str(task.get("symbol") or ""))



def _json_text_safe(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}



def _queue_snapshot(connection: Any) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT trigger_priority, COUNT(*) FROM research_snapshot WHERE status IN ('pending','retry_pending','in_progress') GROUP BY trigger_priority"
    ).fetchall()
    distribution = {str(row[0]): int(row[1]) for row in rows}
    active_slots = int(
        connection.execute("SELECT COUNT(*) FROM research_snapshot WHERE status = 'in_progress'").fetchone()[0]
    )
    return {
        "depth": sum(distribution.values()),
        "distribution": distribution,
        "active_slots": active_slots,
        "max_concurrent_slots": MAX_CONCURRENT_SLOTS,
    }



def _daily_budget_snapshot(connection: Any, day_key: str | None = None) -> dict[str, Any]:
    effective_day = day_key or connection.execute(
        "SELECT COALESCE(MAX(substr(created_at, 1, 10)), ?) FROM audit_log WHERE entity_type = 'research_queue' AND action = 'research_queue_claimed'",
        (_utc_now_iso()[:10],),
    ).fetchone()[0]
    claimed = int(
        connection.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity_type = 'research_queue' AND action = 'research_queue_claimed' AND substr(created_at, 1, 10) = ?",
            (effective_day,),
        ).fetchone()[0]
    )
    return {
        "day": effective_day,
        "claimed_today": claimed,
        "soft_budget": SOFT_DAILY_BUDGET,
        "hard_budget": HARD_DAILY_BUDGET,
        "soft_budget_remaining": max(SOFT_DAILY_BUDGET - claimed, 0),
        "hard_budget_remaining": max(HARD_DAILY_BUDGET - claimed, 0),
    }



def _maybe_create_backlog_alert(*, connection: Any, correlation_id: str, paths: ProjectPaths | None = None) -> dict[str, Any] | None:
    snapshot = _queue_snapshot(connection)
    if int(snapshot["depth"]) <= BACKLOG_ALERT_THRESHOLD:
        return None
    payload = build_event_payload(
        event_type="system_error",
        symbol=None,
        summary="研究队列积压超过阈值",
        correlation_id=correlation_id,
        facts={
            "error_type": "queue_backlog",
            "job_id": "research_queue",
            "backlog_depth": snapshot["depth"],
            "threshold": BACKLOG_ALERT_THRESHOLD,
        },
        actions=[{"action": "view_queue", "label": "查看研究队列"}],
    )
    return create_notification_event(
        event_type="system_error",
        payload=payload,
        correlation_id=correlation_id,
        dedupe_key=f"system_error:queue_backlog:{_utc_now_iso()[:10]}",
        paths=paths,
        connection=connection,
    )





def _et_today() -> datetime.date:
    return datetime.now(ZoneInfo(RESEARCH_TIMEZONE)).date()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = str(value).replace('Z', '+00:00')
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo('UTC'))
    return parsed


def _latest_completed_research_et_date(symbol: str, connection: Any) -> str | None:
    row = connection.execute(
        """
        SELECT research_date
        FROM research_snapshot
        WHERE symbol = ? AND status = 'completed'
        ORDER BY research_date DESC, id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None or not row[0]:
        return None
    completed_at = _parse_iso_datetime(str(row[0]))
    if completed_at is None:
        return None
    return completed_at.astimezone(ZoneInfo(RESEARCH_TIMEZONE)).date().isoformat()


def has_significant_change(symbol: str, paths: ProjectPaths | None = None) -> bool:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT daily_change_pct
            FROM daily_position_snapshot
            WHERE symbol = ?
            ORDER BY snapshot_date DESC, id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if row is not None and row[0] is not None and abs(float(row[0])) >= DEDUP_SIGNIFICANT_CHANGE_PCT:
            return True

        trend_rows = connection.execute(
            """
            SELECT weekly_trend
            FROM technical_snapshot
            WHERE symbol = ?
            ORDER BY snapshot_date DESC, id DESC
            LIMIT 2
            """,
            (symbol,),
        ).fetchall()
    if len(trend_rows) < 2:
        return False
    current_trend = trend_rows[0][0] or ''
    previous_trend = trend_rows[1][0] or ''
    if not current_trend or not previous_trend:
        return False
    return (previous_trend == 'up' and current_trend == 'down') or (previous_trend == 'down' and current_trend == 'up')


def should_research(symbol: str, skip_dedup: bool = False, paths: ProjectPaths | None = None) -> tuple[bool, str]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute("SELECT user_status FROM stock_master WHERE symbol = ?", (symbol,)).fetchone()
        user_status = None if row is None else str(row[0] or '')

        if user_status == 'ignored':
            return False, 'ignored'
        if skip_dedup:
            return True, 'manual_override'

        last_research_date_et = _latest_completed_research_et_date(symbol, connection)
        if last_research_date_et is None:
            return True, 'never_researched'

        days_since = (_et_today() - date.fromisoformat(last_research_date_et)).days
        if days_since > DEDUP_DAYS:
            return True, 'expired'
        if user_status == 'held' and has_significant_change(symbol, paths=paths):
            return True, 'held_significant_change'
        return False, f'reuse:{last_research_date_et}'


def _coerce_initial_score(candidate: dict[str, Any], symbol: str) -> float:
    raw_score = candidate.get('initial_score')
    if raw_score in (None, ''):
        return 0.0
    try:
        return float(raw_score)
    except (TypeError, ValueError):
        logger.warning('Invalid initial_score for %s: %r; defaulting to 0.0', symbol, raw_score)
        return 0.0


def build_research_batch(candidates: list[dict], paths: ProjectPaths | None = None) -> dict[str, list[dict[str, Any]]]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    queued_candidates: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    pending_next_batch: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []

    for candidate in candidates:
        symbol = str(candidate.get('symbol') or '').strip().upper()
        if not symbol:
            logger.warning('Skipping candidate with empty symbol: %r', candidate)
            continue
        initial_score = _coerce_initial_score(candidate, symbol)
        should_run, reason = should_research(symbol, paths=paths)
        if reason == 'ignored':
            ignored.append({'symbol': symbol})
            continue
        if not should_run and reason.startswith('reuse:'):
            reused.append({'symbol': symbol, 'last_research_date': reason.split(':', 1)[1]})
            continue
        if should_run:
            queued_candidates.append({
                'symbol': symbol,
                'initial_score': initial_score,
                'reason': reason,
            })

    queued_candidates.sort(key=lambda item: (-float(item['initial_score']), str(item['symbol'])))
    queued = queued_candidates[:MAX_DAILY_RESEARCH]
    overflow = queued_candidates[MAX_DAILY_RESEARCH:]
    pending_next_batch = [
        {'symbol': item['symbol'], 'initial_score': item['initial_score']}
        for item in overflow
    ]
    return {
        'queued': queued,
        'reused': reused,
        'pending_next_batch': pending_next_batch,
        'ignored': ignored,
    }


def increment_hit_count(symbol: str, paths: ProjectPaths | None = None) -> None:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    now = _utc_now_iso()
    normalized_symbol = str(symbol).strip().upper()
    with sqlite_connection(paths) as connection:
        row = connection.execute('SELECT symbol FROM stock_master WHERE symbol = ?', (normalized_symbol,)).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status, first_discovered_at, created_at, updated_at)
                VALUES (?, ?, 'strategy', 1, 'watching', ?, ?, ?)
                """,
                (normalized_symbol, normalized_symbol, now, now, now),
            )
            return
        connection.execute(
            """
            UPDATE stock_master
            SET hit_count = COALESCE(hit_count, 0) + 1,
                updated_at = ?
            WHERE symbol = ?
            """,
            (now, normalized_symbol),
        )


def execute_research_batch_serial(
    symbols: list[str],
    research_fn: Any,
    interval_seconds: float = RESEARCH_INTERVAL_SECONDS,
) -> list[Any]:
    results: list[Any] = []
    for index, symbol in enumerate(symbols):
        results.append(research_fn(symbol))
        if len(symbols) > 1 and index < len(symbols) - 1:
            time.sleep(interval_seconds)
    return results

def reorder_research_queue(*, paths: ProjectPaths | None = None, correlation_id: str, connection: Any | None = None) -> list[QueueTask]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    if connection is not None:
        return _reorder_research_queue_connection(connection=connection, correlation_id=correlation_id, paths=paths)
    with sqlite_connection(paths) as connection:
        return _reorder_research_queue_connection(connection=connection, correlation_id=correlation_id, paths=paths)



def _reorder_research_queue_connection(*, connection: Any, correlation_id: str, paths: ProjectPaths | None = None) -> list[QueueTask]:
    rows = connection.execute(
        "SELECT id, symbol, trigger_type, trigger_priority, status, retry_count, research_date, input_data_json FROM research_snapshot WHERE status IN ('pending','retry_pending')"
    ).fetchall()
    tasks = []
    for row in rows:
        payload = _json_text_safe(row[7])
        tasks.append(
            {
                "id": int(row[0]),
                "symbol": str(row[1]),
                "trigger_type": str(row[2]),
                "trigger_priority": str(row[3]),
                "status": str(row[4]),
                "retry_count": int(row[5]),
                "research_date": str(row[6]),
                "error_message": None,
                **payload,
            }
        )
    ordered = sorted(tasks, key=_sort_key)
    for index, task in enumerate(ordered, start=1):
        existing_payload = _json_text_safe(
            connection.execute("SELECT input_data_json FROM research_snapshot WHERE id = ?", (task["id"],)).fetchone()[0]
        )
        connection.execute(
            "UPDATE research_snapshot SET input_data_json = ? WHERE id = ?",
            (json.dumps({**existing_payload, "queue_rank": index}, ensure_ascii=False, sort_keys=True), task["id"]),
        )
    append_audit_log(
        entity_type="research_queue",
        entity_key="global",
        action="research_queue_reordered",
        correlation_id=correlation_id,
        payload={**_queue_snapshot(connection), **_daily_budget_snapshot(connection)},
        created_at=_utc_now_iso(),
        connection=connection,
    )
    _maybe_create_backlog_alert(connection=connection, correlation_id=correlation_id, paths=paths)
    return [QueueTask(**{k: task[k] for k in QueueTask.__dataclass_fields__.keys()}) for task in ordered]



def enqueue_queue_task(
    *,
    symbol: str,
    trigger_type: str,
    trigger_priority: str,
    strategy_id: str,
    correlation_id: str,
    paths: ProjectPaths | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> int:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    now = _utc_now()
    payload = {"symbol": symbol, **(extra_payload or {})}
    with sqlite_connection(paths) as connection:
        cursor = connection.execute(
            """
            INSERT INTO research_snapshot (
                symbol, research_date, trigger_type, trigger_priority,
                prompt_template_id, prompt_version, strategy_id, input_data_json,
                status, retry_count, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
            """,
            (
                symbol,
                now.isoformat(),
                trigger_type,
                trigger_priority,
                "baseline_perplexity_template",
                "v1.0",
                strategy_id,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                (now + timedelta(days=14)).isoformat(),
            ),
        )
        _reorder_research_queue_connection(connection=connection, correlation_id=correlation_id, paths=paths)
        append_audit_log(
            entity_type="research_queue",
            entity_key=f"{symbol}:{cursor.lastrowid}",
            action="research_queue_enqueued",
            correlation_id=correlation_id,
            payload={"symbol": symbol, "trigger_priority": trigger_priority, **_queue_snapshot(connection), **_daily_budget_snapshot(connection)},
            created_at=now.isoformat(),
            connection=connection,
        )
        return int(cursor.lastrowid)



def claim_next_research_task(*, paths: ProjectPaths | None = None, correlation_id: str) -> QueueTask | None:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        if int(connection.execute("SELECT COUNT(*) FROM research_snapshot WHERE status = 'in_progress'").fetchone()[0]) >= MAX_CONCURRENT_SLOTS:
            append_audit_log(
                entity_type="research_queue",
                entity_key="global",
                action="research_queue_claim_skipped_slots_full",
                correlation_id=correlation_id,
                payload={**_queue_snapshot(connection), **_daily_budget_snapshot(connection)},
                created_at=_utc_now_iso(),
                connection=connection,
            )
            return None

        budget = _daily_budget_snapshot(connection)
        if int(budget["hard_budget_remaining"]) <= 0:
            append_audit_log(
                entity_type="research_queue",
                entity_key="global",
                action="research_queue_claim_skipped_hard_budget",
                correlation_id=correlation_id,
                payload={**_queue_snapshot(connection), **budget},
                created_at=_utc_now_iso(),
                connection=connection,
            )
            return None

        rows = _reorder_research_queue_connection(connection=connection, correlation_id=correlation_id, paths=paths)
        if not rows:
            return None

        eligible_task = None
        for task in rows:
            if int(budget["soft_budget_remaining"]) <= 0 and str(task.trigger_priority) == "P2":
                continue
            eligible_task = task
            break
        if eligible_task is None:
            append_audit_log(
                entity_type="research_queue",
                entity_key="global",
                action="research_queue_claim_skipped_soft_budget",
                correlation_id=correlation_id,
                payload={**_queue_snapshot(connection), **budget},
                created_at=_utc_now_iso(),
                connection=connection,
            )
            return None

        connection.execute("UPDATE research_snapshot SET status = 'in_progress' WHERE id = ?", (eligible_task.id,))
        append_audit_log(
            entity_type="research_queue",
            entity_key=f"{eligible_task.symbol}:{eligible_task.id}",
            action="research_queue_claimed",
            correlation_id=correlation_id,
            payload={"symbol": eligible_task.symbol, **_queue_snapshot(connection), **_daily_budget_snapshot(connection)},
            created_at=_utc_now_iso(),
            connection=connection,
        )
        return QueueTask(
            id=eligible_task.id,
            symbol=eligible_task.symbol,
            trigger_type=eligible_task.trigger_type,
            trigger_priority=eligible_task.trigger_priority,
            status="in_progress",
            retry_count=eligible_task.retry_count,
            research_date=eligible_task.research_date,
        )



def mark_research_task_failed(
    *,
    task_id: int,
    error_message: str,
    correlation_id: str,
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            "SELECT symbol, trigger_priority, retry_count FROM research_snapshot WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"research task {task_id} not found")
        symbol = str(row[0])
        priority = str(row[1])
        retry_count = int(row[2]) + 1
        next_priority = priority
        next_status = "retry_pending"
        next_run_at = _utc_now()
        if retry_count == 1:
            next_run_at = _utc_now()
        elif retry_count == 2:
            next_run_at = _utc_now() + timedelta(minutes=5)
        elif retry_count == 3:
            next_run_at = _utc_now() + timedelta(minutes=30)
            if priority == "P0":
                next_priority = "P1-A"
            elif priority.startswith("P1"):
                next_priority = "P2"
        else:
            next_status = "failed"

        payload = _json_text_safe(connection.execute("SELECT input_data_json FROM research_snapshot WHERE id = ?", (task_id,)).fetchone()[0])
        payload["next_run_at"] = next_run_at.isoformat()
        payload["queue_rank"] = payload.get("queue_rank")
        connection.execute(
            "UPDATE research_snapshot SET status = ?, retry_count = ?, trigger_priority = ?, error_message = ?, input_data_json = ? WHERE id = ?",
            (next_status, retry_count, next_priority, error_message, json.dumps(payload, ensure_ascii=False, sort_keys=True), task_id),
        )
        _reorder_research_queue_connection(connection=connection, correlation_id=correlation_id, paths=paths)
        append_audit_log(
            entity_type="research_queue",
            entity_key=f"{symbol}:{task_id}",
            action="research_queue_failed",
            correlation_id=correlation_id,
            payload={
                "symbol": symbol,
                "retry_count": retry_count,
                "next_priority": next_priority,
                "next_status": next_status,
                "error_message": error_message,
                **_queue_snapshot(connection),
                **_daily_budget_snapshot(connection),
            },
            created_at=_utc_now_iso(),
            connection=connection,
        )
        return {
            "task_id": task_id,
            "symbol": symbol,
            "retry_count": retry_count,
            "next_priority": next_priority,
            "next_status": next_status,
        }



def run_daily_recovery_reorder(*, paths: ProjectPaths | None = None, correlation_id: str, as_of: str | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    effective_time = as_of or _utc_now_iso()
    with sqlite_connection(paths) as connection:
        connection.execute(
            "UPDATE research_snapshot SET trigger_priority = 'P2' WHERE status IN ('pending', 'retry_pending') AND trigger_priority = 'P2'"
        )
        ordered = _reorder_research_queue_connection(connection=connection, correlation_id=correlation_id, paths=paths)
        append_audit_log(
            entity_type="research_queue",
            entity_key="global",
            action="research_queue_daily_recovery_reordered",
            correlation_id=correlation_id,
            payload={"effective_time": effective_time, **_queue_snapshot(connection), **_daily_budget_snapshot(connection)},
            created_at=effective_time,
            connection=connection,
        )
        return {
            "effective_time": effective_time,
            "queue_depth": len(ordered),
            "budget": _daily_budget_snapshot(connection),
        }
