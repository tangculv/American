from __future__ import annotations

import json
from datetime import datetime
from .time_utils import utc_now_iso
from typing import Any

from .config import ProjectPaths
from .lifecycle import transition_stock_state
from .models.audit import append_audit_log
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .review_workflow import create_review_pending_notification


def _utc_now_iso() -> str:
    return utc_now_iso()


def _holding_metrics(connection: Any, symbol: str, exit_price: float | None = None) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT trade_type, trade_date, price, quantity FROM trade_log WHERE symbol = ? ORDER BY trade_date ASC, id ASC",
        (symbol,),
    ).fetchall()
    total_buy_qty = 0.0
    total_buy_cost = 0.0
    first_buy_date = None
    sold_qty = 0.0
    for trade_type, trade_date, price, quantity in rows:
        if trade_type == 'buy':
            total_buy_qty += float(quantity)
            total_buy_cost += float(price) * float(quantity)
            if first_buy_date is None:
                first_buy_date = str(trade_date)
        elif trade_type == 'sell':
            sold_qty += float(quantity)
    avg_buy_price = (total_buy_cost / total_buy_qty) if total_buy_qty else None
    holding_days = None
    if first_buy_date:
        try:
            holding_days = (datetime.fromisoformat(_utc_now_iso()) - datetime.fromisoformat(first_buy_date)).days
        except ValueError:
            holding_days = None
    return_pct = None
    if avg_buy_price and exit_price is not None:
        return_pct = (float(exit_price) - avg_buy_price) / avg_buy_price * 100
    return {
        'avg_buy_price': avg_buy_price,
        'holding_days': holding_days,
        'open_quantity': total_buy_qty - sold_qty,
        'return_pct': return_pct,
    }


def record_buy(
    *,
    symbol: str,
    price: float,
    quantity: float,
    notes: str = '',
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    now = _utc_now_iso()
    with sqlite_connection(paths) as connection:
        transition_stock_state(
            symbol=symbol,
            from_state='buy_ready',
            to_state='holding',
            trigger_source='manual_buy',
            correlation_id=f'buy-{symbol}-{now}',
            payload={'price': price, 'quantity': quantity, 'notes': notes},
            connection=connection,
        )
        connection.execute(
            """
            INSERT INTO trade_log (symbol, trade_type, trade_date, price, quantity, fees, notes)
            VALUES (?, 'buy', ?, ?, ?, 0, ?)
            """,
            (symbol, now, float(price), float(quantity), notes),
        )
        connection.execute(
            """
            UPDATE stock_master
            SET lifecycle_state = 'holding',
                current_state = 'holding',
                lifecycle_changed_at = ?,
                current_price = COALESCE(current_price, ?),
                latest_price = COALESCE(latest_price, ?),
                updated_at = ?
            WHERE symbol = ?
            """,
            (now, float(price), float(price), now, symbol),
        )


def record_sell(
    *,
    symbol: str,
    price: float,
    quantity: float,
    notes: str = '',
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    now = _utc_now_iso()
    with sqlite_connection(paths) as connection:
        transition_stock_state(
            symbol=symbol,
            from_state='exit_watch',
            to_state='exited',
            trigger_source='manual_sell',
            correlation_id=f'sell-{symbol}-{now}',
            payload={'price': price, 'quantity': quantity, 'notes': notes},
            connection=connection,
        )
        connection.execute(
            """
            INSERT INTO trade_log (symbol, trade_type, trade_date, price, quantity, fees, notes)
            VALUES (?, 'sell', ?, ?, ?, 0, ?)
            """,
            (symbol, now, float(price), float(quantity), notes),
        )
        metrics = _holding_metrics(connection, symbol, float(price))
        connection.execute(
            """
            UPDATE stock_master
            SET lifecycle_state = 'exited',
                current_state = 'exited',
                lifecycle_changed_at = ?,
                current_price = ?,
                latest_price = ?,
                updated_at = ?
            WHERE symbol = ?
            """,
            (now, float(price), float(price), now, symbol),
        )
        append_audit_log(
            entity_type='trade',
            entity_key=symbol,
            action='sell_recorded',
            previous_state='exit_watch',
            new_state='exited',
            correlation_id=f'sell-{symbol}-{now}',
            payload=metrics,
            connection=connection,
        )


def trigger_exit_watch(
    *,
    symbol: str,
    reason: str,
    context: dict[str, Any] | None = None,
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    now = _utc_now_iso()
    with sqlite_connection(paths) as connection:
        current = connection.execute("SELECT lifecycle_state FROM stock_master WHERE symbol = ?", (symbol,)).fetchone()
        if current is None:
            raise ValueError(f'symbol not found: {symbol}')
        if str(current[0]) != 'holding':
            return
        transition_stock_state(
            symbol=symbol,
            from_state='holding',
            to_state='exit_watch',
            trigger_source='exit_rule',
            correlation_id=f'exit-{symbol}-{now}',
            payload={'reason': reason, 'context': context or {}},
            connection=connection,
        )
        connection.execute(
            """
            INSERT INTO alert_state (symbol, alert_type, alert_level, status, context_json, triggered_at)
            VALUES (?, 'exit_watch', 'P1', 'open', ?, ?)
            """,
            (symbol, json.dumps({'reason': reason, **(context or {})}, ensure_ascii=False, sort_keys=True), now),
        )
        connection.execute(
            """
            UPDATE stock_master
            SET lifecycle_state = 'exit_watch',
                current_state = 'exit_watch',
                lifecycle_changed_at = ?,
                updated_at = ?
            WHERE symbol = ?
            """,
            (now, now, symbol),
        )


def archive_after_review(
    *,
    symbol: str,
    summary: str,
    outcome: str,
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    now = _utc_now_iso()
    with sqlite_connection(paths) as connection:
        transition_stock_state(
            symbol=symbol,
            from_state='exited',
            to_state='archived',
            trigger_source='review_complete',
            correlation_id=f'review-{symbol}-{now}',
            payload={'summary': summary, 'outcome': outcome},
            connection=connection,
        )
        metrics = _holding_metrics(connection, symbol)
        connection.execute(
            """
            INSERT INTO review_log (symbol, review_type, review_date, summary, outcome, payload_json)
            VALUES (?, 'post_exit', ?, ?, ?, ?)
            """,
            (symbol, now, summary, outcome, json.dumps(metrics, ensure_ascii=False, sort_keys=True)),
        )
        cursor = connection.execute(
            """
            INSERT INTO suggested_change (
                symbol, change_type, target_object, before_snapshot_json, after_snapshot_json, reason, status, proposed_at
            ) VALUES (?, 'review_suggestion', 'strategy_config', ?, ?, ?, 'pending', ?)
            """,
            (
                symbol,
                json.dumps({'outcome': outcome}, ensure_ascii=False, sort_keys=True),
                json.dumps({'proposed_action': 'manual_review'}, ensure_ascii=False, sort_keys=True),
                summary,
                now,
            ),
        )
        create_review_pending_notification(
            symbol=symbol,
            suggested_change_id=int(cursor.lastrowid),
            summary=f"{symbol} 复盘待审批",
            correlation_id=f'review-{symbol}-{now}',
            paths=paths,
            connection=connection,
        )
        connection.execute(
            """
            UPDATE stock_master
            SET lifecycle_state = 'archived',
                current_state = 'archived',
                lifecycle_changed_at = ?,
                updated_at = ?,
                archive_snapshot_json = json_object(
                    'archive_reason', 'review_completed',
                    'archived_at', ?,
                    'pre_archive_state', 'exited',
                    'last_price', current_price,
                    'holding_days', ?,
                    'total_return_pct', ?
                )
            WHERE symbol = ?
            """,
            (now, now, now, metrics.get('holding_days'), metrics.get('return_pct'), symbol),
        )
        append_audit_log(
            entity_type='review',
            entity_key=symbol,
            action='archived_after_review',
            previous_state='exited',
            new_state='archived',
            correlation_id=f'review-{symbol}-{now}',
            payload={'summary': summary, 'outcome': outcome},
            connection=connection,
        )
