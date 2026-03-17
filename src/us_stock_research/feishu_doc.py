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
    token = str(document.get("document_id") or document.get("document_token") or inner.get("document_id") or inner.get("document_token") or "").strip()
    if url:
        return url
    if token:
        return f"https://open.feishu.cn/document/uQjL04CN/{token}"
    raise FeishuDocError("Missing document URL in Feishu response")


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
