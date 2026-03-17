from __future__ import annotations

from .database import sqlite_connection
from ..config import ProjectPaths

REQUIRED_TABLES = (
    "stock_master",
    "strategy_hit",
    "research_snapshot",
    "research_analysis",
    "technical_snapshot",
    "scoring_breakdown",
    "ranking_snapshot",
    "alert_state",
    "trade_log",
    "alert_event",
    "position_summary",
    "daily_position_snapshot",
    "review_log",
    "notification_event",
    "suggested_change",
    "audit_log",
)

CREATE_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS stock_master (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS strategy_hit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        strategy_id TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        strategy_version TEXT NOT NULL DEFAULT 'v1.0',
        hit_date TEXT NOT NULL,
        hit_at TEXT NOT NULL,
        screening_params_json TEXT NOT NULL DEFAULT '{}',
        initial_score REAL,
        result TEXT NOT NULL DEFAULT 'pending',
        rejection_reason TEXT,
        correlation_id TEXT NOT NULL DEFAULT '',
        screen_payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, strategy_name, hit_at)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS research_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        research_date TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        trigger_priority TEXT NOT NULL,
        prompt_template_id TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        strategy_id TEXT NOT NULL,
        input_data_json TEXT NOT NULL,
        raw_response TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        error_message TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS research_analysis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        research_snapshot_id INTEGER NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        bull_thesis_json TEXT NOT NULL DEFAULT '[]',
        bear_thesis_json TEXT NOT NULL DEFAULT '[]',
        key_risks_json TEXT NOT NULL DEFAULT '[]',
        catalysts_json TEXT NOT NULL DEFAULT '[]',
        valuation_view TEXT NOT NULL DEFAULT 'neutral',
        target_price REAL,
        confidence_score INTEGER NOT NULL DEFAULT 50,
        source_list_json TEXT NOT NULL DEFAULT '[]',
        next_review_date TEXT NOT NULL,
        overall_recommendation TEXT NOT NULL DEFAULT 'hold',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS technical_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        price REAL NOT NULL DEFAULT 0,
        ma_5 REAL,
        ma_10 REAL,
        ma_20 REAL,
        ma_50 REAL,
        ma_200 REAL,
        ma_20_slope REAL,
        rsi_14 REAL,
        macd_line REAL,
        macd_signal REAL,
        macd_histogram REAL,
        atr_14 REAL,
        atr_pct REAL,
        bb_upper REAL,
        bb_lower REAL,
        volume INTEGER,
        volume_ratio REAL,
        high_52w REAL,
        low_52w REAL,
        daily_trend TEXT NOT NULL DEFAULT 'sideways',
        weekly_trend TEXT NOT NULL DEFAULT 'sideways',
        trend_strength_days INTEGER NOT NULL DEFAULT 0,
        signal TEXT NOT NULL DEFAULT 'wait',
        gate_is_blocked INTEGER NOT NULL DEFAULT 0,
        gate_block_reasons_json TEXT NOT NULL DEFAULT '[]',
        gate_blocked_since TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, snapshot_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scoring_breakdown (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        strategy_id TEXT NOT NULL DEFAULT '',
        score_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        scored_at TEXT,
        correlation_id TEXT NOT NULL DEFAULT '',
        fundamental_quality REAL NOT NULL DEFAULT 0,
        fq_roe_score REAL NOT NULL DEFAULT 0,
        fq_margin_score REAL NOT NULL DEFAULT 0,
        fq_debt_score REAL NOT NULL DEFAULT 0,
        fq_current_ratio_score REAL NOT NULL DEFAULT 0,
        valuation_attractiveness REAL NOT NULL DEFAULT 0,
        va_pe_score REAL NOT NULL DEFAULT 0,
        va_pb_score REAL NOT NULL DEFAULT 0,
        va_ev_ebitda_score REAL NOT NULL DEFAULT 0,
        research_conclusion REAL NOT NULL DEFAULT 0,
        catalyst REAL NOT NULL DEFAULT 0,
        risk REAL NOT NULL DEFAULT 0,
        technical_timing REAL NOT NULL DEFAULT 0,
        execution_priority REAL NOT NULL DEFAULT 0,
        weight_profile TEXT NOT NULL DEFAULT 'default',
        formula_version TEXT NOT NULL DEFAULT 'v1.0',
        applied_weights_json TEXT NOT NULL DEFAULT '{}',
        weight_adjustments_json TEXT NOT NULL DEFAULT '[]',
        trigger_context_json TEXT NOT NULL DEFAULT '{}',
        source_snapshot_refs_json TEXT NOT NULL DEFAULT '{}',
        total_score REAL NOT NULL DEFAULT 0,
        missing_dimensions_json TEXT NOT NULL DEFAULT '[]',
        partial_score INTEGER NOT NULL DEFAULT 0,
        score_change_reason TEXT,
        passed_screening INTEGER NOT NULL DEFAULT 0,
        tier_code TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}',
        weights_json TEXT NOT NULL DEFAULT '{}',
        notes_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, strategy_name, score_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ranking_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        ranking_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ranking_scope TEXT NOT NULL DEFAULT 'buy_priority',
        rank INTEGER,
        total_score REAL NOT NULL DEFAULT 0,
        rank_reason_1 TEXT NOT NULL DEFAULT '',
        rank_reason_2 TEXT,
        rank_reason_3 TEXT,
        tie_break_trace_json TEXT NOT NULL DEFAULT '{}',
        strategy_name TEXT NOT NULL DEFAULT '',
        generated_at TEXT,
        correlation_id TEXT NOT NULL DEFAULT '',
        rank_position INTEGER,
        snapshot_batch_id TEXT NOT NULL DEFAULT '',
        scoring_id INTEGER,
        universe_size INTEGER NOT NULL DEFAULT 0,
        rank_percentile REAL,
        trade_gate_status TEXT NOT NULL DEFAULT 'unknown',
        actionable INTEGER NOT NULL DEFAULT 0,
        vs_next_rank TEXT,
        excluded_symbols_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(strategy_name, generated_at, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        alert_level TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        context_json TEXT NOT NULL DEFAULT '{}',
        triggered_at TEXT NOT NULL,
        resolved_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_log (
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
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        signal_level TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'triggered',
        trigger_value REAL,
        trigger_threshold REAL,
        detail TEXT,
        triggered_at TEXT NOT NULL,
        notified_at TEXT,
        acknowledged_at TEXT,
        resolved_at TEXT,
        expired_at TEXT,
        upgrade_from_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS position_summary (
        symbol TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'open',
        total_shares INTEGER NOT NULL DEFAULT 0,
        avg_cost REAL NOT NULL DEFAULT 0,
        first_buy_date TEXT NOT NULL,
        total_invested REAL NOT NULL DEFAULT 0,
        realized_pnl REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_position_snapshot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        price REAL NOT NULL,
        daily_change_pct REAL,
        unrealized_pnl REAL,
        unrealized_pnl_pct REAL,
        holding_days INTEGER,
        volume INTEGER,
        volume_ratio REAL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, snapshot_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        review_type TEXT NOT NULL,
        review_date TEXT NOT NULL,
        summary TEXT NOT NULL,
        outcome TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_event (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        symbol TEXT,
        priority TEXT NOT NULL DEFAULT 'P3',
        template_name TEXT NOT NULL,
        template_version TEXT NOT NULL DEFAULT 'v1',
        payload_json TEXT NOT NULL DEFAULT '{}',
        message_content TEXT NOT NULL DEFAULT '',
        dedupe_key TEXT NOT NULL,
        correlation_id TEXT NOT NULL DEFAULT '',
        sender TEXT NOT NULL DEFAULT 'feishu_webhook',
        cooldown_until TEXT,
        send_status TEXT NOT NULL DEFAULT 'pending',
        sent_at TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(dedupe_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suggested_change (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        change_type TEXT NOT NULL,
        target_object TEXT NOT NULL,
        before_snapshot_json TEXT NOT NULL DEFAULT '{}',
        after_snapshot_json TEXT NOT NULL DEFAULT '{}',
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        proposed_at TEXT NOT NULL,
        approved_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT NOT NULL,
        entity_key TEXT NOT NULL,
        action TEXT NOT NULL,
        previous_state TEXT NOT NULL DEFAULT '',
        new_state TEXT NOT NULL DEFAULT '',
        correlation_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_stock_master_lifecycle_state ON stock_master(lifecycle_state)",
    "CREATE INDEX IF NOT EXISTS idx_stock_master_latest_score ON stock_master(latest_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_stock_master_entry_date ON stock_master(entry_date)",
    "CREATE INDEX IF NOT EXISTS idx_stock_master_first_discovered_at ON stock_master(first_discovered_at)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_hit_symbol_hit_date ON strategy_hit(symbol, hit_date)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_hit_strategy_time ON strategy_hit(strategy_name, hit_at)",
    "CREATE INDEX IF NOT EXISTS idx_research_snapshot_symbol_date ON research_snapshot(symbol, research_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_research_snapshot_status ON research_snapshot(status)",
    "CREATE INDEX IF NOT EXISTS idx_research_snapshot_expires_at ON research_snapshot(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_research_analysis_symbol ON research_analysis(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_technical_snapshot_signal ON technical_snapshot(signal)",
    "CREATE INDEX IF NOT EXISTS idx_technical_snapshot_gate ON technical_snapshot(gate_is_blocked)",
    "CREATE INDEX IF NOT EXISTS idx_scoring_breakdown_symbol_time ON scoring_breakdown(symbol, score_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_scoring_breakdown_score ON scoring_breakdown(total_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_scoring_breakdown_strategy_time ON scoring_breakdown(strategy_name, scored_at)",
    "CREATE INDEX IF NOT EXISTS idx_ranking_snapshot_symbol_date ON ranking_snapshot(symbol, ranking_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ranking_snapshot_strategy_time ON ranking_snapshot(strategy_name, generated_at)",
    "CREATE INDEX IF NOT EXISTS idx_ranking_snapshot_batch_scope ON ranking_snapshot(snapshot_batch_id, ranking_scope, rank)",
    "CREATE INDEX IF NOT EXISTS idx_alert_state_symbol_status ON alert_state(symbol, status)",
    "CREATE INDEX IF NOT EXISTS idx_trade_log_symbol_date ON trade_log(symbol, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_alert_event_symbol_status ON alert_event(symbol, status)",
    "CREATE INDEX IF NOT EXISTS idx_alert_event_signal_level ON alert_event(signal_level, status)",
    "CREATE INDEX IF NOT EXISTS idx_daily_position_snapshot_symbol_date ON daily_position_snapshot(symbol, snapshot_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_stock_master_user_status ON stock_master(user_status)",
    "CREATE INDEX IF NOT EXISTS idx_review_log_symbol_date ON review_log(symbol, review_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notification_event_status ON notification_event(send_status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_notification_event_type_symbol ON notification_event(event_type, symbol, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_suggested_change_status ON suggested_change(status)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_key, created_at)",
)

STOCK_MASTER_COMPAT_ALIASES = (
    ("latest_price", "current_price"),
    ("latest_market_cap", "market_cap"),
    ("current_state", "lifecycle_state"),
)


def _table_columns(connection, table_name: str) -> set[str]:
    if connection is None:
        return set()
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    columns = {str(row[1]) for row in rows}
    sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    table_sql = str(sql_row[0]) if sql_row and sql_row[0] else ""
    normalized_sql = " ".join(table_sql.replace("\n", " ").replace("\t", " ").split()).lower()
    for expected in (
        "snapshot_batch_id",
        "scoring_id",
        "universe_size",
        "rank_percentile",
        "trade_gate_status",
        "actionable",
        "vs_next_rank",
        "excluded_symbols_json",
        "message_content",
        "template_version",
        "sender",
        "cooldown_until",
        "error_message",
    ):
        if expected.lower() in normalized_sql:
            columns.add(expected)
    return columns


def _ensure_column(connection, table_name: str, column_name: str, definition: str) -> None:
    columns = _table_columns(connection, table_name)
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")



def _ensure_notification_event_compatibility(connection) -> None:
    columns = _table_columns(connection, "notification_event")
    if not columns:
        return
    _ensure_column(connection, "notification_event", "message_content", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "notification_event", "template_version", "TEXT NOT NULL DEFAULT 'v1'")
    _ensure_column(connection, "notification_event", "sender", "TEXT NOT NULL DEFAULT 'feishu_webhook'")
    _ensure_column(connection, "notification_event", "cooldown_until", "TEXT")
    _ensure_column(connection, "notification_event", "error_message", "TEXT")

def _ensure_stock_master_compatibility(connection) -> None:
    for target_column, source_column in STOCK_MASTER_COMPAT_ALIASES:
        columns = _table_columns(connection, "stock_master")
        if target_column in columns and source_column in columns:
            connection.execute(
                f"""
                UPDATE stock_master
                SET {source_column} = COALESCE({source_column}, {target_column})
                WHERE {source_column} IS NULL AND {target_column} IS NOT NULL
                """
            )


def _ensure_scoring_breakdown_unique_constraint(connection) -> None:
    columns = _table_columns(connection, "scoring_breakdown")
    if not columns:
        return
    connection.execute(
        """
        UPDATE scoring_breakdown
        SET score_date = COALESCE(NULLIF(score_date, ''), scored_at, CURRENT_TIMESTAMP)
        """
    )
    index_rows = connection.execute("PRAGMA index_list(scoring_breakdown)").fetchall()
    has_score_date_unique = False
    has_legacy_unique = False
    for row in index_rows:
        index_name = str(row[1])
        is_unique = int(row[2]) == 1
        if not is_unique:
            continue
        index_info = connection.execute(f"PRAGMA index_info({index_name})").fetchall()
        index_columns = [str(info[2]) for info in index_info]
        if index_columns == ["symbol", "strategy_name", "score_date"]:
            has_score_date_unique = True
        if index_columns == ["symbol", "strategy_name", "scored_at"]:
            has_legacy_unique = True
    if has_score_date_unique:
        return
    if has_legacy_unique:
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_breakdown_symbol_strategy_score_date ON scoring_breakdown(symbol, strategy_name, score_date)"
        )
        return
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scoring_breakdown_symbol_strategy_score_date ON scoring_breakdown(symbol, strategy_name, score_date)"
    )


def _ensure_schema_migrations(connection) -> None:
    _ensure_column(connection, "stock_master", "market_cap", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "stock_master", "avg_volume", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "stock_master", "current_price", "REAL")
    _ensure_column(connection, "stock_master", "price_updated_at", "TEXT")
    _ensure_column(connection, "stock_master", "price_stale", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "stock_master", "lifecycle_state", "TEXT NOT NULL DEFAULT 'discovered'")
    _ensure_column(connection, "stock_master", "lifecycle_changed_at", "TEXT")
    _ensure_column(connection, "stock_master", "first_discovered_at", "TEXT")
    _ensure_column(connection, "stock_master", "entry_date", "TEXT")
    _ensure_column(connection, "stock_master", "first_research_at", "TEXT")
    _ensure_column(connection, "stock_master", "first_technical_at", "TEXT")
    _ensure_column(connection, "stock_master", "latest_score", "REAL")
    _ensure_column(connection, "stock_master", "latest_signal", "TEXT")
    _ensure_column(connection, "stock_master", "trade_gate_blocked", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "stock_master", "data_completeness", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "stock_master", "archive_snapshot_json", "TEXT")
    _ensure_column(connection, "stock_master", "created_at", "TEXT")
    _ensure_column(connection, "stock_master", "updated_at", "TEXT")
    _ensure_column(connection, "stock_master", "user_status", "TEXT NOT NULL DEFAULT 'watching'")
    _ensure_column(connection, "stock_master", "hit_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "stock_master", "source", "TEXT NOT NULL DEFAULT 'strategy'")
    _ensure_column(connection, "stock_master", "notes", "TEXT")

    _ensure_column(connection, "strategy_hit", "strategy_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "strategy_hit", "strategy_version", "TEXT NOT NULL DEFAULT 'v1.0'")
    _ensure_column(connection, "strategy_hit", "hit_date", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "strategy_hit", "screening_params_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "strategy_hit", "initial_score", "REAL")
    _ensure_column(connection, "strategy_hit", "result", "TEXT NOT NULL DEFAULT 'pending'")
    _ensure_column(connection, "strategy_hit", "rejection_reason", "TEXT")
    _ensure_column(connection, "strategy_hit", "created_at", "TEXT")

    _ensure_column(connection, "research_analysis", "tangible_book_value_per_share", "REAL")
    _ensure_column(connection, "research_analysis", "price_to_tbv", "REAL")
    _ensure_column(connection, "research_analysis", "normalized_eps", "REAL")
    _ensure_column(connection, "research_analysis", "normalized_earnings_yield", "REAL")
    _ensure_column(connection, "research_analysis", "net_debt_to_ebitda", "REAL")
    _ensure_column(connection, "research_analysis", "interest_coverage", "REAL")
    _ensure_column(connection, "research_analysis", "goodwill_pct", "REAL")
    _ensure_column(connection, "research_analysis", "intangible_pct", "REAL")
    _ensure_column(connection, "research_analysis", "tangible_net_asset_positive", "INTEGER")
    _ensure_column(connection, "research_analysis", "safety_margin_source", "TEXT")
    _ensure_column(connection, "research_analysis", "buy_range_low", "REAL")
    _ensure_column(connection, "research_analysis", "buy_range_high", "REAL")
    _ensure_column(connection, "research_analysis", "max_position_pct", "REAL")
    _ensure_column(connection, "research_analysis", "target_price_conservative", "REAL")
    _ensure_column(connection, "research_analysis", "target_price_base", "REAL")
    _ensure_column(connection, "research_analysis", "target_price_optimistic", "REAL")
    _ensure_column(connection, "research_analysis", "stop_loss_condition", "TEXT")
    _ensure_column(connection, "research_analysis", "add_position_condition", "TEXT")
    _ensure_column(connection, "research_analysis", "reduce_position_condition", "TEXT")
    _ensure_column(connection, "research_analysis", "overall_conclusion", "TEXT")
    _ensure_column(connection, "research_analysis", "top_risks_json", "TEXT")
    _ensure_column(connection, "research_analysis", "invalidation_conditions_json", "TEXT")
    _ensure_column(connection, "research_analysis", "three_sentence_summary", "TEXT")
    _ensure_column(connection, "research_analysis", "refinancing_risk", "TEXT")
    _ensure_column(connection, "research_analysis", "feishu_doc_url", "TEXT")

    _ensure_column(connection, "trade_log", "reason", "TEXT")

    _ensure_column(connection, "scoring_breakdown", "strategy_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "scoring_breakdown", "score_date", "TEXT")
    _ensure_column(connection, "scoring_breakdown", "fundamental_quality", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "fq_roe_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "fq_margin_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "fq_debt_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "fq_current_ratio_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "valuation_attractiveness", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "va_pe_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "va_pb_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "va_ev_ebitda_score", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "research_conclusion", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "catalyst", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "risk", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "technical_timing", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "execution_priority", "REAL NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "weight_profile", "TEXT NOT NULL DEFAULT 'default'")
    _ensure_column(connection, "scoring_breakdown", "formula_version", "TEXT NOT NULL DEFAULT 'v1.0'")
    _ensure_column(connection, "scoring_breakdown", "applied_weights_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "scoring_breakdown", "weight_adjustments_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "scoring_breakdown", "trigger_context_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "scoring_breakdown", "source_snapshot_refs_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(connection, "scoring_breakdown", "missing_dimensions_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "scoring_breakdown", "partial_score", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "scoring_breakdown", "score_change_reason", "TEXT")
    _ensure_column(connection, "scoring_breakdown", "created_at", "TEXT")

    _ensure_column(connection, "ranking_snapshot", "symbol", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "ranking_snapshot", "ranking_date", "TEXT")
    _ensure_column(connection, "ranking_snapshot", "ranking_scope", "TEXT NOT NULL DEFAULT 'buy_priority'")
    _ensure_column(connection, "ranking_snapshot", "rank", "INTEGER")
    _ensure_column(connection, "ranking_snapshot", "rank_reason_1", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "ranking_snapshot", "rank_reason_2", "TEXT")
    _ensure_column(connection, "ranking_snapshot", "rank_reason_3", "TEXT")
    _ensure_column(connection, "ranking_snapshot", "snapshot_batch_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(connection, "ranking_snapshot", "scoring_id", "INTEGER")
    _ensure_column(connection, "ranking_snapshot", "universe_size", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "ranking_snapshot", "rank_percentile", "REAL")
    _ensure_column(connection, "ranking_snapshot", "trade_gate_status", "TEXT NOT NULL DEFAULT 'unknown'")
    _ensure_column(connection, "ranking_snapshot", "actionable", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "ranking_snapshot", "vs_next_rank", "TEXT")
    _ensure_column(connection, "ranking_snapshot", "excluded_symbols_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(connection, "ranking_snapshot", "created_at", "TEXT")

    _ensure_stock_master_compatibility(connection)
    _ensure_scoring_breakdown_unique_constraint(connection)

    connection.execute(
        """
        UPDATE stock_master
        SET lifecycle_state = COALESCE(NULLIF(lifecycle_state, ''), current_state, 'discovered')
        WHERE lifecycle_state IS NULL OR lifecycle_state = ''
        """
    )
    connection.execute(
        """
        UPDATE stock_master
        SET current_state = COALESCE(NULLIF(current_state, ''), lifecycle_state, 'discovered')
        WHERE current_state IS NULL OR current_state = ''
        """
    )
    connection.execute(
        """
        UPDATE stock_master
        SET current_price = COALESCE(current_price, latest_price),
            market_cap = COALESCE(NULLIF(market_cap, 0), latest_market_cap, 0),
            first_discovered_at = COALESCE(NULLIF(first_discovered_at, ''), first_seen_at, CURRENT_TIMESTAMP),
            lifecycle_changed_at = COALESCE(NULLIF(lifecycle_changed_at, ''), last_seen_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(NULLIF(updated_at, ''), last_seen_at, CURRENT_TIMESTAMP),
            created_at = COALESCE(NULLIF(created_at, ''), first_seen_at, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        UPDATE strategy_hit
        SET hit_date = COALESCE(NULLIF(hit_date, ''), substr(hit_at, 1, 10)),
            strategy_id = COALESCE(NULLIF(strategy_id, ''), strategy_name),
            screening_params_json = COALESCE(NULLIF(screening_params_json, ''), '{}'),
            result = CASE
                WHEN result IS NULL OR result = '' THEN 'pending'
                ELSE result
            END,
            created_at = COALESCE(NULLIF(created_at, ''), hit_at, CURRENT_TIMESTAMP)
        """
    )
    connection.execute(
        """
        UPDATE scoring_breakdown
        SET score_date = COALESCE(NULLIF(score_date, ''), scored_at, CURRENT_TIMESTAMP),
            created_at = COALESCE(NULLIF(created_at, ''), scored_at, CURRENT_TIMESTAMP),
            applied_weights_json = COALESCE(NULLIF(applied_weights_json, ''), weights_json, '{}'),
            trigger_context_json = COALESCE(NULLIF(trigger_context_json, ''), '{}'),
            source_snapshot_refs_json = COALESCE(NULLIF(source_snapshot_refs_json, ''), '{}'),
            missing_dimensions_json = COALESCE(NULLIF(missing_dimensions_json, ''), '[]')
        """
    )
    connection.execute(
        """
        UPDATE ranking_snapshot
        SET ranking_date = COALESCE(NULLIF(ranking_date, ''), generated_at, CURRENT_TIMESTAMP),
            rank = COALESCE(rank, rank_position),
            snapshot_batch_id = COALESCE(NULLIF(snapshot_batch_id, ''), generated_at, CURRENT_TIMESTAMP),
            universe_size = CASE WHEN universe_size <= 0 THEN COALESCE(universe_size, 0) ELSE universe_size END,
            trade_gate_status = COALESCE(NULLIF(trade_gate_status, ''), CASE WHEN total_score > 0 THEN 'unblocked' ELSE 'unknown' END),
            actionable = COALESCE(actionable, 0),
            excluded_symbols_json = COALESCE(NULLIF(excluded_symbols_json, ''), '[]'),
            created_at = COALESCE(NULLIF(created_at, ''), generated_at, CURRENT_TIMESTAMP),
            ranking_scope = COALESCE(NULLIF(ranking_scope, ''), 'buy_priority')
        """
    )
    connection.execute(
        """
        WITH batch_sizes AS (
            SELECT snapshot_batch_id, ranking_scope, COUNT(*) AS cnt
            FROM ranking_snapshot
            GROUP BY snapshot_batch_id, ranking_scope
        )
        UPDATE ranking_snapshot
        SET universe_size = COALESCE(NULLIF(universe_size, 0), (
                SELECT cnt FROM batch_sizes bs
                WHERE bs.snapshot_batch_id = ranking_snapshot.snapshot_batch_id
                  AND bs.ranking_scope = ranking_snapshot.ranking_scope
            ), 0),
            rank_percentile = CASE
                WHEN COALESCE(NULLIF(universe_size, 0), (
                    SELECT cnt FROM batch_sizes bs
                    WHERE bs.snapshot_batch_id = ranking_snapshot.snapshot_batch_id
                      AND bs.ranking_scope = ranking_snapshot.ranking_scope
                ), 0) > 0 AND COALESCE(rank, rank_position) IS NOT NULL
                THEN ((COALESCE(NULLIF(universe_size, 0), (
                    SELECT cnt FROM batch_sizes bs
                    WHERE bs.snapshot_batch_id = ranking_snapshot.snapshot_batch_id
                      AND bs.ranking_scope = ranking_snapshot.ranking_scope
                ), 0) - COALESCE(rank, rank_position) + 1) * 100.0) / COALESCE(NULLIF(universe_size, 0), (
                    SELECT cnt FROM batch_sizes bs
                    WHERE bs.snapshot_batch_id = ranking_snapshot.snapshot_batch_id
                      AND bs.ranking_scope = ranking_snapshot.ranking_scope
                ), 1)
                ELSE rank_percentile
            END
        """
    )


def ensure_schema(paths: ProjectPaths | None = None) -> None:
    with sqlite_connection(paths) as connection:
        for statement in CREATE_TABLE_STATEMENTS:
            connection.execute(statement)
        _ensure_schema_migrations(connection)
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
