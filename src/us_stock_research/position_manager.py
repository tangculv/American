from __future__ import annotations

from typing import Any

from .config import ProjectPaths
from .models.database import sqlite_connection
from .models.schema import ensure_schema

VALID_TRADE_TYPES = ("buy", "sell")
VALID_POSITION_STATUS = ("open", "closed")
_TERMINAL_ALERT_STATUSES = ("resolved", "expired", "historical_reached", "upgraded")


def record_buy(
    symbol: str,
    price: float,
    quantity: int,
    buy_date: str,
    reason: str | None = None,
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        stock = connection.execute(
            "SELECT symbol FROM stock_master WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if stock is None:
            connection.execute(
                """
                INSERT INTO stock_master (symbol, company_name, source, hit_count, user_status)
                VALUES (?, ?, 'manual_entry', 0, 'watching')
                """,
                (symbol, symbol),
            )

        connection.execute(
            """
            INSERT INTO trade_log (symbol, trade_type, trade_date, price, quantity, reason)
            VALUES (?, 'buy', ?, ?, ?, ?)
            """,
            (symbol, buy_date, float(price), int(quantity), reason),
        )
        connection.execute(
            "UPDATE stock_master SET user_status = 'held' WHERE symbol = ?",
            (symbol,),
        )

    update_position_summary(symbol, paths=paths)


def record_sell(
    symbol: str,
    price: float,
    quantity: int,
    sell_date: str,
    reason: str | None = None,
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    position = get_position(symbol, paths=paths)
    if position is None:
        raise ValueError(f"position not found: {symbol}")

    avg_cost = float(position["avg_cost"])
    _ = (float(price) - avg_cost) * int(quantity)

    with sqlite_connection(paths) as connection:
        connection.execute(
            """
            INSERT INTO trade_log (symbol, trade_type, trade_date, price, quantity, reason)
            VALUES (?, 'sell', ?, ?, ?, ?)
            """,
            (symbol, sell_date, float(price), int(quantity), reason),
        )

    update_position_summary(symbol, paths=paths)
    updated_position = get_position(symbol, paths=paths)
    if updated_position is None:
        return

    with sqlite_connection(paths) as connection:
        if updated_position["status"] == "closed" or int(updated_position["total_shares"]) <= 0:
            connection.execute(
                "UPDATE position_summary SET status = 'closed', total_shares = 0 WHERE symbol = ?",
                (symbol,),
            )
            connection.execute(
                "UPDATE stock_master SET user_status = 'closed' WHERE symbol = ?",
                (symbol,),
            )
            placeholders = ", ".join("?" for _ in _TERMINAL_ALERT_STATUSES)
            connection.execute(
                f"""
                UPDATE alert_event
                SET status = 'resolved', resolved_at = COALESCE(resolved_at, CURRENT_TIMESTAMP)
                WHERE symbol = ? AND status NOT IN ({placeholders})
                """,
                (symbol, *_TERMINAL_ALERT_STATUSES),
            )
        else:
            connection.execute(
                "UPDATE stock_master SET user_status = 'held' WHERE symbol = ?",
                (symbol,),
            )


def update_position_summary(symbol: str, paths: ProjectPaths | None = None) -> None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        rows = connection.execute(
            """
            SELECT trade_type, trade_date, price, quantity
            FROM trade_log
            WHERE symbol = ? AND trade_type IN ('buy', 'sell')
            ORDER BY trade_date ASC, id ASC
            """,
            (symbol,),
        ).fetchall()

        buys = [row for row in rows if str(row[0]) == "buy"]
        sells = [row for row in rows if str(row[0]) == "sell"]

        if not buys:
            return

        total_bought_shares = sum(int(row[3]) for row in buys)
        total_bought_cost = sum(float(row[2]) * int(row[3]) for row in buys)
        total_sold_shares = sum(int(row[3]) for row in sells)
        remaining = total_bought_shares - total_sold_shares
        avg_cost = total_bought_cost / total_bought_shares
        first_buy_date = min(str(row[1]) for row in buys)
        total_invested = total_bought_cost
        realized_pnl = sum((float(row[2]) - avg_cost) * int(row[3]) for row in sells)
        status = "open" if remaining > 0 else "closed"

        connection.execute(
            """
            INSERT OR REPLACE INTO position_summary (
                symbol, status, total_shares, avg_cost,
                first_buy_date, total_invested, realized_pnl, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                symbol,
                status,
                max(int(remaining), 0),
                float(avg_cost),
                first_buy_date,
                float(total_invested),
                float(realized_pnl),
            ),
        )


def get_position(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any] | None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT symbol, status, total_shares, avg_cost,
                   first_buy_date, total_invested, realized_pnl
            FROM position_summary
            WHERE symbol = ?
            """,
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    return {
        "symbol": str(row[0]),
        "status": str(row[1]),
        "total_shares": int(row[2]),
        "avg_cost": float(row[3]),
        "first_buy_date": str(row[4]),
        "total_invested": float(row[5]),
        "realized_pnl": float(row[6]),
    }


def is_held(symbol: str, paths: ProjectPaths | None = None) -> bool:
    position = get_position(symbol, paths=paths)
    return bool(position and position["status"] == "open" and int(position["total_shares"]) > 0)
