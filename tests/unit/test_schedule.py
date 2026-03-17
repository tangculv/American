from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths, save_app_config  # noqa: E402
from us_stock_research.schedule import cron_matches_datetime, schedule_runtime_context, scheduled_run_decision  # noqa: E402
from us_stock_research.scheduled_job import load_state, main as scheduled_job_main  # noqa: E402


def make_paths(root: Path) -> ProjectPaths:
    return ProjectPaths(
        root=root,
        config_dir=root / "config",
        strategy_dir=root / "config" / "strategies",
        app_config_path=root / "config" / "app.yaml",
        outputs_dir=root / "outputs" / "fmp-screening",
        watchlist_dir=root / "watchlist",
        data_dir=root / "data",
        database_path=root / "data" / "stock_research.db",
        logs_dir=root / "logs",
    )


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def save_schedule(
        self,
        *,
        enabled: bool = True,
        cron: str = "0 9 * * 0",
        timezone: str = "Asia/Shanghai",
        run_strategy: str = "low_valuation_quality",
        top_n: int = 10,
    ) -> None:
        save_app_config(
            {
                "schedule": {
                    "enabled": enabled,
                    "cron": cron,
                    "timezone": timezone,
                    "run_strategy": run_strategy,
                    "top_n": top_n,
                }
            },
            self.paths,
        )

    def test_schedule_runtime_context_reads_config_and_env_override(self) -> None:
        self.save_schedule(run_strategy="weekly_value", top_n=12)

        context = schedule_runtime_context(paths=self.paths)
        self.assertTrue(context["enabled"])
        self.assertEqual(context["strategy_name"], "weekly_value")
        self.assertEqual(context["top_n"], 12)
        self.assertEqual(context["cron"], "0 9 * * 0")
        self.assertEqual(context["timezone"], "Asia/Shanghai")

        overridden = schedule_runtime_context(
            paths=self.paths,
            env={
                "US_STOCK_STRATEGY": "manual_override",
                "US_STOCK_TOP_N": "8",
                "US_STOCK_REQUIRE_SCHEDULE_MATCH": "1",
            },
        )
        self.assertEqual(overridden["strategy_name"], "manual_override")
        self.assertEqual(overridden["top_n"], 8)
        self.assertTrue(overridden["respect_schedule"])

    def test_cron_matches_datetime_for_weekly_schedule(self) -> None:
        scheduled_time = datetime(2026, 3, 15, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        off_time = datetime(2026, 3, 15, 9, 1, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertTrue(cron_matches_datetime("0 9 * * 0", scheduled_time))
        self.assertFalse(cron_matches_datetime("0 9 * * 0", off_time))

    def test_scheduled_run_decision_respects_enabled_flag(self) -> None:
        self.save_schedule(enabled=False, run_strategy="disabled_strategy", top_n=6)
        scheduled_time = datetime(2026, 3, 15, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        manual = scheduled_run_decision(paths=self.paths, now=scheduled_time, respect_schedule=False)
        self.assertTrue(manual["should_run"])
        self.assertEqual(manual["reason"], "manual")

        guarded = scheduled_run_decision(paths=self.paths, now=scheduled_time, respect_schedule=True)
        self.assertFalse(guarded["should_run"])
        self.assertEqual(guarded["reason"], "disabled")
        self.assertEqual(guarded["strategy_name"], "disabled_strategy")
        self.assertEqual(guarded["top_n"], 6)

    def test_scheduled_run_decision_reports_due_and_not_due(self) -> None:
        self.save_schedule(enabled=True, cron="0 9 * * 0")
        due_time = datetime(2026, 3, 15, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        later_time = datetime(2026, 3, 15, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        due = scheduled_run_decision(paths=self.paths, now=due_time, respect_schedule=True)
        not_due = scheduled_run_decision(paths=self.paths, now=later_time, respect_schedule=True)

        self.assertTrue(due["should_run"])
        self.assertEqual(due["reason"], "due")
        self.assertFalse(not_due["should_run"])
        self.assertEqual(not_due["reason"], "not_due")

    def test_scheduled_job_main_skips_duplicate_minute(self) -> None:
        scheduled_at = datetime(2026, 3, 15, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        decision = {
            "enabled": True,
            "cron": "0 9 * * 0",
            "timezone": "Asia/Shanghai",
            "strategy_name": "low_valuation_quality",
            "top_n": 10,
            "respect_schedule": True,
            "force_run": False,
            "scheduled_at": scheduled_at,
            "should_run": True,
            "reason": "due",
        }

        with patch("us_stock_research.scheduled_job.scheduled_run_decision", return_value=decision), patch(
            "us_stock_research.scheduled_job.run_and_notify_command",
            return_value=0,
        ) as mocked_run:
            first_exit = scheduled_job_main(["--respect-schedule"], paths=self.paths)
            second_exit = scheduled_job_main(["--respect-schedule"], paths=self.paths)

        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 0)
        mocked_run.assert_called_once_with("low_valuation_quality", None, 10, paths=self.paths)
        state = load_state(self.paths)
        self.assertEqual(state["last_success_minute"], "2026-03-15T09:00+0800")


if __name__ == "__main__":
    unittest.main()
