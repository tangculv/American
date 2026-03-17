from __future__ import annotations

import json
from typing import Any


VALID_PHASE1_STATES = {
    "discovered",
    "shortlisted",
    "rejected",
    "queued_for_research",
    "researched",
    "scored",
    "waiting_for_setup",
    "buy_ready",
    "holding",
    "exit_watch",
    "exited",
    "archived",
}


def ensure_non_empty_string(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def ensure_state_value(value: Any, field_name: str = "state") -> str:
    state = ensure_non_empty_string(value, field_name)
    if state not in VALID_PHASE1_STATES:
        raise ValueError(f"{field_name} must be one of: {', '.join(sorted(VALID_PHASE1_STATES))}")
    return state


def ensure_json_object(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        json.dumps(value, ensure_ascii=False)
        return value
    raise ValueError(f"{field_name} must be a JSON object")
