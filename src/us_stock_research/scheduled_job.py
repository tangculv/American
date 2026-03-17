from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .cli import cmd_monitor, cmd_run
from .config import ProjectPaths
from .event_notifications import build_event_payload, create_notification_event
from .schedule import ScheduleConfigError, scheduled_run_decision

STATE_FILE_NAME = "scheduled_run_state.json"


def state_file_path(paths: ProjectPaths | None = None) -> Path:
    paths = paths or ProjectPaths()
    return paths.data_dir / STATE_FILE_NAME


def load_state(paths: ProjectPaths | None = None) -> dict[str, Any]:
    path = state_file_path(paths)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(data: dict[str, Any], paths: ProjectPaths | None = None) -> None:
    path = state_file_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def schedule_minute_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M%z")


def run_and_notify_command(strategy_name: str, limit_override: int | None, top_n: int, paths: ProjectPaths | None = None) -> int:
    return cmd_run(notify=True, strategy_name=strategy_name, limit_override=limit_override, top_n=top_n, paths=paths)


def daily_run(strategy_name: str, top_n: int, paths: ProjectPaths | None = None) -> int:
    paths = paths or ProjectPaths()
    exit_code = run_and_notify_command(strategy_name, None, top_n, paths=paths)
    cmd_monitor(paths=paths)
    return exit_code


def main(argv: list[str] | None = None, paths: ProjectPaths | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run scheduled stock screening with config-driven timing")
    parser.add_argument('--respect-schedule', action='store_true', default=None)
    parser.add_argument('--force-run', action='store_true', default=None)
    args = parser.parse_args(argv)

    paths = paths or ProjectPaths()
    paths.ensure()

    try:
        decision = scheduled_run_decision(paths=paths, respect_schedule=args.respect_schedule, force_run=args.force_run)
    except ScheduleConfigError as exc:
        print(f"❌ 调度配置无效：{exc}")
        return 1

    scheduled_at = decision['scheduled_at']
    timestamp = scheduled_at.strftime('%Y-%m-%d %H:%M:%S %Z')
    strategy_name = decision['strategy_name']
    top_n = decision['top_n']
    respect_schedule = bool(decision['respect_schedule'])
    force_run = bool(decision['force_run'])

    if not decision['should_run']:
        print(f"[{timestamp}] 跳过本次调度：reason={decision['reason']} cron={decision['cron']} timezone={decision['timezone']} strategy={strategy_name} top_n={top_n}")
        return 0

    if respect_schedule and not force_run:
        state = load_state(paths)
        minute_key = schedule_minute_key(scheduled_at)
        if state.get('last_success_minute') == minute_key:
            print(f"[{timestamp}] 跳过重复调度：minute={minute_key} strategy={strategy_name} top_n={top_n}")
            return 0

    print(f"[{timestamp}] 开始执行定时筛选：reason={decision['reason']} cron={decision['cron']} timezone={decision['timezone']} strategy={strategy_name} top_n={top_n}")
    try:
        exit_code = daily_run(strategy_name, top_n, paths=paths)
    except Exception as exc:
        create_notification_event(
            event_type='system_error',
            payload=build_event_payload(
                event_type='system_error',
                symbol=None,
                summary='定时筛选执行失败',
                correlation_id=f"scheduled-job-{scheduled_at.strftime('%Y%m%d%H%M')}",
                facts={'error_type': exc.__class__.__name__, 'job_id': 'scheduled_screening', 'module': 'scheduled_job', 'retry_count': 0, 'fallback': 'manual_cli'},
                actions=[{'action': 'view_log', 'label': '查看调度日志'}],
            ),
            correlation_id=f"scheduled-job-{scheduled_at.strftime('%Y%m%d%H%M')}",
            dedupe_key=f"system_error:scheduled_screening:{scheduled_at.strftime('%Y-%m-%dT%H:%M')}",
            paths=paths,
        )
        raise

    if exit_code == 0 and respect_schedule and not force_run:
        save_state({'last_success_minute': schedule_minute_key(scheduled_at), 'last_success_at': scheduled_at.isoformat(), 'strategy_name': strategy_name, 'top_n': top_n}, paths)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
