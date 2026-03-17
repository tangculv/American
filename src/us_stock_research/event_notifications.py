from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from contextlib import nullcontext
from typing import Any, Callable

from .alert_manager import AlertManager
from .config import ProjectPaths
from .feishu_sender import send_post
from .models.database import sqlite_connection
from .time_utils import utc_now
from .models.schema import ensure_schema

_logger = logging.getLogger(__name__)

COOLDOWN_HOURS_DEFAULT = 6
URGENT_EVENT_TYPES = {"risk_warning", "sell_reminder", "reresearch_completed", "system_failure"}
NOTIFICATION_MAX_RETRIES = 3
ACTION_LEVEL_WARNING = {"继续持有", "重点关注"}

EVENT_SPECS: dict[str, dict[str, Any]] = {
    "strategy_hit": {
        "template_name": "tpl_strategy_hit",
        "priority": "P2",
        "cooldown_hours": 12,
        "sender": "feishu_webhook",
    },
    "daily_digest": {
        "template_name": "tpl_daily_digest",
        "priority": "P3",
        "cooldown_hours": 24,
        "sender": "feishu_webhook",
    },
    "weekly_digest": {
        "template_name": "tpl_weekly_digest",
        "priority": "P3",
        "cooldown_hours": 24 * 7,
        "sender": "feishu_webhook",
    },
    "price_alert": {
        "template_name": "tpl_price_alert",
        "priority": "P2",
        "cooldown_hours": 4,
        "sender": "feishu_webhook",
    },
    "score_change_significant": {
        "template_name": "tpl_score_change_significant",
        "priority": "P2",
        "cooldown_hours": 12,
        "sender": "feishu_webhook",
    },
    "buy_signal": {
        "template_name": "tpl_buy_signal",
        "priority": "P1",
        "cooldown_hours": 12,
        "sender": "feishu_webhook",
    },
    "exit_signal": {
        "template_name": "tpl_exit_signal",
        "priority": "P1",
        "cooldown_hours": 6,
        "sender": "feishu_webhook",
    },
    "system_error": {
        "template_name": "tpl_system_error",
        "priority": "P1",
        "cooldown_hours": 1,
        "sender": "feishu_webhook",
    },
    "review_pending": {
        "template_name": "tpl_review_pending",
        "priority": "P2",
        "cooldown_hours": 24 * 7,
        "sender": "feishu_webhook",
    },
    "research_completed": {
        "template_name": "tpl_research_done",
        "priority": "P2",
        "cooldown_hours": 24,
        "sender": "feishu_webhook",
    },
    "gate_blocked": {
        "template_name": "tpl_gate_blocked",
        "priority": "P1",
        "cooldown_hours": 6,
        "sender": "feishu_webhook",
    },
    "gate_unblocked": {
        "template_name": "tpl_gate_unblocked",
        "priority": "P2",
        "cooldown_hours": 6,
        "sender": "feishu_webhook",
    },
    "daily_screening": {
        "template_name": "tpl_daily_screening",
        "priority": "P2",
        "cooldown_hours": 24,
        "sender": "feishu_webhook",
        "urgency": "normal",
    },
    "research_completed_v2": {
        "template_name": "tpl_research_completed",
        "priority": "P2",
        "cooldown_hours": 24,
        "sender": "feishu_webhook",
        "urgency": "normal",
    },
    "buy_confirmation": {
        "template_name": "tpl_buy_confirmation",
        "priority": "P2",
        "cooldown_hours": 0,
        "sender": "feishu_webhook",
        "urgency": "normal",
    },
    "risk_warning": {
        "template_name": "tpl_risk_warning",
        "priority": "P1",
        "cooldown_hours": 6,
        "sender": "feishu_webhook",
        "urgency": "urgent",
    },
    "sell_reminder": {
        "template_name": "tpl_sell_reminder",
        "priority": "P1",
        "cooldown_hours": 6,
        "sender": "feishu_webhook",
        "urgency": "urgent",
    },
    "reresearch_completed": {
        "template_name": "tpl_reresearch_completed",
        "priority": "P1",
        "cooldown_hours": 0,
        "sender": "feishu_webhook",
        "urgency": "urgent",
    },
    "system_failure": {
        "template_name": "tpl_system_failure",
        "priority": "P0",
        "cooldown_hours": 1,
        "sender": "feishu_webhook",
        "urgency": "critical",
    },
}


def _utc_now():
    return utc_now()


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _event_title(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("event_type") or "")
    symbol = str(payload.get("symbol") or "").strip()
    company = str(payload.get("company_name") or "").strip()
    label = company or symbol

    titles = {
        "strategy_hit":        f"📡 每日筛选命中候选股",
        "research_completed":  f"📋 研究完成 · {label}" if label else "📋 研究完成",
        "risk_warning":        f"⚠️ 持仓预警 · {label}" if label else "⚠️ 持仓预警",
        "sell_reminder":       f"🔴 卖出提醒 · {label}" if label else "🔴 卖出提醒",
        "buy_confirmation":    f"✅ 买入确认 · {label}" if label else "✅ 买入确认",
        "daily_screening":     "📊 今日研究汇总",
        "reresearch_completed": f"🔄 重研究完成 · {label}" if label else "🔄 重研究完成",
        "system_failure":      "🚨 系统异常",
        "system_error":        "⚠️ 系统错误",
    }
    return titles.get(event_type) or str(payload.get("summary") or event_type or "事件通知")


def _fmt_symbols(value: Any) -> str:
    """Format a list of symbols as a readable string."""
    if isinstance(value, list):
        return "、".join(str(v) for v in value[:8]) + ("…" if len(value) > 8 else "")
    return str(value)


def _event_lines(payload: dict[str, Any]) -> list[str]:
    event_type = str(payload.get("event_type") or "")
    facts = dict(payload.get("facts") or {})
    symbol = str(payload.get("symbol") or "").strip()
    company = str(payload.get("company_name") or "").strip()
    label = f"{symbol}（{company}）" if company and company != symbol else symbol

    if event_type == "strategy_hit":
        strategy = str(facts.get("strategy_display_name") or facts.get("strategy_name") or "筛选策略")
        count = facts.get("screened_count") or facts.get("stockCount") or 0
        top = facts.get("top_symbols") or []
        lines = [f"策略：{strategy}"]
        lines.append(f"命中数量：{count} 只")
        if top:
            lines.append(f"候选股：{_fmt_symbols(top)}")
        lines.append("建议：运行 research 命令查看研究报告")
        return lines

    if event_type == "research_completed":
        conclusion = str(facts.get("overall_conclusion") or "")
        quality = str(facts.get("quality_level") or "")
        doc_url = str(facts.get("doc_url") or "")
        lines = [f"股票：{label}"] if label else []
        if conclusion:
            lines.append(f"研究结论：{conclusion}")
        if quality and quality != "pass":
            lines.append(f"报告质量：{quality}")
        if doc_url:
            lines.append(f"飞书文档：{doc_url}")
        return lines or [str(payload.get("summary") or "研究完成")]

    if event_type in ("risk_warning", "sell_reminder"):
        signals = facts.get("signals") or []
        top_action = str(facts.get("top_action") or "")
        signal_names = facts.get("signal_names") or []
        lines = [f"股票：{label}"] if label else []
        if top_action:
            lines.append(f"建议动作：{top_action}")
        if signal_names:
            lines.append(f"触发信号：{'、'.join(str(s) for s in signal_names)}")
        elif signals:
            lines.append(f"触发信号数：{len(signals)} 个")
        for key, cn in [("daily_change_pct", "今日涨跌"), ("return_pct", "持仓收益率"), ("price", "当前价格")]:
            val = facts.get(key)
            if val is not None:
                lines.append(f"{cn}：{val}%") if "pct" in key else lines.append(f"{cn}：${val}")
        return lines or [str(payload.get("summary") or event_type)]

    if event_type == "buy_confirmation":
        price = facts.get("price")
        quantity = facts.get("quantity")
        trade_date = facts.get("trade_date") or ""
        reason = str(facts.get("reason") or "")
        lines = [f"股票：{label}"] if label else []
        if quantity and price:
            lines.append(f"买入：{quantity} 股 @ ${price}")
        if trade_date:
            lines.append(f"日期：{trade_date}")
        if reason:
            lines.append(f"备注：{reason}")
        return lines or [str(payload.get("summary") or "买入确认")]

    if event_type == "daily_screening":
        batch = facts.get("batch_results") or []
        researched = [b for b in batch if b.get("status") in ("success", "fallback")]
        reused = [b for b in batch if b.get("status") == "reused"]
        lines = []
        if researched:
            lines.append(f"新研究：{len(researched)} 只 — " + "、".join(b.get("symbol","") for b in researched[:5]))
        if reused:
            lines.append(f"复用历史：{len(reused)} 只")
        total = facts.get("candidate_count") or len(batch)
        if total:
            lines.append(f"本次候选总数：{total}")
        return lines or [str(payload.get("summary") or "今日汇总")]

    # fallback: generic readable format
    lines = [str(payload.get("summary") or event_type)]
    for key, value in facts.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"- {key}: {_fmt_symbols(value) if isinstance(value, list) else value}")
    return lines


def _default_dedupe_key(event_type: str, symbol: str | None, correlation_id: str, payload: dict[str, Any]) -> str:
    if event_type == "system_error":
        error_type = str(dict(payload.get("facts") or {}).get("error_type") or "unknown")
        return f"{event_type}:{error_type}:{correlation_id}"
    return f"{event_type}:{symbol or 'GLOBAL'}:{correlation_id}"


def build_event_payload(
    *,
    event_type: str,
    symbol: str | None,
    summary: str,
    correlation_id: str,
    facts: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    company_name: str | None = None,
    template_version: str = "v1",
) -> dict[str, Any]:
    spec = EVENT_SPECS[event_type]
    return {
        "template_name": spec["template_name"],
        "template_version": template_version,
        "event_type": event_type,
        "priority": spec["priority"],
        "symbol": symbol,
        "company_name": company_name or "",
        "triggered_at": _utc_now_iso(),
        "correlation_id": correlation_id,
        "summary": summary,
        "facts": facts or {},
        "actions": actions or [],
        "meta": meta or {},
    }


def create_notification_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str,
    symbol: str | None = None,
    dedupe_key: str | None = None,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    if connection is None:
        ensure_schema(paths)
    spec = EVENT_SPECS[event_type]
    payload = dict(payload)
    symbol = symbol or str(payload.get("symbol") or "").strip() or None
    dedupe = dedupe_key or _default_dedupe_key(event_type, symbol, correlation_id, payload)
    now = _utc_now()
    cooldown_until = (now + timedelta(hours=int(spec["cooldown_hours"]))).isoformat()
    message = "\n".join(_event_lines(payload))

    connection_manager = nullcontext(connection) if connection is not None else sqlite_connection(paths)
    with connection_manager as active_connection:
        existing = active_connection.execute(
            "SELECT id, send_status, cooldown_until, payload_json FROM notification_event WHERE dedupe_key = ?",
            (dedupe,),
        ).fetchone()
        if existing is not None:
            return {
                "created": False,
                "id": int(existing[0]),
                "send_status": str(existing[1]),
                "cooldown_until": existing[2],
                "payload": json.loads(existing[3] or "{}"),
            }

        cursor = active_connection.execute(
            """
            INSERT INTO notification_event (
                event_type,
                symbol,
                priority,
                template_name,
                template_version,
                payload_json,
                message_content,
                dedupe_key,
                correlation_id,
                sender,
                cooldown_until,
                send_status,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                event_type,
                symbol,
                spec["priority"],
                payload["template_name"],
                payload.get("template_version", "v1"),
                _json_text(payload),
                message,
                dedupe,
                correlation_id,
                spec["sender"],
                cooldown_until,
                now.isoformat(),
            ),
        )
        return {
            "created": True,
            "id": int(cursor.lastrowid),
            "send_status": "pending",
            "cooldown_until": cooldown_until,
            "payload": payload,
        }


def should_send_notification(
    event_type: str,
    symbol: str | None,
    is_upgrade: bool = False,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> tuple[bool, str]:
    paths = paths or ProjectPaths()
    spec = EVENT_SPECS[event_type]
    cooldown_hours = int(spec.get("cooldown_hours", COOLDOWN_HOURS_DEFAULT))
    if cooldown_hours == 0:
        return True, "ok"

    urgency = str(spec.get("urgency") or "normal")
    if is_upgrade and event_type in URGENT_EVENT_TYPES:
        return True, "ok"

    if connection is None:
        ensure_schema(paths)
    connection_manager = nullcontext(connection) if connection is not None else sqlite_connection(paths)
    with connection_manager as active_connection:
        row = active_connection.execute(
            """
            SELECT sent_at
            FROM notification_event
            WHERE event_type = ? AND ((symbol IS NULL AND ? IS NULL) OR symbol = ?) AND send_status = 'sent' AND sent_at IS NOT NULL
            ORDER BY sent_at DESC, id DESC
            LIMIT 1
            """,
            (event_type, symbol, symbol),
        ).fetchone()
    if row is None or not row[0]:
        return True, "ok"

    try:
        sent_at = str(row[0]).replace("Z", "+00:00")
        last_sent = datetime.fromisoformat(sent_at)
    except (ValueError, TypeError):
        _logger.warning("Invalid sent_at format for %s/%s: %r; treating as no history", event_type, symbol, row[0])
        return True, "ok"
    now = _utc_now()
    if last_sent.tzinfo is None and now.tzinfo is not None:
        last_sent = last_sent.replace(tzinfo=now.tzinfo)
    elif last_sent.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=last_sent.tzinfo)
    if (now - last_sent) < timedelta(hours=cooldown_hours):
        return False, "cooldown"
    return True, "ok"


def create_alert_notification(
    symbol: str,
    merged: dict,
    event_type: str,
    correlation_id: str,
    is_upgrade: bool = False,
    paths: ProjectPaths | None = None,
) -> dict:
    should_send, reason = should_send_notification(event_type, symbol, is_upgrade=is_upgrade, paths=paths)
    if not should_send:
        return {"created": False, "reason": reason}

    payload = build_event_payload(
        event_type=event_type,
        symbol=symbol,
        summary=f"[{symbol}] {merged.get('top_action')}｜{merged.get('signal_count')}条信号",
        correlation_id=correlation_id,
        facts={
            "top_action": merged.get("top_action"),
            "signals": list(merged.get("signals") or []),
            "signal_count": int(merged.get("signal_count") or 0),
        },
    )
    return create_notification_event(
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
        symbol=symbol,
        paths=paths,
    )


def handle_system_failure(
    failure_type: str,
    detail: str,
    correlation_id: str,
    paths: ProjectPaths | None = None,
) -> dict:
    should_send, reason = should_send_notification("system_failure", None, paths=paths)
    if not should_send:
        return {"created": False, "reason": reason}

    payload = build_event_payload(
        event_type="system_failure",
        symbol=None,
        summary=detail,
        correlation_id=correlation_id,
        facts={"failure_type": failure_type, "detail": detail},
    )
    return create_notification_event(
        event_type="system_failure",
        payload=payload,
        correlation_id=correlation_id,
        symbol=None,
        dedupe_key=f"system_failure:{failure_type}:{correlation_id}",
        paths=paths,
    )


def build_daily_summary_notification(
    batch_results: list[dict],
    correlation_id: str,
    paths: ProjectPaths | None = None,
) -> dict:
    if not batch_results:
        return handle_system_failure("task_not_started", "定时任务未启动或无候选股", correlation_id, paths=paths)

    icon_map = {
        "success": "✅",
        "fallback": "⚠️",
        "failed": "❌",
        "reused": "🔄",
        "pending": "⏳",
    }
    total = len(batch_results)
    lines = [f"今日命中 {total} 只股票："]
    all_failed = all(str(item.get("status")) == "failed" for item in batch_results)
    for item in batch_results:
        status = str(item.get("status") or "pending")
        icon = icon_map.get(status)
        if icon is None:
            _logger.warning("Unknown batch result status %r for symbol %s; defaulting to ⏳", status, item.get("symbol"))
            icon = "⏳"
        symbol = str(item.get("symbol") or "")
        summary = str(item.get("summary") or "")
        doc_url = item.get("doc_url")
        reuse_date = item.get("reuse_date")
        if status in {"success", "fallback"} and doc_url:
            lines.append(f"{icon} {symbol}: {summary} → [查看报告]({doc_url})")
        elif status == "reused" and reuse_date:
            lines.append(f"{icon} {symbol}: 已研究（复用 {reuse_date} 研究）")
        elif status == "pending":
            lines.append(f"{icon} {symbol}: 待研究，已入候选池")
        elif status == "failed":
            lines.append(f"{icon} {symbol}: 研究失败")
        else:
            lines.append(f"{icon} {symbol}: {summary}")

    summary = "\n".join(lines)
    if all_failed:
        summary = f"今日命中{total}只股票：全批次失败\n" + "\n".join(lines[1:])

    payload = build_event_payload(
        event_type="daily_screening",
        symbol=None,
        summary=summary,
        correlation_id=correlation_id,
        facts={"total": total, "results": batch_results, "all_failed": all_failed},
    )
    return create_notification_event(
        event_type="daily_screening",
        payload=payload,
        correlation_id=correlation_id,
        symbol=None,
        paths=paths,
    )


def send_alert_notifications_for_symbol(
    symbol: str,
    alert_manager: AlertManager,
    webhook_url: str,
    correlation_id: str,
    is_upgrade: bool = False,
    paths: ProjectPaths | None = None,
) -> dict:
    merged = alert_manager.merge_for_notification(symbol)
    if merged is None:
        return {"sent": False, "reason": "no_active_signals"}

    event_type = "risk_warning" if merged.get("top_action") in ACTION_LEVEL_WARNING else "sell_reminder"
    created = create_alert_notification(
        symbol=symbol,
        merged=merged,
        event_type=event_type,
        correlation_id=correlation_id,
        is_upgrade=is_upgrade,
        paths=paths,
    )
    if not created.get("created"):
        return {"sent": False, "reason": created.get("reason", "cooldown"), "created": False}

    sent = send_notification_event(
        notification_id=int(created["id"]),
        webhook_url=webhook_url,
        paths=paths,
        sender=send_post,
    )
    return {"sent": bool(sent.get("sent")), "event_type": event_type, "notification_id": created["id"]}


def send_notification_event(
    *,
    notification_id: int,
    webhook_url: str,
    paths: ProjectPaths | None = None,
    sender: Callable[[str, list[str], str], dict[str, Any]] = send_post,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            "SELECT payload_json, send_status FROM notification_event WHERE id = ?",
            (notification_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"notification_event {notification_id} not found")
        payload = json.loads(row[0] or "{}")
        if str(row[1]) == "sent":
            return {"sent": False, "reason": "already_sent", "payload": payload}

        title = _event_title(payload)
        lines = _event_lines(payload)
        last_error: str | None = None
        for attempt in range(1, NOTIFICATION_MAX_RETRIES + 1):
            try:
                response = sender(title, lines, webhook_url)
                connection.execute(
                    "UPDATE notification_event SET send_status = 'sent', sent_at = ?, error_message = NULL WHERE id = ?",
                    (_utc_now_iso(), notification_id),
                )
                return {"sent": True, "payload": payload, "response": response, "attempts": attempt}
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt < NOTIFICATION_MAX_RETRIES:
                    time.sleep(attempt * 2)
                    continue

        connection.execute(
            "UPDATE notification_event SET send_status = 'failed', error_message = ? WHERE id = ?",
            (last_error, notification_id),
        )
        return {"sent": False, "payload": payload, "reason": "send_failed", "error_message": last_error, "attempts": NOTIFICATION_MAX_RETRIES}


def flush_pending_notifications(
    paths: ProjectPaths | None = None,
    sender: Callable[[str, list[str], str], dict[str, Any]] = send_post,
) -> dict[str, Any]:
    """Send all pending notification_event records via Feishu webhook.

    Called at the end of screen / run / research CLI commands so that
    notifications created during the pipeline are actually dispatched.
    Returns a summary dict with sent_count and failed_count.
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook_url:
        _logger.warning("FEISHU_WEBHOOK_URL not set — skipping notification flush")
        return {"sent_count": 0, "failed_count": 0, "skipped": True}

    paths = paths or ProjectPaths()
    ensure_schema(paths)
    with sqlite_connection(paths) as conn:
        rows = conn.execute(
            "SELECT id FROM notification_event WHERE send_status = 'pending' ORDER BY id ASC"
        ).fetchall()

    sent_count = 0
    failed_count = 0
    for (notification_id,) in rows:
        result = send_notification_event(
            notification_id=notification_id,
            webhook_url=webhook_url,
            paths=paths,
            sender=sender,
        )
        if result.get("sent"):
            sent_count += 1
        elif result.get("reason") != "already_sent":
            failed_count += 1

    return {"sent_count": sent_count, "failed_count": failed_count}
