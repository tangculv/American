from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import ProjectPaths, load_settings, load_strategy
from .fmp_client import FMPClient
from .models.screening_repo import persist_screening_run
from .event_notifications import build_event_payload, create_notification_event
from .utils import new_correlation_id
from .research_queue import build_research_batch, increment_hit_count


class ScreeningServiceError(RuntimeError):
    """Raised when the screening workflow cannot produce usable output."""


def run_screening(
    strategy_name: str,
    limit_override: int | None = None,
    top_n: int | None = None,
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    paths.ensure()
    settings = load_settings()
    strategy = load_strategy(strategy_name, paths)

    screen = dict(strategy.get("screen", {}))
    ranking = dict(strategy.get("ranking", {}))
    effective_limit = limit_override or int(screen.get("limit", 50))
    effective_top_n = max(1, top_n if top_n is not None else int(ranking.get("top_n", 10)))

    client = FMPClient(
        api_key=settings.fmp_api_key,
        base_url=settings.fmp_base_url,
        timeout=settings.request_timeout,
    )

    candidates = client.company_screener(
        market_cap_min=int(screen.get("market_cap_min", 500_000_000)),
        market_cap_max=int(screen.get("market_cap_max", 100_000_000_000)),
        volume_min=int(screen.get("volume_min", 1_000_000)),
        sector=str(screen.get("sector", "Technology")),
        exchange=str(screen.get("exchange", "NASDAQ")),
        limit=effective_limit,
        beta_min=screen.get("beta_min"),
        beta_max=screen.get("beta_max"),
    )

    from .cli import evaluate_candidates, write_outputs

    screened_stocks = evaluate_candidates(client, candidates, ranking)
    ranked = [
        stock for stock in screened_stocks if stock.get("scoreDetail", {}).get("eligibility", {}).get("passed")
    ][: max(3, effective_top_n)]

    generated_at = datetime.now()
    display_name = str(strategy.get("name", strategy_name))
    correlation_id = new_correlation_id()
    persist_screening_run(
        strategy_key=strategy_name,
        strategy_display_name=display_name,
        screened_stocks=screened_stocks,
        ranked_stocks=ranked,
        generated_at=generated_at,
        correlation_id=correlation_id,
        ranking=ranking,
        paths=paths,
    )
    normalized_candidates = []
    for stock in screened_stocks:
        symbol = str(stock.get("symbol") or "").strip()
        if not symbol:
            continue
        increment_hit_count(symbol, paths=paths)
        normalized_candidates.append({
            "symbol": symbol,
            "initial_score": stock.get("score"),
        })
    research_batch = build_research_batch(normalized_candidates, paths=paths)
    if ranked:
        top = ranked[0]
        create_notification_event(
            event_type="strategy_hit",
            payload=build_event_payload(
                event_type="strategy_hit",
                symbol=str(top.get("symbol") or "").strip() or None,
                summary=f"{display_name} 发现候选 {len(ranked)} 只",
                correlation_id=correlation_id,
                facts={
                    "strategy_name": display_name,
                    "candidate_count": len(ranked),
                    "top_symbol": top.get("symbol"),
                    "top_score": top.get("score"),
                },
                actions=[{"action": "view_watchlist", "label": "查看候选清单"}],
            ),
            correlation_id=correlation_id,
            symbol=str(top.get("symbol") or "").strip() or None,
            dedupe_key=f"strategy_hit:{strategy_name}:{generated_at.strftime('%Y-%m-%dT%H')}"
            ,paths=paths,
        )
    if not ranked:
        raise ScreeningServiceError("未获得可用候选股，请检查 API key、网络或筛选条件。")

    outputs = write_outputs(paths, ranked, display_name, timestamp=generated_at)

    return {
        "generatedAt": generated_at.isoformat(),
        "strategyName": display_name,
        "strategyKey": strategy_name,
        "stockCount": len(ranked),
        "stocks": ranked,
        "topStocks": ranked[:3],
        "research_batch": research_batch,
        "allRoePending": bool(ranked) and all(
            stock.get("scoreDetail", {}).get("tier", {}).get("code") == "roe_pending"
            for stock in ranked
        ),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "rankingNotes": str(ranking.get("notes", "PE/PB + ROE + 财务健康 + 市值")),
    }
