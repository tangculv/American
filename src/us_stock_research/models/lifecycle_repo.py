from __future__ import annotations

from ..time_utils import utc_now_iso
from typing import Any

from ..config import ProjectPaths
from ..utils.validators import ensure_non_empty_string, ensure_state_value
from .database import sqlite_connection


def _utc_now_iso() -> str:
    return utc_now_iso()


def get_stock(connection: Any, symbol: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM stock_master WHERE symbol = ?",
        (ensure_non_empty_string(symbol, "symbol"),),
    ).fetchone()
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def get_lifecycle_state(connection: Any, symbol: str) -> str | None:
    row = connection.execute(
        "SELECT lifecycle_state FROM stock_master WHERE symbol = ?",
        (ensure_non_empty_string(symbol, "symbol"),),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]) if row[0] else None


def update_lifecycle_state(
    *,
    symbol: str,
    to_state: str,
    changed_at: str | None = None,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> None:
    stock_symbol = ensure_non_empty_string(symbol, "symbol")
    next_state = ensure_state_value(to_state, "to_state")
    effective_changed_at = changed_at or _utc_now_iso()

    sql = """
    UPDATE stock_master
    SET lifecycle_state = ?,
        current_state = ?,
        lifecycle_changed_at = ?,
        updated_at = ?,
        last_seen_at = COALESCE(last_seen_at, ?)
    WHERE symbol = ?
    """
    params = (next_state, next_state, effective_changed_at, effective_changed_at, effective_changed_at, stock_symbol)

    if connection is not None:
        connection.execute(sql, params)
        return

    with sqlite_connection(paths) as db:
        db.execute(sql, params)


def upsert_stock_core(
    *,
    stock: dict[str, Any],
    lifecycle_state: str,
    correlation_id: str,
    run_at_iso: str,
    paths: ProjectPaths | None = None,
    connection: Any | None = None,
) -> None:
    symbol = ensure_non_empty_string(stock.get("symbol"), "symbol")
    company_name = ensure_non_empty_string(stock.get("companyName") or stock.get("name"), "company_name")
    exchange = str(stock.get("exchangeShortName") or stock.get("exchange") or "")
    sector = str(stock.get("sector") or "")
    market_cap = stock.get("marketCap") or 0
    avg_volume = stock.get("volume") or stock.get("avgVolume") or 0
    current_price = stock.get("price")
    next_state = ensure_state_value(lifecycle_state, "lifecycle_state")

    sql = """
    INSERT INTO stock_master (
        symbol,
        company_name,
        sector,
        exchange,
        market_cap,
        avg_volume,
        current_price,
        price_updated_at,
        price_stale,
        lifecycle_state,
        lifecycle_changed_at,
        first_discovered_at,
        latest_score,
        latest_signal,
        trade_gate_blocked,
        data_completeness,
        created_at,
        updated_at,
        latest_price,
        latest_market_cap,
        current_state,
        first_seen_at,
        last_seen_at,
        last_correlation_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol) DO UPDATE SET
        company_name = excluded.company_name,
        sector = excluded.sector,
        exchange = excluded.exchange,
        market_cap = excluded.market_cap,
        avg_volume = excluded.avg_volume,
        current_price = excluded.current_price,
        price_updated_at = excluded.price_updated_at,
        lifecycle_state = excluded.lifecycle_state,
        lifecycle_changed_at = excluded.lifecycle_changed_at,
        updated_at = excluded.updated_at,
        latest_price = excluded.latest_price,
        latest_market_cap = excluded.latest_market_cap,
        current_state = excluded.current_state,
        last_seen_at = excluded.last_seen_at,
        last_correlation_id = excluded.last_correlation_id
    """
    params = (
        symbol,
        company_name,
        sector,
        exchange,
        market_cap,
        avg_volume,
        current_price,
        run_at_iso if current_price is not None else None,
        0,
        next_state,
        run_at_iso,
        run_at_iso,
        None,
        None,
        0,
        0,
        run_at_iso,
        run_at_iso,
        current_price,
        market_cap,
        next_state,
        run_at_iso,
        run_at_iso,
        ensure_non_empty_string(correlation_id, "correlation_id"),
    )

    if connection is not None:
        connection.execute(sql, params)
        return

    with sqlite_connection(paths) as db:
        db.execute(sql, params)
