from __future__ import annotations

import json
from ..time_utils import utc_now_iso
from typing import Any

from ..config import ProjectPaths
from ..utils.validators import ensure_json_object, ensure_non_empty_string
from .database import sqlite_connection


AUDIT_LOG_INSERT = """
INSERT INTO audit_log (
    entity_type,
    entity_key,
    action,
    previous_state,
    new_state,
    correlation_id,
    payload_json,
    created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def append_audit_log(
    *,
    entity_type: str,
    entity_key: str,
    action: str,
    correlation_id: str,
    payload: dict[str, Any] | None = None,
    previous_state: str = "",
    new_state: str = "",
    created_at: str | None = None,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> None:
    payload_json = json.dumps(ensure_json_object(payload, "payload"), ensure_ascii=False, sort_keys=True)
    timestamp = created_at or utc_now_iso()
    params = (
        ensure_non_empty_string(entity_type, "entity_type"),
        ensure_non_empty_string(entity_key, "entity_key"),
        ensure_non_empty_string(action, "action"),
        str(previous_state or ""),
        str(new_state or ""),
        ensure_non_empty_string(correlation_id, "correlation_id"),
        payload_json,
        timestamp,
    )
    if connection is not None:
        connection.execute(AUDIT_LOG_INSERT, params)
        return

    with sqlite_connection(paths) as db_connection:
        db_connection.execute(AUDIT_LOG_INSERT, params)
