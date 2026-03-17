from __future__ import annotations

# FROZEN: 复盘审批功能已降级到后续版本（PRD v3）
# 本文件保留但不再被主流程调用

import json
from .time_utils import utc_now_iso
from typing import Any

from .config import ProjectPaths
from .event_notifications import build_event_payload, create_notification_event
from .models.audit import append_audit_log
from .models.database import sqlite_connection
from .models.schema import ensure_schema


ALLOWED_SUGGESTED_CHANGE_STATUS = {"pending", "approved", "rejected"}


def _utc_now_iso() -> str:
    return utc_now_iso()


def list_pending_review_changes(*, paths: ProjectPaths | None = None) -> list[dict[str, Any]]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        rows = connection.execute(
            """
            SELECT id, symbol, change_type, target_object, reason, status, proposed_at, approved_at
            FROM suggested_change
            WHERE status = 'pending'
            ORDER BY proposed_at DESC, id DESC
            """
        ).fetchall()
        return [
            {
                "id": int(row[0]),
                "symbol": str(row[1] or ""),
                "change_type": str(row[2] or ""),
                "target_object": str(row[3] or ""),
                "reason": str(row[4] or ""),
                "status": str(row[5] or "pending"),
                "proposed_at": str(row[6] or ""),
                "approved_at": str(row[7] or ""),
            }
            for row in rows
        ]


def create_review_pending_notification(
    *,
    symbol: str,
    suggested_change_id: int,
    summary: str,
    correlation_id: str,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> dict[str, Any]:
    payload = build_event_payload(
        event_type="review_pending",
        symbol=symbol,
        summary=summary,
        correlation_id=correlation_id,
        facts={
            "suggested_change_id": suggested_change_id,
            "symbol": symbol,
        },
        actions=[
            {"action": "approve_review_change", "label": "审批变更"},
            {"action": "view_review_log", "label": "查看复盘"},
        ],
    )
    return create_notification_event(
        event_type="review_pending",
        payload=payload,
        correlation_id=correlation_id,
        symbol=symbol,
        dedupe_key=f"review_pending:{symbol}:{suggested_change_id}",
        paths=paths,
        connection=connection,
    )


def update_suggested_change_status(
    *,
    change_id: int,
    decision: str,
    reviewer: str = "system",
    note: str = "",
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")

    paths = paths or ProjectPaths()
    ensure_schema(paths)
    now = _utc_now_iso()
    correlation_id = f"review-decision-{change_id}-{now}"

    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT id, symbol, change_type, target_object, before_snapshot_json, after_snapshot_json, reason, status, proposed_at
            FROM suggested_change
            WHERE id = ?
            """,
            (change_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"suggested_change {change_id} not found")
        current_status = str(row[7] or "pending")
        if current_status not in ALLOWED_SUGGESTED_CHANGE_STATUS:
            raise ValueError(f"unsupported suggested_change status: {current_status}")
        if current_status != "pending":
            return {
                "change_id": change_id,
                "status": current_status,
                "symbol": str(row[1] or ""),
                "changed": False,
            }

        approved_at = now if normalized_decision == "approved" else None
        connection.execute(
            "UPDATE suggested_change SET status = ?, approved_at = ? WHERE id = ?",
            (normalized_decision, approved_at, change_id),
        )
        payload = {
            "change_id": change_id,
            "symbol": str(row[1] or ""),
            "change_type": str(row[2] or ""),
            "target_object": str(row[3] or ""),
            "decision": normalized_decision,
            "reviewer": reviewer,
            "note": note,
            "reason": str(row[6] or ""),
            "proposed_at": str(row[8] or ""),
            "before": json.loads(row[4] or "{}"),
            "after": json.loads(row[5] or "{}"),
        }
        append_audit_log(
            entity_type="suggested_change",
            entity_key=str(change_id),
            action=f"suggested_change_{normalized_decision}",
            previous_state="pending",
            new_state=normalized_decision,
            correlation_id=correlation_id,
            payload=payload,
            connection=connection,
        )
        return {
            "change_id": change_id,
            "status": normalized_decision,
            "symbol": str(row[1] or ""),
            "changed": True,
            "approved_at": approved_at,
        }
