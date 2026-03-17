from __future__ import annotations

from typing import Any, Iterable

import requests


class FeishuSenderError(RuntimeError):
    """Raised when a Feishu webhook message cannot be delivered."""


def _check_response_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FeishuSenderError("Feishu webhook returned invalid JSON")

    code = payload.get("code")
    status_code = payload.get("StatusCode")
    if code not in (None, 0) or status_code not in (None, 0):
        message = payload.get("msg") or payload.get("StatusMessage") or "unknown error"
        raise FeishuSenderError(f"Feishu webhook rejected message: {message}")
    return payload


def send_message(payload: dict[str, Any], webhook_url: str, timeout: int = 10) -> dict[str, Any]:
    url = webhook_url.strip()
    if not url:
        raise FeishuSenderError("FEISHU_WEBHOOK_URL is missing.")

    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        response.raise_for_status()
        return _check_response_payload(response.json())
    except requests.RequestException as exc:
        raise FeishuSenderError(f"Feishu webhook request failed: {exc}") from exc
    except ValueError as exc:
        raise FeishuSenderError("Feishu webhook returned invalid JSON") from exc


def send_text(text: str, webhook_url: str, timeout: int = 10) -> dict[str, Any]:
    return send_message({"msg_type": "text", "content": {"text": text}}, webhook_url=webhook_url, timeout=timeout)


def build_post_payload(title: str, lines: Iterable[str]) -> dict[str, Any]:
    content = []
    for line in lines:
        text = str(line).strip()
        content.append([{"tag": "text", "text": text or " "}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title or "通知",
                    "content": content,
                }
            }
        },
    }


def send_post(title: str, lines: Iterable[str], webhook_url: str, timeout: int = 10) -> dict[str, Any]:
    return send_message(build_post_payload(title, lines), webhook_url=webhook_url, timeout=timeout)


def send_markdown_summary(title: str, content: str, webhook_url: str, timeout: int = 10) -> dict[str, Any]:
    full_text = f"{title}\n\n{content}" if title else content
    return send_text(full_text, webhook_url=webhook_url, timeout=timeout)
