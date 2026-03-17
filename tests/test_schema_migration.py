from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.models.schema import CREATE_TABLE_STATEMENTS, INDEX_STATEMENTS, _ensure_schema_migrations  # noqa: E402


RESEARCH_ANALYSIS_NEW_COLUMNS = [
    "tangible_book_value_per_share",
    "price_to_tbv",
    "normalized_eps",
    "normalized_earnings_yield",
    "net_debt_to_ebitda",
    "interest_coverage",
    "goodwill_pct",
    "intangible_pct",
    "tangible_net_asset_positive",
    "safety_margin_source",
    "buy_range_low",
    "buy_range_high",
    "max_position_pct",
    "target_price_conservative",
    "target_price_base",
    "target_price_optimistic",
    "stop_loss_condition",
    "add_position_condition",
    "reduce_position_condition",
    "overall_conclusion",
    "top_risks_json",
    "invalidation_conditions_json",
    "three_sentence_summary",
    "refinancing_risk",
    "feishu_doc_url",
]

NEW_INDEX_NAMES = {
    "idx_alert_event_symbol_status",
    "idx_alert_event_signal_level",
    "idx_daily_position_snapshot_symbol_date",
    "idx_stock_master_user_status",
}


def create_latest_schema(connection: sqlite3.Connection) -> None:
    for statement in CREATE_TABLE_STATEMENTS:
        connection.execute(statement)
    _ensure_schema_migrations(connection)
    for statement in INDEX_STATEMENTS:
        connection.execute(statement)


def create_legacy_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE stock_master (
            symbol TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            sector TEXT NOT NULL DEFAULT '',
            exchange TEXT NOT NULL DEFAULT '',
            market_cap REAL NOT NULL DEFAULT 0,
            avg_volume INTEGER NOT NULL DEFAULT 0,
            current_price REAL,
            price_updated_at TEXT,
            price_stale INTEGER NOT NULL DEFAULT 0,
            lifecycle_state TEXT NOT NULL DEFAULT 'discovered',
            lifecycle_changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            first_discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            entry_date TEXT,
            first_research_at TEXT,
            first_technical_at TEXT,
            latest_score REAL,
            latest_signal TEXT,
            trade_gate_blocked INTEGER NOT NULL DEFAULT 0,
            data_completeness REAL NOT NULL DEFAULT 0,
            archive_snapshot_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            latest_price REAL,
            latest_market_cap REAL,
            current_state TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT,
            last_correlation_id TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE strategy_hit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            hit_at TEXT NOT NULL,
            correlation_id TEXT NOT NULL DEFAULT '',
            screen_payload_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE research_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            research_snapshot_id INTEGER NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            bull_thesis_json TEXT NOT NULL DEFAULT '[]',
            bear_thesis_json TEXT NOT NULL DEFAULT '[]',
            key_risks_json TEXT NOT NULL DEFAULT '[]',
            catalysts_json TEXT NOT NULL DEFAULT '[]',
            valuation_view TEXT NOT NULL DEFAULT 'neutral',
            target_price REAL,
            invalidation_conditions_json TEXT NOT NULL DEFAULT '[]',
            confidence_score INTEGER NOT NULL DEFAULT 50,
            source_list_json TEXT NOT NULL DEFAULT '[]',
            next_review_date TEXT NOT NULL,
            overall_recommendation TEXT NOT NULL DEFAULT 'hold',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            fees REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE scoring_breakdown (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            scored_at TEXT,
            total_score REAL NOT NULL DEFAULT 0,
            weights_json TEXT NOT NULL DEFAULT '{}',
            notes_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE ranking_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            total_score REAL NOT NULL DEFAULT 0,
            strategy_name TEXT NOT NULL DEFAULT '',
            generated_at TEXT,
            correlation_id TEXT NOT NULL DEFAULT '',
            rank_position INTEGER,
            tie_break_trace_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def table_columns(connection: sqlite3.Connection, table_name: str) -> dict[str, tuple[str, int, str | None]]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]): (str(row[2]), int(row[3]), row[4]) for row in rows}


def test_new_tables_created() -> None:
    connection = sqlite3.connect(":memory:")

    create_latest_schema(connection)

    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"alert_event", "position_summary", "daily_position_snapshot"}.issubset(tables)


def test_new_tables_crud() -> None:
    connection = sqlite3.connect(":memory:")
    create_latest_schema(connection)

    connection.execute(
        """
        INSERT INTO alert_event (
            symbol, signal_type, signal_level, action, trigger_value,
            trigger_threshold, detail, triggered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("AAPL", "急跌预警", "warning", "继续观察", 92.5, 95.0, "跌破阈值", "2026-03-16T09:30:00"),
    )
    connection.execute(
        """
        INSERT INTO position_summary (
            symbol, first_buy_date, total_shares, avg_cost, total_invested, realized_pnl
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("AAPL", "2026-03-01", 100, 88.8, 8880.0, 120.5),
    )
    connection.execute(
        """
        INSERT INTO daily_position_snapshot (
            symbol, snapshot_date, price, daily_change_pct, unrealized_pnl,
            unrealized_pnl_pct, holding_days, volume, volume_ratio
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("AAPL", "2026-03-16", 92.5, -3.1, 370.0, 4.17, 15, 1000000, 1.8),
    )

    alert = connection.execute(
        "SELECT symbol, status, action FROM alert_event WHERE symbol = 'AAPL'"
    ).fetchone()
    position = connection.execute(
        "SELECT symbol, status, total_shares FROM position_summary WHERE symbol = 'AAPL'"
    ).fetchone()
    snapshot = connection.execute(
        "SELECT symbol, snapshot_date, price FROM daily_position_snapshot WHERE symbol = 'AAPL'"
    ).fetchone()

    assert alert == ("AAPL", "triggered", "继续观察")
    assert position == ("AAPL", "open", 100)
    assert snapshot == ("AAPL", "2026-03-16", 92.5)


def test_stock_master_new_columns() -> None:
    connection = sqlite3.connect(":memory:")
    create_latest_schema(connection)

    columns = table_columns(connection, "stock_master")
    assert columns["user_status"] == ("TEXT", 1, "'watching'")
    assert columns["hit_count"] == ("INTEGER", 1, "0")
    assert columns["source"] == ("TEXT", 1, "'strategy'")

    connection.execute("INSERT INTO stock_master (symbol, company_name) VALUES (?, ?)", ("MSFT", "Microsoft"))
    row = connection.execute(
        "SELECT user_status, hit_count, source FROM stock_master WHERE symbol = 'MSFT'"
    ).fetchone()
    assert row == ("watching", 0, "strategy")


def test_research_analysis_new_columns() -> None:
    connection = sqlite3.connect(":memory:")
    create_latest_schema(connection)

    columns = table_columns(connection, "research_analysis")
    for column_name in RESEARCH_ANALYSIS_NEW_COLUMNS:
        assert column_name in columns
        assert columns[column_name][1] == 0


    connection.execute(
        """
        INSERT INTO research_analysis (research_snapshot_id, symbol, next_review_date)
        VALUES (?, ?, ?)
        """,
        (1, "NVDA", "2026-03-20"),
    )
    row = connection.execute(
        f"SELECT {', '.join(RESEARCH_ANALYSIS_NEW_COLUMNS)} FROM research_analysis WHERE research_snapshot_id = 1"
    ).fetchone()
    assert row == tuple([None] * len(RESEARCH_ANALYSIS_NEW_COLUMNS))


def test_trade_log_reason_column() -> None:
    connection = sqlite3.connect(":memory:")
    create_latest_schema(connection)

    columns = table_columns(connection, "trade_log")
    assert "reason" in columns
    assert columns["reason"][0] == "TEXT"


def test_migration_idempotent() -> None:
    connection = sqlite3.connect(":memory:")

    create_latest_schema(connection)
    create_latest_schema(connection)

    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "alert_event" in tables


def test_existing_data_preserved() -> None:
    connection = sqlite3.connect(":memory:")
    create_legacy_schema(connection)

    connection.execute(
        "INSERT INTO stock_master (symbol, company_name, latest_score) VALUES (?, ?, ?)",
        ("TSLA", "Tesla", 91.2),
    )
    connection.execute(
        "INSERT INTO research_analysis (research_snapshot_id, symbol, next_review_date) VALUES (?, ?, ?)",
        (10, "TSLA", "2026-03-30"),
    )
    connection.execute(
        "INSERT INTO trade_log (symbol, trade_type, trade_date, price, quantity, notes) VALUES (?, ?, ?, ?, ?, ?)",
        ("TSLA", "buy", "2026-03-10", 250.0, 10, "legacy"),
    )

    _ensure_schema_migrations(connection)

    stock = connection.execute(
        "SELECT symbol, company_name, latest_score, user_status, hit_count, source FROM stock_master WHERE symbol = 'TSLA'"
    ).fetchone()
    analysis = connection.execute(
        "SELECT symbol, next_review_date, overall_conclusion, feishu_doc_url FROM research_analysis WHERE research_snapshot_id = 10"
    ).fetchone()
    trade = connection.execute(
        "SELECT symbol, trade_type, notes, reason FROM trade_log WHERE symbol = 'TSLA'"
    ).fetchone()

    assert stock == ("TSLA", "Tesla", 91.2, "watching", 0, "strategy")
    assert analysis == ("TSLA", "2026-03-30", None, None)
    assert trade == ("TSLA", "buy", "legacy", None)


def test_new_indexes_created() -> None:
    connection = sqlite3.connect(":memory:")
    create_latest_schema(connection)

    indexes = {
        row[1]
        for row in connection.execute("PRAGMA index_list('alert_event')").fetchall()
    }
    indexes |= {
        row[1]
        for row in connection.execute("PRAGMA index_list('daily_position_snapshot')").fetchall()
    }
    indexes |= {
        row[1]
        for row in connection.execute("PRAGMA index_list('stock_master')").fetchall()
    }

    assert NEW_INDEX_NAMES.issubset(indexes)
