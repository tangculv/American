from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths, save_app_config, save_strategy  # noqa: E402
from us_stock_research.models.screening_repo import persist_screening_run  # noqa: E402
from us_stock_research.event_notifications import build_event_payload, create_notification_event  # noqa: E402
from us_stock_research.models import get_connection  # noqa: E402
from us_stock_research.ui_data import load_dashboard_bundle  # noqa: E402


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


class UiDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        self.paths.ensure()
        save_strategy(
            "low_valuation_quality",
            {
                "name": "低估值高质量科技股",
                "screen": {
                    "limit": 50,
                    "market_cap_min": 500_000_000,
                    "market_cap_max": 100_000_000_000,
                    "volume_min": 1_000_000,
                    "sector": "Technology",
                    "exchange": "NASDAQ",
                },
                "ranking": {
                    "top_n": 10,
                    "gates": {
                        "max_pe": 30,
                        "max_pb": 5,
                        "min_valuation_score": 2,
                        "min_roe_for_quality": 0.1,
                    },
                },
            },
            self.paths,
        )
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "https://example.com/hook",
                        "digest_mode": "top3_only",
                    }
                },
                "schedule": {
                    "enabled": True,
                    "cron": "0 9 * * 1-5",
                    "timezone": "Asia/Shanghai",
                    "run_strategy": "low_valuation_quality",
                    "top_n": 5,
                },
            },
            self.paths,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def sample_stock(self, symbol: str, *, score: float, tier_code: str, tier_label: str, roe: float | None) -> dict[str, object]:
        return {
            "symbol": symbol,
            "companyName": f"{symbol} Corp",
            "price": 123.45,
            "marketCap": 22_500_000_000,
            "score": score,
            "scoreDetail": {
                "tier": {
                    "code": tier_code,
                    "label": tier_label,
                    "summary": "测试摘要",
                },
                "eligibility": {
                    "passed": True,
                    "reasons": ["通过估值门槛"],
                },
                "metrics": {
                    "pe": 12.0,
                    "pb": 1.8,
                    "roe": roe,
                    "netProfitMargin": 0.22,
                    "debtToEquity": 0.35,
                    "currentRatio": 2.1,
                    "marketCap": 22_500_000_000,
                },
                "valuation": {"notes": ["PE 12.00，估值便宜"]},
                "profitability": {"notes": ["盈利能力良好"]},
                "financial_health": {"notes": ["负债水平可控"]},
                "scale": {"notes": ["大盘股，流动性较好"]},
            },
        }

    def persist_db_run(self, slug: str = "20260312_190000") -> None:
        ranked_stocks = [
            self.sample_stock("DB1", score=66.6, tier_code="strict_pass", tier_label="严格通过", roe=0.18),
            self.sample_stock("DB2", score=55.5, tier_code="roe_pending", tier_label="ROE待补充", roe=None),
        ]
        persist_screening_run(
            strategy_key="low_valuation_quality",
            strategy_display_name="低估值高质量科技股",
            screened_stocks=ranked_stocks,
            ranked_stocks=ranked_stocks,
            generated_at=datetime.strptime(slug, "%Y%m%d_%H%M%S"),
            correlation_id=f"cid-low-valuation-{slug}",
            ranking={"top_n": len(ranked_stocks)},
            paths=self.paths,
        )

    def write_legacy_result(self, slug: str = "20260312_200000") -> None:
        result_path = self.paths.outputs_dir / f"FMP筛选结果_{slug}.json"
        result_path.write_text(
            """
[
  {
    "symbol": "LEGACY",
    "companyName": "Legacy Corp",
    "price": 100,
    "score": 80,
    "scoreDetail": {
      "tier": {
        "code": "strict_pass",
        "label": "严格通过"
      },
      "metrics": {
        "pe": 10,
        "pb": 1.5,
        "roe": 0.2
      }
    }
  }
]
""".strip(),
            encoding="utf-8",
        )

    def test_load_dashboard_bundle_prefers_db_latest_result(self) -> None:
        self.persist_db_run(slug="20260312_190000")
        self.write_legacy_result(slug="20260312_200000")

        with get_connection(self.paths) as connection:
            connection.execute(
                "INSERT INTO suggested_change (symbol, change_type, target_object, before_snapshot_json, after_snapshot_json, reason, status, proposed_at) VALUES ('DB1', 'review_suggestion', 'strategy_config', '{}', '{}', 'need review', 'pending', '2026-03-12T19:05:00')"
            )
        create_notification_event(
            event_type='strategy_hit',
            payload=build_event_payload(
                event_type='strategy_hit',
                symbol='DB1',
                summary='低估值高质量科技股 发现候选 2 只',
                correlation_id='cid-ui-hit',
                facts={'candidate_count': 2},
            ),
            correlation_id='cid-ui-hit',
            symbol='DB1',
            dedupe_key='strategy_hit:ui:test',
            paths=self.paths,
        )

        bundle = load_dashboard_bundle("low_valuation_quality", paths=self.paths)

        latest = bundle["latest"]
        summary = bundle["summary"]
        rows = bundle["rows"]

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["generatedAt"], "2026-03-12T19:00:00")
        self.assertEqual([stock["symbol"] for stock in latest["stocks"]], ["DB1", "DB2"])
        self.assertEqual(summary["generated_at"], "2026-03-12 19:00:00")
        self.assertEqual(summary["strategy_name"], "低估值高质量科技股")
        self.assertEqual(summary["stock_count"], 2)
        self.assertEqual(summary["report_path"], str(self.paths.outputs_dir / "FMP筛选报告_20260312_190000.md"))
        self.assertEqual(summary["json_path"], str(self.paths.outputs_dir / "FMP筛选结果_20260312_190000.json"))
        self.assertEqual(summary["watchlist_path"], str(self.paths.watchlist_dir / "候选股.md"))
        self.assertEqual([row["Ticker"] for row in rows], ["DB1", "DB2"])
        self.assertEqual(rows[0]["Tier"], "严格通过")
        self.assertEqual(rows[1]["Tier"], "ROE待补充")
        self.assertEqual(rows[0]["ROE %"], 18.0)
        self.assertIsNone(rows[1]["ROE %"])
        self.assertEqual(bundle["strategy"]["name"], "低估值高质量科技股")
        self.assertTrue(bundle["app_config"]["notifications"]["feishu"]["enabled"])
        self.assertEqual(bundle["app_config"]["schedule"]["top_n"], 5)
        self.assertTrue(len(bundle["lifecycle"]["notifications"]) >= 1)
        self.assertTrue(len(bundle["lifecycle"]["review_queue"]) >= 1)
        self.assertIn('totals', bundle['lifecycle'])
        self.assertGreaterEqual(bundle['lifecycle']['totals']['notification_count'], 1)
        self.assertGreaterEqual(bundle['lifecycle']['totals']['review_queue_count'], 1)

    def test_load_dashboard_bundle_returns_empty_rows_without_results(self) -> None:
        bundle = load_dashboard_bundle("low_valuation_quality", paths=self.paths)

        self.assertIsNone(bundle["latest"])
        self.assertEqual(bundle["summary"]["generated_at"], "暂无")
        self.assertEqual(bundle["summary"]["stock_count"], 0)
        self.assertEqual(bundle["rows"], [])
        self.assertEqual(bundle["strategy"]["name"], "低估值高质量科技股")
        self.assertTrue(bundle["app_config"]["schedule"]["enabled"])
        self.assertEqual(bundle['lifecycle']['totals']['notification_count'], 0)
        self.assertEqual(bundle['lifecycle']['totals']['review_queue_count'], 0)


if __name__ == "__main__":
    unittest.main()
