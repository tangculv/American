from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DEFAULT_STRATEGY_NAME, ProjectPaths, load_strategy
from .models import ensure_schema, sqlite_connection

RESULT_PREFIX = "FMP筛选结果_"
REPORT_PREFIX = "FMP筛选报告_"


def list_result_files(paths: ProjectPaths | None = None) -> list[Path]:
    paths = paths or ProjectPaths()
    if not paths.outputs_dir.exists():
        return []
    return sorted(paths.outputs_dir.glob(f"{RESULT_PREFIX}*.json"), reverse=True)


def latest_result_file(paths: ProjectPaths | None = None) -> Path | None:
    files = list_result_files(paths)
    return files[0] if files else None


def extract_result_slug(result_path: Path) -> str:
    return result_path.stem.replace(RESULT_PREFIX, "", 1)


def extract_generated_at(result_path: Path) -> datetime:
    slug = extract_result_slug(result_path)
    return datetime.strptime(slug, "%Y%m%d_%H%M%S")


def _stable_output_paths(paths: ProjectPaths) -> dict[str, str]:
    return {
        "candidate": str(paths.watchlist_dir / "候选股-自动筛选.md"),
        "top3": str(paths.watchlist_dir / "本周Top3.md"),
        "watchlist": str(paths.watchlist_dir / "候选股.md"),
    }


def _default_output_paths_from_slug(paths: ProjectPaths, slug: str) -> dict[str, str]:
    outputs = _stable_output_paths(paths)
    outputs.update(
        {
            "json": str(paths.outputs_dir / f"{RESULT_PREFIX}{slug}.json"),
            "report": str(paths.outputs_dir / f"{REPORT_PREFIX}{slug}.md"),
        }
    )
    return outputs


def _default_output_paths(paths: ProjectPaths, result_path: Path) -> dict[str, str]:
    return _default_output_paths_from_slug(paths, extract_result_slug(result_path))


def _default_output_paths_from_generated_at(paths: ProjectPaths, generated_at: str) -> dict[str, str]:
    try:
        slug = datetime.fromisoformat(generated_at).strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return _stable_output_paths(paths)
    return _default_output_paths_from_slug(paths, slug)


def _strategy_display_name(strategy_name_hint: str | None, paths: ProjectPaths) -> str:
    if not strategy_name_hint:
        return DEFAULT_STRATEGY_NAME
    try:
        strategy = load_strategy(strategy_name_hint, paths)
        return str(strategy.get("name", strategy_name_hint))
    except Exception:
        return strategy_name_hint


def _json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _latest_ranked_run(
    paths: ProjectPaths,
    strategy_name_hint: str | None = None,
) -> tuple[str, str] | None:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        if strategy_name_hint:
            row = connection.execute(
                """
                SELECT strategy_name, generated_at
                FROM ranking_snapshot
                WHERE strategy_name = ?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (strategy_name_hint,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT strategy_name, generated_at
                FROM ranking_snapshot
                ORDER BY generated_at DESC
                LIMIT 1
                """
            ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def _load_ranked_stocks(paths: ProjectPaths, strategy_key: str, generated_at: str) -> list[dict[str, Any]]:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        rows = connection.execute(
            """
            SELECT
                rs.symbol,
                rs.rank_position,
                rs.total_score,
                sh.screen_payload_json,
                sb.detail_json
            FROM ranking_snapshot rs
            LEFT JOIN strategy_hit sh
                ON sh.symbol = rs.symbol
               AND sh.strategy_name = rs.strategy_name
               AND sh.hit_at = rs.generated_at
            LEFT JOIN scoring_breakdown sb
                ON sb.symbol = rs.symbol
               AND sb.strategy_name = rs.strategy_name
               AND sb.scored_at = rs.generated_at
            WHERE rs.strategy_name = ? AND rs.generated_at = ?
            ORDER BY rs.rank_position ASC, rs.symbol ASC
            """,
            (strategy_key, generated_at),
        ).fetchall()

    stocks: list[dict[str, Any]] = []
    for row in rows:
        stock = _json_dict(row[3])
        detail = _json_dict(row[4])
        stock["symbol"] = str(stock.get("symbol") or row[0])
        stock["score"] = float(row[2] or stock.get("score", 0) or 0)
        if detail:
            stock["scoreDetail"] = detail
        stocks.append(stock)
    return stocks


def _load_run_payload(paths: ProjectPaths, strategy_key: str, generated_at: str) -> dict[str, Any]:
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            """
            SELECT payload_json
            FROM audit_log
            WHERE entity_type = 'screening_run'
              AND action = 'screening_persisted'
              AND entity_key = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (f"{strategy_key}:{generated_at}",),
        ).fetchone()
    if row is None:
        return {}
    return _json_dict(row[0])


def load_latest_result_from_db(
    paths: ProjectPaths | None = None,
    strategy_name_hint: str | None = None,
) -> dict[str, Any] | None:
    paths = paths or ProjectPaths()
    latest_run = _latest_ranked_run(paths, strategy_name_hint)
    if latest_run is None:
        return None

    strategy_key, generated_at = latest_run
    stocks = _load_ranked_stocks(paths, strategy_key, generated_at)
    if not stocks:
        return None

    run_payload = _load_run_payload(paths, strategy_key, generated_at)
    outputs = _default_output_paths_from_generated_at(paths, generated_at)
    strategy_name = str(
        run_payload.get("strategy_display_name")
        or _strategy_display_name(strategy_key if strategy_name_hint is None else strategy_name_hint, paths)
    )
    all_roe_pending = bool(stocks) and all(
        stock.get("scoreDetail", {}).get("tier", {}).get("code") == "roe_pending"
        for stock in stocks
    )

    return {
        "generatedAt": generated_at,
        "strategyName": strategy_name,
        "strategyKey": strategy_key,
        "stockCount": len(stocks),
        "stocks": stocks,
        "topStocks": stocks[:3],
        "allRoePending": all_roe_pending,
        "outputs": outputs,
        "resultFile": str(outputs.get("json", "")),
    }


def normalize_result_payload(
    payload: Any,
    result_path: Path,
    paths: ProjectPaths | None = None,
    strategy_name_hint: str | None = None,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    generated_at = extract_generated_at(result_path)
    outputs = _default_output_paths(paths, result_path)

    if isinstance(payload, dict) and isinstance(payload.get("stocks"), list):
        stocks = payload.get("stocks", [])
        outputs.update({key: str(value) for key, value in dict(payload.get("outputs", {})).items() if value})
        strategy_name = str(payload.get("strategyName") or _strategy_display_name(strategy_name_hint, paths))
        generated_value = payload.get("generatedAt")
        generated_at_iso = str(generated_value) if generated_value else generated_at.isoformat()
    elif isinstance(payload, list):
        stocks = payload
        strategy_name = _strategy_display_name(strategy_name_hint, paths)
        generated_at_iso = generated_at.isoformat()
    else:
        raise ValueError(f"Unsupported result payload in {result_path}")

    top_stocks = stocks[:3]
    all_roe_pending = bool(stocks) and all(
        stock.get("scoreDetail", {}).get("tier", {}).get("code") == "roe_pending"
        for stock in stocks
    )

    return {
        "generatedAt": generated_at_iso,
        "strategyName": strategy_name,
        "stockCount": len(stocks),
        "stocks": stocks,
        "topStocks": top_stocks,
        "allRoePending": all_roe_pending,
        "outputs": outputs,
        "resultFile": str(result_path),
    }


def load_result(
    result_path: Path,
    paths: ProjectPaths | None = None,
    strategy_name_hint: str | None = None,
) -> dict[str, Any]:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    return normalize_result_payload(payload, result_path, paths=paths, strategy_name_hint=strategy_name_hint)


def load_latest_result(
    paths: ProjectPaths | None = None,
    strategy_name_hint: str | None = None,
) -> dict[str, Any] | None:
    paths = paths or ProjectPaths()
    latest_from_db = load_latest_result_from_db(paths, strategy_name_hint=strategy_name_hint)
    if latest_from_db is not None:
        return latest_from_db

    result_path = latest_result_file(paths)
    if result_path is None:
        return None
    return load_result(result_path, paths=paths, strategy_name_hint=strategy_name_hint)
