from __future__ import annotations

from datetime import UTC, date, datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat().replace('+00:00', '')


def utc_today() -> date:
    return utc_now().date()
