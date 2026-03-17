from __future__ import annotations

from datetime import datetime
from typing import Any

from .alert_engine import Signal
from .config import ProjectPaths
from .models.database import sqlite_connection
from .models.schema import ensure_schema

VALID_ALERT_STATUSES = [
    "triggered",
    "notified",
    "acknowledged",
    "resolved",
    "expired",
    "historical_reached",
    "upgraded",
]

ACTIVE_STATUSES = ("triggered", "notified", "acknowledged")
TERMINAL_STATUSES = ("resolved", "expired", "historical_reached", "upgraded")

ACTION_PRIORITY = {
    "继续持有": 1,
    "重点关注": 2,
    "考虑减仓": 3,
    "考虑止盈": 4,
    "考虑止损": 5,
    "考虑清仓": 6,
}

PRICE_BASED_SIGNALS = ["目标价达成", "收益率达标", "技术顶部信号"]
CONDITION_BASED_SIGNALS = ["止损触发", "失效条件触发", "持有逻辑失效"]
EXPIRY_TRADING_DAYS = 3


def get_active_alerts(
    symbol: str,
    status: str | None = None,
    paths: ProjectPaths | None = None,
) -> list[dict[str, Any]]:
    ensure_schema(paths)
    query = """
        SELECT id, symbol, signal_type, signal_level, action, status,
               trigger_value, trigger_threshold, detail, triggered_at,
               notified_at, acknowledged_at, resolved_at, expired_at, upgrade_from_id
        FROM alert_event
        WHERE symbol = ?
    """
    params: list[Any] = [symbol]
    if status is None:
        query += " AND status NOT IN (?, ?, ?, ?)"
        params.extend(TERMINAL_STATUSES)
    else:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id ASC"

    with sqlite_connection(paths) as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def create_alert(
    symbol: str,
    signal: Signal,
    *,
    upgrade_from_id: int | None = None,
    paths: ProjectPaths | None = None,
) -> int:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        cursor = connection.execute(
            """
            INSERT INTO alert_event (
                symbol, signal_type, signal_level, action, status,
                trigger_value, trigger_threshold, detail, triggered_at, upgrade_from_id
            ) VALUES (?, ?, ?, ?, 'triggered', ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                symbol,
                signal.type,
                signal.level,
                signal.action,
                signal.value,
                signal.threshold,
                signal.detail,
                upgrade_from_id,
            ),
        )
        return int(cursor.lastrowid)


def update_alert_status(
    alert_id: int,
    new_status: str,
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    timestamp_column = {
        "acknowledged": "acknowledged_at",
        "resolved": "resolved_at",
        "expired": "expired_at",
    }.get(new_status)

    with sqlite_connection(paths) as connection:
        connection.execute(
            "UPDATE alert_event SET status = ? WHERE id = ?",
            (new_status, alert_id),
        )
        if timestamp_column is not None:
            connection.execute(
                f"UPDATE alert_event SET {timestamp_column} = COALESCE({timestamp_column}, CURRENT_TIMESTAMP) WHERE id = ?",
                (alert_id,),
            )


def close_all_active_alerts(symbol: str, paths: ProjectPaths | None = None) -> None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        connection.execute(
            """
            UPDATE alert_event
            SET status = 'resolved', resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP)
            WHERE symbol = ? AND status NOT IN (?, ?, ?, ?)
            """,
            (symbol, *TERMINAL_STATUSES),
        )


class AlertManager:
    def __init__(self, paths: ProjectPaths | None = None) -> None:
        self.paths = paths

    def process_signals(self, symbol: str, new_signals: list[Signal]) -> None:
        active_alerts = get_active_alerts(symbol, paths=self.paths)
        for signal in new_signals:
            existing = self._find_matching_alert(active_alerts, signal)
            if existing is None:
                alert_id = create_alert(symbol, signal, paths=self.paths)
                active_alerts.append(
                    {
                        "id": alert_id,
                        "symbol": symbol,
                        "signal_type": signal.type,
                        "signal_level": signal.level,
                        "action": signal.action,
                        "status": "triggered",
                        "trigger_value": signal.value,
                        "trigger_threshold": signal.threshold,
                        "detail": signal.detail,
                        "triggered_at": None,
                        "upgrade_from_id": None,
                    }
                )
            else:
                self._refresh_alert(int(existing["id"]), signal)
                existing.update(
                    {
                        "signal_level": signal.level,
                        "action": signal.action,
                        "trigger_value": signal.value,
                        "trigger_threshold": signal.threshold,
                        "detail": signal.detail,
                    }
                )
        self.check_upgrades(symbol, new_signals)
        self.check_expirations(symbol, new_signals)

    def check_expirations(self, symbol: str, new_signals: list[Signal]) -> None:
        current_signal_types = {signal.type for signal in new_signals}
        for alert in get_active_alerts(symbol, paths=self.paths):
            signal_type = str(alert["signal_type"])
            if signal_type in current_signal_types:
                continue

            signal_level = str(alert["signal_level"])
            if signal_level == "action" and signal_type in CONDITION_BASED_SIGNALS:
                continue

            days_since_trigger = self._days_since_triggered(alert)
            if days_since_trigger < EXPIRY_TRADING_DAYS:
                continue

            if signal_level == "warning":
                update_alert_status(int(alert["id"]), "expired", paths=self.paths)
            elif signal_level == "action" and signal_type in PRICE_BASED_SIGNALS:
                update_alert_status(int(alert["id"]), "historical_reached", paths=self.paths)

    def check_upgrades(self, symbol: str, new_signals: list[Signal]) -> None:
        signal_types = {signal.type for signal in new_signals}
        if "阶段回撤" not in signal_types or "止损触发" not in signal_types:
            return

        alerts = get_active_alerts(symbol, paths=self.paths)
        drawdown_alert = self._find_alert_by_type(alerts, "阶段回撤")
        if drawdown_alert is None:
            return

        drawdown_id = int(drawdown_alert["id"])
        update_alert_status(drawdown_id, "upgraded", paths=self.paths)

        stop_loss_alert = self._find_alert_by_type(alerts, "止损触发")
        if stop_loss_alert is None:
            stop_loss_signal = self._find_signal_by_type(new_signals, "止损触发")
            if stop_loss_signal is None:
                return
            create_alert(
                symbol,
                stop_loss_signal,
                upgrade_from_id=drawdown_id,
                paths=self.paths,
            )
            return

        ensure_schema(self.paths)
        with sqlite_connection(self.paths) as connection:
            connection.execute(
                "UPDATE alert_event SET upgrade_from_id = ? WHERE id = ?",
                (drawdown_id, int(stop_loss_alert["id"])),
            )

    def merge_for_notification(self, symbol: str) -> dict[str, Any] | None:
        active = get_active_alerts(symbol, status="triggered", paths=self.paths)
        if not active:
            return None
        active.sort(key=lambda row: ACTION_PRIORITY.get(str(row["action"]), 0), reverse=True)
        return {
            "symbol": symbol,
            "top_action": str(active[0]["action"]),
            "signals": [
                {
                    "type": str(row["signal_type"]),
                    "action": str(row["action"]),
                    "detail": row["detail"],
                }
                for row in active
            ],
            "signal_count": len(active),
        }

    def acknowledge(self, alert_id: int) -> None:
        update_alert_status(alert_id, "acknowledged", paths=self.paths)

    def resolve(self, alert_id: int) -> None:
        update_alert_status(alert_id, "resolved", paths=self.paths)

    def _find_matching_alert(self, alerts: list[dict[str, Any]], signal: Signal) -> dict[str, Any] | None:
        for alert in alerts:
            if str(alert["signal_type"]) == signal.type:
                return alert
        return None

    def _find_alert_by_type(self, alerts: list[dict[str, Any]], signal_type: str) -> dict[str, Any] | None:
        for alert in alerts:
            if str(alert["signal_type"]) == signal_type:
                return alert
        return None

    def _find_signal_by_type(self, signals: list[Signal], signal_type: str) -> Signal | None:
        for signal in signals:
            if signal.type == signal_type:
                return signal
        return None

    def _refresh_alert(self, alert_id: int, signal: Signal) -> None:
        ensure_schema(self.paths)
        with sqlite_connection(self.paths) as connection:
            connection.execute(
                """
                UPDATE alert_event
                SET signal_level = ?, action = ?, trigger_value = ?, trigger_threshold = ?, detail = ?, triggered_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (signal.level, signal.action, signal.value, signal.threshold, signal.detail, alert_id),
            )

    def _days_since_triggered(self, alert: dict[str, Any]) -> int:
        raw_value = alert.get("triggered_at")
        if raw_value is None:
            return 0
        triggered_at = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        return (datetime.now(triggered_at.tzinfo) - triggered_at).days
