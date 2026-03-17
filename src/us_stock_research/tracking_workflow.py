from __future__ import annotations

import json
import logging
from .time_utils import utc_now_iso
from typing import Any

from .alert_engine import AlertEngine, Signal
from .alert_manager import AlertManager
from .config import ProjectPaths, load_settings
from .fmp_client import FMPClient
from .models.database import sqlite_connection
from .models.schema import ensure_schema
from .position_manager import get_position, is_held
from .research_engine import execute_research_with_two_layer_output, run_deep_research, save_two_layer_result
from .scoring_engine import build_scoring_payload
from .technical_analysis import infer_basic_technical_snapshot, technical_timing_score
from .workflow_engine import persist_technical_snapshot
from .portfolio_workflow import trigger_exit_watch
from .event_notifications import build_event_payload, create_notification_event
from .feishu_doc import FeishuDocError, create_research_doc, write_doc_url_to_db

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return utc_now_iso()


def _holding_quantity(connection: Any, symbol: str) -> float:
    row = connection.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN trade_type='buy' THEN quantity ELSE -quantity END), 0)
        FROM trade_log
        WHERE symbol = ?
        """,
        (symbol,),
    ).fetchone()
    return float(row[0] or 0)


def _latest_buy_price(connection: Any, symbol: str) -> float | None:
    row = connection.execute(
        "SELECT price FROM trade_log WHERE symbol = ? AND trade_type = 'buy' ORDER BY trade_date DESC, id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    return None if row is None else float(row[0])


def _load_stock_context(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any] | None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT symbol, company_name, sector, exchange, current_price, market_cap, avg_volume
            FROM stock_master
            WHERE symbol = ?
            """,
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    return {
        "symbol": row[0],
        "companyName": row[1],
        "company_name": row[1],
        "sector": row[2],
        "exchange": row[3],
        "price": row[4],
        "marketCap": row[5],
        "avgVolume": row[6],
    }


def _latest_conclusion(symbol: str, paths: ProjectPaths | None = None) -> str | None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            "SELECT overall_conclusion FROM research_analysis WHERE symbol = ? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return None if row is None else row[0]


def _load_research_analysis(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any] | None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT net_debt_to_ebitda,
                   stop_loss_condition,
                   target_price_conservative, target_price_base, target_price_optimistic,
                   invalidation_conditions_json, overall_conclusion
            FROM research_analysis
            WHERE symbol = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    return {
        "prev_roe": None,
        "roe": None,
        "net_debt_to_ebitda": row[0],
        "stop_loss_condition": row[1],
        "target_price_conservative": row[2],
        "target_price_base": row[3],
        "target_price_optimistic": row[4],
        "invalidation_conditions_json": row[5],
        "overall_conclusion": row[6],
    }


def build_monitoring_snapshot(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any]:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        rows = connection.execute(
            """
            SELECT price, ma_50, ma_200, rsi_14, ma_20_slope,
                   high_52w, volume, volume_ratio, weekly_trend
            FROM technical_snapshot
            WHERE symbol = ?
            ORDER BY snapshot_date DESC, id DESC
            LIMIT 2
            """,
            (symbol,),
        ).fetchall()

    snapshot = {
        "price": None,
        "daily_change_pct": None,
        "ma_50": None,
        "ma_200": None,
        "prev_ma_50": None,
        "prev_ma_200": None,
        "rsi_14": None,
        "ma_50_slope": None,
        "high_52w": None,
        "volume": None,
        "volume_ratio": None,
        "weekly_trend": None,
    }
    if not rows:
        return snapshot

    latest = rows[0]
    snapshot.update(
        {
            "price": latest[0],
            "ma_50": latest[1],
            "ma_200": latest[2],
            "rsi_14": latest[3],
            "ma_50_slope": latest[4],
            "high_52w": latest[5],
            "volume": latest[6],
            "volume_ratio": latest[7],
            "weekly_trend": latest[8],
        }
    )

    if len(rows) > 1:
        previous = rows[1]
        previous_price = previous[0]
        if latest[0] is not None and previous_price not in (None, 0):
            snapshot["daily_change_pct"] = (float(latest[0]) - float(previous_price)) / float(previous_price) * 100.0
        snapshot["prev_ma_50"] = previous[1]
        snapshot["prev_ma_200"] = previous[2]

    return snapshot


def write_daily_snapshot(
    symbol: str,
    snapshot: dict[str, Any],
    position: dict[str, Any],
    paths: ProjectPaths | None = None,
) -> None:
    ensure_schema(paths)
    price = snapshot.get("price")
    avg_cost = position.get("avg_cost")
    total_shares = position.get("total_shares")
    first_buy_date = str(position.get("first_buy_date") or "")

    unrealized_pnl = None
    unrealized_pnl_pct = None
    if price is not None and avg_cost not in (None, 0) and total_shares is not None:
        unrealized_pnl = (float(price) - float(avg_cost)) * float(total_shares)
        unrealized_pnl_pct = (float(price) - float(avg_cost)) / float(avg_cost) * 100.0

    holding_days = None
    if first_buy_date:
        from datetime import date
        holding_days = max((date.fromisoformat(utc_now_iso()[:10]) - date.fromisoformat(first_buy_date[:10])).days, 0)

    with sqlite_connection(paths) as connection:
        connection.execute(
            """
            INSERT INTO daily_position_snapshot (
                symbol, snapshot_date, price, daily_change_pct,
                unrealized_pnl, unrealized_pnl_pct, holding_days,
                volume, volume_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, snapshot_date) DO UPDATE SET
                price = excluded.price,
                daily_change_pct = excluded.daily_change_pct,
                unrealized_pnl = excluded.unrealized_pnl,
                unrealized_pnl_pct = excluded.unrealized_pnl_pct,
                holding_days = excluded.holding_days,
                volume = excluded.volume,
                volume_ratio = excluded.volume_ratio
            """,
            (
                symbol,
                utc_now_iso()[:10],
                snapshot.get("price") or 0,
                snapshot.get("daily_change_pct"),
                unrealized_pnl,
                unrealized_pnl_pct,
                holding_days,
                snapshot.get("volume"),
                snapshot.get("volume_ratio"),
            ),
        )


def check_reresearch_trigger(symbol: str, snapshot: dict[str, Any], paths: ProjectPaths | None = None) -> bool:
    if not is_held(symbol, paths=paths):
        return False

    daily_change_pct = snapshot.get("daily_change_pct")
    if daily_change_pct is not None and abs(float(daily_change_pct)) >= 5.0:
        return True

    current_trend = snapshot.get("weekly_trend")
    if not current_trend:
        return False

    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT weekly_trend
            FROM technical_snapshot
            WHERE symbol = ?
            ORDER BY snapshot_date DESC, id DESC
            LIMIT 1 OFFSET 1
            """,
            (symbol,),
        ).fetchone()
    previous_trend = None if row is None else row[0]
    if previous_trend == "up" and current_trend == "down":
        return True
    if previous_trend == "down" and current_trend == "up":
        return True
    return False


def run_daily_monitoring(paths: ProjectPaths | None = None) -> dict[str, Any]:
    ensure_schema(paths)
    engine = AlertEngine()
    manager = AlertManager(paths=paths)
    result = {"monitored": 0, "signals_detected": 0, "reresearch_triggered": []}

    with sqlite_connection(paths) as connection:
        symbols = [row[0] for row in connection.execute("SELECT symbol FROM position_summary WHERE status = 'open' ORDER BY symbol ASC").fetchall()]

    for symbol in symbols:
        result["monitored"] += 1
        try:
            refresh_holding_tracking(symbol=symbol, paths=paths)
            snapshot = build_monitoring_snapshot(symbol, paths=paths)
            position = get_position(symbol, paths=paths)
            if position is None:
                continue
            write_daily_snapshot(symbol, snapshot, position, paths=paths)
            research = _load_research_analysis(symbol, paths=paths)
            signals = engine.detect_signals(symbol, snapshot, research, position)
            result["signals_detected"] += len(signals)
            manager.process_signals(symbol, signals)
            if check_reresearch_trigger(symbol, snapshot, paths=paths):
                result["reresearch_triggered"].append(symbol)
        except Exception as exc:
            logger.exception("daily monitoring failed for %s: %s", symbol, exc)
            continue

    return result


def refresh_holding_tracking(*, symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    settings = load_settings()
    client = FMPClient(settings.fmp_api_key, settings.fmp_base_url, settings.request_timeout)
    now = _utc_now_iso()

    with sqlite_connection(paths) as connection:
        stock_row = connection.execute(
            "SELECT symbol, company_name, sector, exchange, trade_gate_blocked FROM stock_master WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if stock_row is None:
            raise ValueError(f"symbol not found: {symbol}")

        quote_candidates = client.company_screener(
            market_cap_min=0,
            market_cap_max=10_000_000_000_000,
            volume_min=0,
            sector=str(stock_row[2] or ''),
            exchange=str(stock_row[3] or 'NASDAQ'),
            limit=500,
        )
        quote = next((item for item in quote_candidates if str(item.get('symbol')) == symbol), None)
        if quote is None:
            raise ValueError(f"unable to refresh live quote for {symbol}")

        quote['ratios'] = client.ratios_ttm(symbol)
        research = run_deep_research(quote, paths=paths)
        technical_snapshot = infer_basic_technical_snapshot(quote, client=client)
        scoring = build_scoring_payload(
            quote,
            market_trend='default',
            technical_timing=technical_timing_score(technical_snapshot),
            technical_signal=technical_snapshot.signal,
            price_stale=technical_snapshot.price_stale,
            research_analysis={
                'confidence_score': research.confidence_score,
                'bull_thesis': research.bull_thesis,
                'bear_thesis': research.bear_thesis,
                'catalysts': research.catalysts,
                'key_risks': research.key_risks,
            },
            holding_count_by_sector=0,
            avg_volume=quote.get('volume') or quote.get('avgVolume') or quote.get('volAvg'),
            market_cap=quote.get('marketCap'),
        )

        previous_score_row = connection.execute("SELECT latest_score, current_price FROM stock_master WHERE symbol = ?", (symbol,)).fetchone()
        previous_score = float(previous_score_row[0]) if previous_score_row and previous_score_row[0] is not None else None
        previous_price = float(previous_score_row[1]) if previous_score_row and previous_score_row[1] is not None else None

        persist_technical_snapshot(
            symbol=symbol,
            snapshot=technical_snapshot,
            price=quote.get('price'),
            snapshot_date=now[:10],
            paths=paths,
            connection=connection,
        )

        connection.execute(
            """
            UPDATE stock_master
            SET current_price = ?, latest_price = ?, market_cap = ?, latest_market_cap = ?,
                avg_volume = ?, price_updated_at = ?, updated_at = ?, latest_score = ?,
                latest_signal = ?, trade_gate_blocked = ?, price_stale = ?
            WHERE symbol = ?
            """,
            (
                float(quote.get('price') or 0),
                float(quote.get('price') or 0),
                float(quote.get('marketCap') or 0),
                float(quote.get('marketCap') or 0),
                int(quote.get('volume') or quote.get('avgVolume') or quote.get('volAvg') or 0),
                now,
                now,
                float(scoring['total_score']),
                technical_snapshot.signal,
                1 if technical_snapshot.gate_is_blocked else 0,
                1 if technical_snapshot.price_stale else 0,
                symbol,
            ),
        )

        connection.execute(
            """
            INSERT INTO review_log (symbol, review_type, review_date, summary, outcome, payload_json)
            VALUES (?, 'daily_tracking', ?, ?, ?, ?)
            """,
            (
                symbol,
                now,
                f"{symbol} 日常跟踪更新完成",
                'tracked',
                json.dumps(
                    {
                        'technical_signal': technical_snapshot.signal,
                        'trade_gate_blocked': technical_snapshot.gate_is_blocked,
                        'score': scoring['total_score'],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )

        current_price = float(quote.get('price') or 0)
        previous_gate_blocked = bool(int(stock_row[4] or 0))
        current_gate_blocked = bool(technical_snapshot.gate_is_blocked)
        if previous_gate_blocked != current_gate_blocked:
            event_type = "gate_blocked" if current_gate_blocked else "gate_unblocked"
            summary = f"{symbol} 交易门槛受阻" if current_gate_blocked else f"{symbol} 交易门槛已解除"
            create_notification_event(
                event_type=event_type,
                payload=build_event_payload(
                    event_type=event_type,
                    symbol=symbol,
                    summary=summary,
                    correlation_id=f"tracking-{symbol}-{now}",
                    facts={
                        "technical_signal": technical_snapshot.signal,
                        "trade_gate_status": "blocked" if current_gate_blocked else "unblocked",
                    },
                    actions=[{"action": "view_tracking", "label": "查看跟踪结果"}],
                ),
                correlation_id=f"tracking-{symbol}-{now}",
                symbol=symbol,
                dedupe_key=f"{event_type}:{symbol}:{now[:10]}",
                paths=paths,
                connection=connection,
            )

        current_score = float(scoring['total_score'])
        if previous_score is not None:
            score_delta = round(current_score - previous_score, 2)
            if abs(score_delta) >= 5:
                create_notification_event(
                    event_type="score_change_significant",
                    payload=build_event_payload(
                        event_type="score_change_significant",
                        symbol=symbol,
                        summary=f"{symbol} 跟踪评分显著变化",
                        correlation_id=f"tracking-score-{symbol}-{now}",
                        facts={
                            "previous_score": previous_score,
                            "current_score": current_score,
                            "delta": score_delta,
                            "technical_signal": technical_snapshot.signal,
                        },
                        actions=[{"action": "view_tracking", "label": "查看跟踪结果"}],
                    ),
                    correlation_id=f"tracking-score-{symbol}-{now}",
                    symbol=symbol,
                    dedupe_key=f"score_change_significant:{symbol}:{now[:10]}",
                    paths=paths,
                    connection=connection,
                )
        if previous_price is not None and previous_price > 0:
            price_change_pct = round((current_price - previous_price) / previous_price * 100, 2)
            if abs(price_change_pct) >= 8:
                create_notification_event(
                    event_type="price_alert",
                    payload=build_event_payload(
                        event_type="price_alert",
                        symbol=symbol,
                        summary=f"{symbol} 价格波动显著",
                        correlation_id=f"tracking-price-{symbol}-{now}",
                        facts={
                            "previous_price": previous_price,
                            "current_price": current_price,
                            "price_change_pct": price_change_pct,
                            "technical_signal": technical_snapshot.signal,
                        },
                        actions=[{"action": "view_tracking", "label": "查看跟踪结果"}],
                    ),
                    correlation_id=f"tracking-price-{symbol}-{now}",
                    symbol=symbol,
                    dedupe_key=f"price_alert:{symbol}:{now[:10]}",
                    paths=paths,
                    connection=connection,
                )

        quantity = _holding_quantity(connection, symbol)
        buy_price = _latest_buy_price(connection, symbol)
        return_pct = ((current_price - buy_price) / buy_price * 100) if buy_price else None
        reasons: list[str] = []
        if return_pct is not None and return_pct <= -15:
            reasons.append('stop_loss_15pct')
        if return_pct is not None and return_pct >= 25:
            reasons.append('take_profit_25pct')
        if technical_snapshot.signal == 'avoid' or technical_snapshot.gate_is_blocked:
            reasons.append('technical_reversal')
        if research.key_risks and len(research.key_risks) >= 3:
            reasons.append('risk_cluster')

    if reasons:
        trigger_exit_watch(symbol=symbol, reason=';'.join(reasons), context={'return_pct': return_pct, 'quantity': quantity}, paths=paths)

    return {
        'symbol': symbol,
        'price': current_price,
        'score': float(scoring['total_score']),
        'signal': technical_snapshot.signal,
        'gate_blocked': technical_snapshot.gate_is_blocked,
        'return_pct': return_pct,
        'exit_reasons': reasons,
    }


def execute_reresearch(symbol: str, paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    ensure_schema(paths)
    try:
        stock_context = _load_stock_context(symbol, paths=paths)
        if stock_context is None:
            raise ValueError(f"symbol not found: {symbol}")

        prev_conclusion = _latest_conclusion(symbol, paths=paths)
        result = execute_research_with_two_layer_output(symbol, stock_context, paths=paths)
        if result.quality_level == "fail":
            return {"success": False, "doc_url": "", "conclusion_flipped": False}

        save_two_layer_result(symbol, result, input_data=stock_context, paths=paths)

        doc_url = ""
        try:
            doc_url = create_research_doc(
                symbol=symbol,
                company_name=str(stock_context.get("company_name") or symbol),
                markdown_report=result.markdown_report,
                quality_level="fallback" if result.fallback_used else result.quality_level,
                title_prefix="重研究",
            )
            if doc_url:
                write_doc_url_to_db(symbol, doc_url, paths=paths)
        except FeishuDocError as exc:
            logger.warning("failed to create feishu doc for %s: %s", symbol, exc)

        new_conclusion = _latest_conclusion(symbol, paths=paths)
        conclusion_flipped = prev_conclusion == "值得投" and new_conclusion == "不值得投"
        if conclusion_flipped:
            AlertManager(paths=paths).process_signals(
                symbol,
                [
                    Signal(
                        type="持有逻辑失效",
                        level="action",
                        action="考虑清仓",
                        detail="重研究结论从值得投变为不值得投",
                    )
                ],
            )

        correlation_id = f"reresearch:{symbol}:{_utc_now_iso()}"
        payload = build_event_payload(
            event_type="reresearch_completed",
            symbol=symbol,
            summary=f"[{symbol}] 重研究完成｜quality={result.quality_level}｜flip={'yes' if conclusion_flipped else 'no'}｜doc={'yes' if doc_url else 'no'}",
            correlation_id=correlation_id,
            facts={
                "quality_level": result.quality_level,
                "doc_url": doc_url,
                "conclusion_flipped": conclusion_flipped,
            },
            company_name=str(stock_context.get("company_name") or ""),
        )
        create_notification_event(
            event_type="reresearch_completed",
            payload=payload,
            correlation_id=correlation_id,
            symbol=symbol,
            paths=paths,
        )
        return {"success": True, "doc_url": doc_url, "conclusion_flipped": conclusion_flipped}
    except Exception as exc:
        logger.exception("execute_reresearch failed for %s: %s", symbol, exc)
        return {"success": False, "doc_url": "", "conclusion_flipped": False}
