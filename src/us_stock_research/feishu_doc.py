from __future__ import annotations

import json
import os
from datetime import datetime
from urllib import error, request

from .config import ProjectPaths
from .models.database import sqlite_connection
from .models.schema import ensure_schema

FEISHU_AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_DOC_CREATE_URL = "https://open.feishu.cn/open-apis/docx/v1/documents"
FEISHU_DOC_BLOCKS_URL = "https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}/children"


class FeishuDocError(Exception):
    """Feishu document operation failed."""


def _get_feishu_config() -> dict[str, str]:
    return {
        "app_id": os.environ.get("FEISHU_APP_ID", ""),
        "app_secret": os.environ.get("FEISHU_APP_SECRET", ""),
        "folder_token": os.environ.get("FEISHU_DOC_FOLDER_TOKEN", ""),
    }


def _us_eastern_date_str() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


def _post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
        method="POST",
    )
    try:
        with request.urlopen(req) as response:
            content = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise FeishuDocError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except error.URLError as exc:
        raise FeishuDocError(str(exc.reason)) from exc
    try:
        return json.loads(content or "{}")
    except json.JSONDecodeError as exc:
        raise FeishuDocError("Invalid JSON response from Feishu") from exc


def _get_tenant_access_token(app_id: str, app_secret: str) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    data = _post_json(FEISHU_AUTH_URL, payload)
    if int(data.get("code", 0) or 0) != 0:
        raise FeishuDocError(str(data.get("msg") or "Failed to get tenant access token"))
    token = str((data.get("tenant_access_token") or "")).strip()
    if not token:
        raise FeishuDocError("Missing tenant_access_token in Feishu response")
    return token


# --- Block builders ---

def _text_block(content: str) -> dict:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": content}}], "style": {}}}


def _heading_block(content: str, level: int) -> dict:
    block_type = {1: 3, 2: 4, 3: 5}.get(level, 3)
    key = {3: "heading1", 4: "heading2", 5: "heading3"}[block_type]
    return {"block_type": block_type, key: {"elements": [{"text_run": {"content": content}}], "style": {}}}


def _bullet_block(content: str) -> dict:
    return {"block_type": 12, "bullet": {"elements": [{"text_run": {"content": content}}], "style": {}}}


def _markdown_to_blocks(markdown_text: str) -> list[dict]:
    """Convert plain markdown to Feishu doc blocks (paragraphs, headings, bullets)."""
    blocks = []
    for line in markdown_text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            blocks.append(_heading_block(line[4:], 3))
        elif line.startswith("## "):
            blocks.append(_heading_block(line[3:], 2))
        elif line.startswith("# "):
            blocks.append(_heading_block(line[2:], 1))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(_bullet_block(line[2:]))
        elif line.startswith("  - ") or line.startswith("  * "):
            blocks.append(_bullet_block(line[4:]))
        else:
            blocks.append(_text_block(line))
    return blocks


def _write_doc_content(tenant_token: str, document_id: str, markdown_text: str) -> None:
    """Write markdown content into an existing Feishu doc via the blocks API."""
    blocks = _markdown_to_blocks(markdown_text)
    if not blocks:
        return
    # Feishu blocks API limit: 50 blocks per request
    url = FEISHU_DOC_BLOCKS_URL.format(doc_id=document_id, block_id=document_id)
    chunk_size = 50
    for i in range(0, len(blocks), chunk_size):
        chunk = blocks[i: i + chunk_size]
        data = _post_json(url, {"children": chunk}, headers={"Authorization": f"Bearer {tenant_token}"})
        if int(data.get("code", 0) or 0) != 0:
            raise FeishuDocError(f"Failed to write doc blocks: {data.get('msg')}")


def build_markdown_report(symbol: str, company_name: str, structured: dict) -> str:
    """Build a human-readable markdown report from Perplexity structured fields."""
    lines: list[str] = []

    lines.append(f"# [{symbol}] {company_name} 深度研究报告")
    lines.append("")

    summary = structured.get("three_sentence_summary") or ""
    if summary:
        lines.append("## 研究摘要")
        lines.append(summary)
        lines.append("")

    conclusion = structured.get("overall_conclusion") or ""
    if conclusion:
        lines.append(f"**投资结论：{conclusion}**")
        lines.append("")

    # Summary table
    summary_table = structured.get("summary_table") or {}
    if summary_table:
        lines.append("## 基本面快照")
        for k, v in summary_table.items():
            if v is not None and v != "":
                lines.append(f"- {k}: {v}")
        lines.append("")

    # Bull thesis
    bull = structured.get("bull_thesis") or []
    if bull:
        lines.append("## 多头逻辑")
        for item in bull:
            point = item.get("point") or ""
            impact = item.get("impact") or ""
            lines.append(f"- **{point}**：{impact}" if impact else f"- {point}")
        lines.append("")

    # Bear thesis
    bear = structured.get("bear_thesis") or []
    if bear:
        lines.append("## 空头逻辑")
        for item in bear:
            point = item.get("point") or ""
            impact = item.get("impact") or ""
            lines.append(f"- **{point}**：{impact}" if impact else f"- {point}")
        lines.append("")

    # Top risks
    risks = structured.get("top_risks") or []
    if risks:
        lines.append("## 主要风险")
        for r in risks:
            rtype = r.get("type") or ""
            detail = r.get("detail") or ""
            severity = r.get("severity") or ""
            lines.append(f"- [{severity}] {rtype}：{detail}")
        lines.append("")

    # Catalysts
    catalysts = structured.get("catalysts") or []
    if catalysts:
        lines.append("## 催化剂")
        for c in catalysts:
            title = c.get("title") or ""
            impact = c.get("impact") or ""
            timeline = c.get("timeline") or ""
            lines.append(f"- {title}（{timeline}）：{impact}")
        lines.append("")

    # Valuation
    valuation = structured.get("valuation") or {}
    if valuation:
        lines.append("## 估值")
        for k, v in valuation.items():
            if v is not None and v != "":
                lines.append(f"- {k}: {v}")
        lines.append("")

    # Three scenario valuation
    tsv = structured.get("three_scenario_valuation") or {}
    cons = tsv.get("target_price_conservative")
    base = tsv.get("target_price_base")
    opt = tsv.get("target_price_optimistic")
    if any(x is not None for x in [cons, base, opt]):
        lines.append("## 三情景目标价")
        if cons is not None:
            lines.append(f"- 保守：${cons}")
        if base is not None:
            lines.append(f"- 基准：${base}")
        if opt is not None:
            lines.append(f"- 乐观：${opt}")
        lines.append("")

    # Trade plan
    trade = structured.get("trade_plan") or {}
    if trade:
        lines.append("## 交易计划")
        low = trade.get("buy_range_low")
        high = trade.get("buy_range_high")
        pct = trade.get("max_position_pct")
        if low is not None and high is not None:
            lines.append(f"- 买入区间：${low} — ${high}")
        if pct is not None:
            lines.append(f"- 最大仓位：{pct}%")
        for key, label in [
            ("stop_loss_condition", "止损条件"),
            ("add_position_condition", "加仓条件"),
            ("reduce_position_condition", "减仓条件"),
        ]:
            val = trade.get(key) or ""
            if val:
                lines.append(f"- {label}：{val}")
        lines.append("")

    # Invalidation conditions
    inv = structured.get("invalidation_conditions") or []
    if inv:
        lines.append("## 逻辑失效条件")
        for cond in inv:
            lines.append(f"- {cond}")
        lines.append("")

    return "\n".join(lines)


def _create_feishu_doc(tenant_token: str, title: str, content: str, folder_token: str = "") -> str:
    payload = {"title": title}
    if folder_token:
        payload["folder_token"] = folder_token
    data = _post_json(FEISHU_DOC_CREATE_URL, payload, headers={"Authorization": f"Bearer {tenant_token}"})
    if int(data.get("code", 0) or 0) != 0:
        raise FeishuDocError(str(data.get("msg") or "Failed to create Feishu doc"))
    inner = data.get("data") or {}
    document = inner.get("document") or {}
    url = str(document.get("url") or inner.get("url") or "").strip()
    doc_id = str(
        document.get("document_id") or document.get("document_token")
        or inner.get("document_id") or inner.get("document_token") or ""
    ).strip()
    if not doc_id:
        raise FeishuDocError("Missing document_id in Feishu response")

    # Write content blocks
    if content and content.strip():
        _write_doc_content(tenant_token, doc_id, content)

    if url:
        return url
    return f"https://feishu.cn/docx/{doc_id}"


def build_doc_title(
    symbol: str,
    company_name: str,
    quality_level: str,
    title_prefix: str | None = None,
    date_str: str | None = None,
) -> str:
    prefix = "[降级] " if quality_level == "fallback" else ""
    report_type = "重研究报告" if title_prefix == "重研究" else "深度研究报告"
    doc_date = date_str or _us_eastern_date_str()
    return f"{prefix}[{symbol}] {company_name} - {report_type} ({doc_date})"


def create_research_doc(
    symbol: str,
    company_name: str,
    markdown_report: str,
    quality_level: str,
    title_prefix: str | None = None,
) -> str:
    config = _get_feishu_config()
    if not config["app_id"]:
        return ""
    token = _get_tenant_access_token(config["app_id"], config["app_secret"])
    title = build_doc_title(symbol, company_name, quality_level, title_prefix=title_prefix)
    return _create_feishu_doc(token, title, markdown_report, folder_token=config["folder_token"])


def write_doc_url_to_db(symbol: str, doc_url: str, paths: ProjectPaths | None = None) -> None:
    if not doc_url:
        return
    ensure_schema(paths)
    with sqlite_connection(paths) as connection:
        row = connection.execute(
            "SELECT id FROM research_analysis WHERE symbol = ? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row is None:
            return
        connection.execute(
            "UPDATE research_analysis SET feishu_doc_url = ? WHERE id = ?",
            (doc_url, int(row[0])),
        )
