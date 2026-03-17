from __future__ import annotations

# FROZEN: 旧版生命周期状态机已降级为兼容保留（PRD v3）
# 本文件保留但不再作为主流程状态模型

from typing import Any

from ..config import ProjectPaths
from ..models import append_audit_log
from ..utils.validators import ensure_non_empty_string, ensure_state_value

PHASE1_STATES = (
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
)

TERMINAL_STATES = ("rejected", "archived")

TRANSITION_RULES: dict[str, set[str]] = {
    "discovered": {"shortlisted", "rejected"},
    "shortlisted": {"queued_for_research"},
    "rejected": {"discovered"},
    "queued_for_research": {"researched"},
    "researched": {"scored"},
    "scored": {"waiting_for_setup", "buy_ready"},
    "waiting_for_setup": {"buy_ready"},
    "buy_ready": {"holding"},
    "holding": {"exit_watch"},
    "exit_watch": {"exited"},
    "exited": {"archived"},
    "archived": {"discovered"},
}


def validate_transition(from_state: str, to_state: str) -> tuple[bool, str]:
    current_state = ensure_state_value(from_state, "from_state")
    next_state = ensure_state_value(to_state, "to_state")
    if current_state == next_state:
        return False, f"transition {current_state} -> {next_state} is not allowed"
    allowed_targets = TRANSITION_RULES[current_state]
    if next_state in allowed_targets:
        return True, "ok"
    allowed = ", ".join(sorted(allowed_targets))
    return False, f"transition {current_state} -> {next_state} is not allowed; allowed targets: {allowed}"


def transition_stock_state(
    *,
    symbol: str,
    from_state: str,
    to_state: str,
    trigger_source: str,
    correlation_id: str,
    paths: ProjectPaths | None = None,
    payload: dict[str, Any] | None = None,
    connection: Any | None = None,
) -> dict[str, Any]:
    ok, reason = validate_transition(from_state, to_state)
    if not ok:
        raise ValueError(reason)

    stock_symbol = ensure_non_empty_string(symbol, "symbol")
    trigger = ensure_non_empty_string(trigger_source, "trigger_source")
    append_audit_log(
        entity_type="stock",
        entity_key=stock_symbol,
        action="state_transition",
        previous_state=from_state,
        new_state=to_state,
        correlation_id=correlation_id,
        payload={
            "symbol": stock_symbol,
            "trigger_source": trigger,
            **(payload or {}),
        },
        paths=paths,
        connection=connection,
    )
    return {
        "symbol": stock_symbol,
        "from_state": from_state,
        "to_state": to_state,
        "trigger_source": trigger,
        "correlation_id": correlation_id,
    }
