from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import (
    DEFAULT_SCHEDULE_CRON,
    DEFAULT_SCHEDULE_TIMEZONE,
    DEFAULT_STRATEGY_NAME,
    ProjectPaths,
    load_app_config,
)

TRUTHY_VALUES = {"1", "true", "yes", "on"}


class ScheduleConfigError(ValueError):
    """Raised when schedule config cannot be parsed."""


def truthy_flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUTHY_VALUES


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return truthy_flag(value)
    return bool(value)


def load_schedule_config(paths: ProjectPaths | None = None) -> dict[str, Any]:
    schedule = load_app_config(paths).get("schedule", {})
    if not isinstance(schedule, dict):
        raise ScheduleConfigError("schedule 配置必须是对象。")
    return schedule


def _coerce_positive_int(value: Any, field_name: str, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleConfigError(f"{field_name} 必须是整数。") from exc
    if number <= 0:
        raise ScheduleConfigError(f"{field_name} 必须大于 0。")
    return number


def schedule_runtime_context(
    *,
    env: Mapping[str, str] | None = None,
    paths: ProjectPaths | None = None,
    respect_schedule: bool | None = None,
    force_run: bool | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    schedule = load_schedule_config(paths)

    strategy_name = str(env.get("US_STOCK_STRATEGY") or schedule.get("run_strategy") or DEFAULT_STRATEGY_NAME).strip()
    if not strategy_name:
        strategy_name = DEFAULT_STRATEGY_NAME

    top_n = _coerce_positive_int(env.get("US_STOCK_TOP_N", schedule.get("top_n")), "schedule.top_n", 10)
    cron = str(schedule.get("cron") or DEFAULT_SCHEDULE_CRON).strip() or DEFAULT_SCHEDULE_CRON
    timezone_name = str(schedule.get("timezone") or DEFAULT_SCHEDULE_TIMEZONE).strip() or DEFAULT_SCHEDULE_TIMEZONE
    enabled = coerce_bool(schedule.get("enabled"))

    return {
        "enabled": enabled,
        "cron": cron,
        "timezone": timezone_name,
        "strategy_name": strategy_name,
        "top_n": top_n,
        "respect_schedule": truthy_flag(env.get("US_STOCK_REQUIRE_SCHEDULE_MATCH")) if respect_schedule is None else respect_schedule,
        "force_run": truthy_flag(env.get("US_STOCK_FORCE_RUN")) if force_run is None else force_run,
    }


def current_time_in_timezone(timezone_name: str, now: datetime | None = None) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleConfigError(f"无法识别时区：{timezone_name}") from exc

    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def _parse_cron_number(value: str, field_name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ScheduleConfigError(f"cron 的 {field_name} 字段无效：{value}") from exc
    if number < minimum or number > maximum:
        raise ScheduleConfigError(f"cron 的 {field_name} 字段超出范围：{value}")
    return number


def _expand_cron_token(
    token: str,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
    raw_maximum: int,
    normalize: Callable[[int], int] | None = None,
) -> set[int]:
    step = 1
    range_part = token
    if "/" in token:
        range_part, step_text = token.split("/", 1)
        step = _parse_cron_number(step_text, field_name, 1, raw_maximum)

    if range_part == "*":
        start = minimum
        end = raw_maximum
    elif "-" in range_part:
        start_text, end_text = range_part.split("-", 1)
        start = _parse_cron_number(start_text, field_name, minimum, raw_maximum)
        end = _parse_cron_number(end_text, field_name, minimum, raw_maximum)
        if start > end:
            raise ScheduleConfigError(f"cron 的 {field_name} 范围无效：{token}")
    else:
        value = _parse_cron_number(range_part, field_name, minimum, raw_maximum)
        normalized = normalize(value) if normalize else value
        if normalized < minimum or normalized > maximum:
            raise ScheduleConfigError(f"cron 的 {field_name} 字段超出范围：{token}")
        return {normalized}

    values: set[int] = set()
    for value in range(start, end + 1, step):
        normalized = normalize(value) if normalize else value
        if normalized < minimum or normalized > maximum:
            raise ScheduleConfigError(f"cron 的 {field_name} 字段超出范围：{value}")
        values.add(normalized)
    return values


def _parse_cron_field(
    field: str,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
    raw_maximum: int | None = None,
    normalize: Callable[[int], int] | None = None,
) -> set[int] | None:
    field = field.strip()
    if field == "*":
        return None

    values: set[int] = set()
    effective_raw_max = raw_maximum if raw_maximum is not None else maximum
    for token in field.split(","):
        token = token.strip()
        if not token:
            raise ScheduleConfigError(f"cron 的 {field_name} 字段不能为空。")
        values.update(
            _expand_cron_token(
                token,
                field_name=field_name,
                minimum=minimum,
                maximum=maximum,
                raw_maximum=effective_raw_max,
                normalize=normalize,
            )
        )
    return values


def parse_cron_expression(expression: str) -> dict[str, set[int] | None]:
    parts = expression.split()
    if len(parts) != 5:
        raise ScheduleConfigError("cron 表达式必须是 5 段：分钟 小时 日 月 周。")

    minute, hour, day_of_month, month, day_of_week = parts
    return {
        "minute": _parse_cron_field(minute, field_name="minute", minimum=0, maximum=59),
        "hour": _parse_cron_field(hour, field_name="hour", minimum=0, maximum=23),
        "day_of_month": _parse_cron_field(day_of_month, field_name="day_of_month", minimum=1, maximum=31),
        "month": _parse_cron_field(month, field_name="month", minimum=1, maximum=12),
        "day_of_week": _parse_cron_field(
            day_of_week,
            field_name="day_of_week",
            minimum=0,
            maximum=6,
            raw_maximum=7,
            normalize=lambda value: 0 if value == 7 else value,
        ),
    }


def _matches(field_values: set[int] | None, value: int) -> bool:
    return field_values is None or value in field_values


def cron_matches_datetime(expression: str, dt: datetime) -> bool:
    cron = parse_cron_expression(expression)
    if not _matches(cron["minute"], dt.minute):
        return False
    if not _matches(cron["hour"], dt.hour):
        return False
    if not _matches(cron["month"], dt.month):
        return False

    day_of_month_values = cron["day_of_month"]
    day_of_week_values = cron["day_of_week"]
    day_of_month_match = _matches(day_of_month_values, dt.day)
    cron_day_of_week = (dt.weekday() + 1) % 7
    day_of_week_match = _matches(day_of_week_values, cron_day_of_week)

    if day_of_month_values is not None and day_of_week_values is not None:
        return day_of_month_match or day_of_week_match
    return day_of_month_match and day_of_week_match


def scheduled_run_decision(
    *,
    env: Mapping[str, str] | None = None,
    paths: ProjectPaths | None = None,
    now: datetime | None = None,
    respect_schedule: bool | None = None,
    force_run: bool | None = None,
) -> dict[str, Any]:
    context = schedule_runtime_context(
        env=env,
        paths=paths,
        respect_schedule=respect_schedule,
        force_run=force_run,
    )
    scheduled_at = current_time_in_timezone(context["timezone"], now)

    if context["force_run"]:
        reason = "forced"
        should_run = True
    elif not context["respect_schedule"]:
        reason = "manual"
        should_run = True
    elif not context["enabled"]:
        reason = "disabled"
        should_run = False
    elif cron_matches_datetime(context["cron"], scheduled_at):
        reason = "due"
        should_run = True
    else:
        reason = "not_due"
        should_run = False

    return {
        **context,
        "scheduled_at": scheduled_at,
        "should_run": should_run,
        "reason": reason,
    }
