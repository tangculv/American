from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any, Callable

from dotenv import load_dotenv

from .config import DEFAULT_FEISHU_DIGEST_MODE, ProjectPaths, load_app_config
from .feishu_sender import send_post
from .results_repo import load_latest_result

FIXTURE_SYMBOL_PATTERN = re.compile(r"^STK\d+$")
OUTPUT_ORDER = ("report", "watchlist", "top3", "candidate", "json")


class NotificationConfigError(RuntimeError):
    """Raised when notifications cannot be sent because config is incomplete."""


def _format_timestamp(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def _format_number(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_price(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_percent(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_market_cap(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric >= 1_000_000_000_000:
        return f"${numeric / 1_000_000_000_000:.2f}T"
    return f"${numeric / 1_000_000_000:.2f}B"


def _generated_slug(run_data: dict[str, Any]) -> str | None:
    generated_at = str(run_data.get("generatedAt", "")).strip()
    if not generated_at:
        return None
    try:
        return datetime.fromisoformat(generated_at).strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _project_path(value: Any, paths: ProjectPaths) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = paths.root / candidate
    candidate = candidate.resolve(strict=False)
    root = paths.root.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _relative_project_path(value: Path | None, paths: ProjectPaths) -> str | None:
    if value is None:
        return None
    candidate = value.resolve(strict=False)
    root = paths.root.resolve(strict=False)
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return None


def _derived_output_paths(run_data: dict[str, Any], paths: ProjectPaths) -> dict[str, Path]:
    slug = _generated_slug(run_data)
    if not slug:
        return {}
    return {
        "report": paths.outputs_dir / f"FMP筛选报告_{slug}.md",
        "json": paths.outputs_dir / f"FMP筛选结果_{slug}.json",
        "candidate": paths.watchlist_dir / "候选股-自动筛选.md",
        "top3": paths.watchlist_dir / "本周Top3.md",
        "watchlist": paths.watchlist_dir / "候选股.md",
    }


def _notification_output_paths(run_data: dict[str, Any], paths: ProjectPaths) -> dict[str, str]:
    outputs = dict(run_data.get("outputs", {}))
    derived = _derived_output_paths(run_data, paths)
    resolved: dict[str, str] = {}

    for key in OUTPUT_ORDER:
        path = _project_path(outputs.get(key), paths)
        if path is None or not path.exists():
            fallback = derived.get(key)
            if fallback is not None and fallback.exists():
                path = fallback
        display_path = _relative_project_path(path, paths)
        if display_path:
            resolved[key] = display_path
    return resolved


def _looks_like_fixture_payload(run_data: dict[str, Any]) -> bool:
    stocks = list(run_data.get("stocks", []))
    sample = stocks[:3]
    symbols = [str(stock.get("symbol", "")).strip() for stock in sample if str(stock.get("symbol", "")).strip()]
    company_names = [
        str(stock.get("companyName", "")).strip().lower()
        for stock in sample
        if str(stock.get("companyName", "")).strip()
    ]
    outputs = dict(run_data.get("outputs", {}))

    if symbols and all(FIXTURE_SYMBOL_PATTERN.fullmatch(symbol) for symbol in symbols):
        return True
    if company_names and all(name.startswith("stock ") for name in company_names):
        return True
    return any(str(value or "").strip().startswith("/tmp/") for value in outputs.values())


def _recommendation(score: Any) -> str:
    try:
        numeric = float(score or 0)
    except (TypeError, ValueError):
        return "待观察"
    if numeric >= 60:
        return "强烈关注"
    if numeric >= 45:
        return "优先观察"
    if numeric >= 30:
        return "可跟踪"
    return "暂不优先"


def _top_stocks_for_digest(run_data: dict[str, Any], digest_mode: str) -> list[dict[str, Any]]:
    stocks = list(run_data.get("stocks", []))
    return stocks if digest_mode == "full_watchlist" else stocks[:3]


def build_report_digest(run_data: dict[str, Any], digest_mode: str = DEFAULT_FEISHU_DIGEST_MODE) -> str:
    return "\n".join(build_report_digest_lines(run_data, digest_mode=digest_mode))


def build_report_digest_lines(run_data: dict[str, Any], digest_mode: str = DEFAULT_FEISHU_DIGEST_MODE) -> list[str]:
    stocks = list(run_data.get("stocks", []))
    strategy_name = str(run_data.get("strategyName", "未知策略"))
    generated_at = _format_timestamp(str(run_data.get("generatedAt", "")))
    digest_stocks = _top_stocks_for_digest(run_data, digest_mode)

    lines = [
        "详细报告摘要",
        f"运行时间：{generated_at}",
        f"策略：{strategy_name}",
        f"共筛出 {len(stocks)} 只股票",
    ]

    if not digest_stocks:
        lines.append("本轮没有符合条件的候选股")
        return lines

    for index, stock in enumerate(digest_stocks, start=1):
        detail = stock.get("scoreDetail", {})
        metrics = detail.get("metrics", {})
        tier = detail.get("tier", {})
        valuation_notes = "；".join(detail.get("valuation", {}).get("notes", [])) or "暂无"
        profitability_notes = "；".join(detail.get("profitability", {}).get("notes", [])) or "暂无"
        health_notes = "；".join(detail.get("financial_health", {}).get("notes", [])) or "暂无"
        scale_notes = "；".join(detail.get("scale", {}).get("notes", [])) or "暂无"

        lines.extend(
            [
                f"Top {index}｜{stock.get('symbol', '')} - {stock.get('companyName', '')}",
                f"建议级别：{_recommendation(stock.get('score'))}",
                f"评分：{_format_number(stock.get('score'))} ｜ 分层：{tier.get('label', '待研究')}",
                f"分层说明：{tier.get('summary', '暂无说明')}",
                f"价格 / 市值：{_format_price(stock.get('price'))} ｜ {_format_market_cap(stock.get('marketCap', metrics.get('marketCap')))}",
                f"估值指标：PE {_format_number(metrics.get('pe'))} ｜ PB {_format_number(metrics.get('pb'))}",
                f"盈利指标：ROE {_format_percent(metrics.get('roe'))} ｜ 净利率 {_format_percent(metrics.get('netProfitMargin'))}",
                f"财务指标：D/E {_format_number(metrics.get('debtToEquity'))} ｜ 流动比率 {_format_number(metrics.get('currentRatio'))}",
                f"估值亮点：{valuation_notes}",
                f"盈利亮点：{profitability_notes}",
                f"财务亮点：{health_notes}",
                f"规模补充：{scale_notes}",
            ]
        )

    return lines


def build_notification_lines(
    run_data: dict[str, Any],
    digest_mode: str = DEFAULT_FEISHU_DIGEST_MODE,
    paths: ProjectPaths | None = None,
) -> list[str]:
    paths = paths or ProjectPaths()
    stocks = list(run_data.get("stocks", []))
    generated_at = _format_timestamp(str(run_data.get("generatedAt", "")))
    strategy_name = str(run_data.get("strategyName", "未知策略"))
    stock_count = int(run_data.get("stockCount", len(stocks)))
    digest_stocks = _top_stocks_for_digest(run_data, digest_mode)

    lines = [
        "美股选股筛选通知",
        f"运行时间：{generated_at}",
        f"策略：{strategy_name}",
        f"候选数量：{stock_count}",
        "",
        "一眼先看这里",
    ]

    if not digest_stocks:
        lines.append("本轮没有符合条件的候选股")
    else:
        for index, stock in enumerate(digest_stocks, start=1):
            tier = stock.get("scoreDetail", {}).get("tier", {}).get("label", "待研究")
            score = _format_number(stock.get("score"))
            price = _format_price(stock.get("price"))
            lines.append(f"Top {index}：{stock.get('symbol', '')} ｜ {tier} ｜ 分数 {score} ｜ 价格 {price}")

    if run_data.get("allRoePending"):
        lines.extend(["", "风险提示：本轮全部为 ROE待补充，盈利质量还要二次核验。"])

    lines.extend(["", *build_report_digest_lines(run_data, digest_mode=digest_mode)])

    output_paths = _notification_output_paths(run_data, paths)
    if output_paths:
        lines.extend(["", "补充落盘位置"])
        if output_paths.get("report"):
            lines.append(f"Markdown 报告：{output_paths['report']}")
        if output_paths.get("watchlist"):
            lines.append(f"候选清单：{output_paths['watchlist']}")
        if output_paths.get("top3"):
            lines.append(f"Top 3：{output_paths['top3']}")
        if output_paths.get("candidate"):
            lines.append(f"自动筛选详情：{output_paths['candidate']}")
        if output_paths.get("json"):
            lines.append(f"JSON 结果：{output_paths['json']}")
        lines.append("说明：上面已经是可直接看的内容，这些路径只是本地留档。")

    return lines


def build_notification_text(
    run_data: dict[str, Any],
    digest_mode: str = DEFAULT_FEISHU_DIGEST_MODE,
    paths: ProjectPaths | None = None,
) -> str:
    return "\n".join(build_notification_lines(run_data, digest_mode=digest_mode, paths=paths))


def _notification_title(run_data: dict[str, Any]) -> str:
    strategy_name = str(run_data.get("strategyName", "美股选股"))
    generated_at = _format_timestamp(str(run_data.get("generatedAt", "")))
    return f"{strategy_name}｜{generated_at}"


def _notification_settings(paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    app_config = load_app_config(paths)
    notifications = dict(app_config.get("notifications", {}))
    return dict(notifications.get("feishu", {}))


def send_run_notification(
    run_data: dict[str, Any],
    paths: ProjectPaths | None = None,
    sender: Callable[[str, list[str], str], dict[str, Any]] = send_post,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    load_dotenv(paths.root / ".env")
    feishu = _notification_settings(paths)
    if not feishu.get("enabled"):
        raise NotificationConfigError("飞书通知未启用，请在 config/app.yaml 中打开 notifications.feishu.enabled。")

    webhook_url = str(feishu.get("webhook_url", "")).strip() or os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise NotificationConfigError("飞书 webhook 未配置，请在 config/app.yaml 或 .env 中填写 FEISHU_WEBHOOK_URL。")
    if _looks_like_fixture_payload(run_data):
        raise NotificationConfigError("当前通知数据看起来像测试样例，已阻止发送到飞书。")

    digest_mode = str(feishu.get("digest_mode", DEFAULT_FEISHU_DIGEST_MODE) or DEFAULT_FEISHU_DIGEST_MODE)
    title = _notification_title(run_data)
    lines = build_notification_lines(run_data, digest_mode=digest_mode, paths=paths)
    return sender(title, lines, webhook_url)


def send_latest_notification(
    paths: ProjectPaths | None = None,
    strategy_name_hint: str | None = None,
    sender: Callable[[str, list[str], str], dict[str, Any]] = send_post,
) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    latest = load_latest_result(paths, strategy_name_hint=strategy_name_hint)
    if latest is None:
        raise NotificationConfigError("暂无可发送的筛选结果，请先运行一次筛选。")
    return send_run_notification(latest, paths=paths, sender=sender)
