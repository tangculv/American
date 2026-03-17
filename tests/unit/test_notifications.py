from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths, save_app_config  # noqa: E402
from us_stock_research.models.screening_repo import persist_screening_run  # noqa: E402
from us_stock_research.notifications import (  # noqa: E402
    NotificationConfigError,
    build_notification_text,
    send_latest_notification,
    send_run_notification,
)


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


class NotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def sample_run_data(self, count: int = 4, all_roe_pending: bool = False) -> dict[str, object]:
        stocks = []
        for index in range(count):
            if all_roe_pending:
                tier_code = "roe_pending"
            elif index < 2:
                tier_code = "strict_pass"
            else:
                tier_code = "quality_watch"
            tier_label = {
                "strict_pass": "严格通过",
                "roe_pending": "ROE待补充",
                "quality_watch": "质量待观察",
            }[tier_code]
            stocks.append(
                {
                    "symbol": f"STK{index + 1}",
                    "companyName": f"Stock {index + 1}",
                    "price": 100 + index,
                    "score": 80 - index,
                    "scoreDetail": {"tier": {"code": tier_code, "label": tier_label}},
                }
            )
        return {
            "generatedAt": "2026-03-12T18:30:00",
            "strategyName": "低估值高质量科技股",
            "stockCount": len(stocks),
            "stocks": stocks,
            "allRoePending": all_roe_pending,
            "outputs": {
                "report": "/tmp/report.md",
                "json": "/tmp/result.json",
            },
        }

    def realistic_run_data(self, count: int = 4, all_roe_pending: bool = False) -> dict[str, object]:
        stocks = []
        symbols = ["ZM", "CTSH", "CSCO", "ANET"]
        company_names = [
            "Zoom Communications, Inc.",
            "Cognizant Technology Solutions Corporation",
            "Cisco Systems, Inc.",
            "Arista Networks, Inc.",
        ]
        for index in range(count):
            if all_roe_pending:
                tier_code = "roe_pending"
            elif index < 2:
                tier_code = "strict_pass"
            else:
                tier_code = "quality_watch"
            tier_label = {
                "strict_pass": "严格通过",
                "roe_pending": "ROE待补充",
                "quality_watch": "质量待观察",
            }[tier_code]
            tier_summary = {
                "strict_pass": "估值通过，且 ROE 达到 10% 质量线",
                "roe_pending": "估值通过，但 ROE 仍待补充",
                "quality_watch": "估值通过，但盈利质量仍需观察",
            }[tier_code]
            stocks.append(
                {
                    "symbol": symbols[index],
                    "companyName": company_names[index],
                    "price": 76.05 + index,
                    "score": 78.36 - index,
                    "marketCap": 22_518_478_084 + index * 1_000_000_000,
                    "scoreDetail": {
                        "tier": {"code": tier_code, "label": tier_label, "summary": tier_summary},
                        "metrics": {
                            "pe": 11.87 + index,
                            "pb": 2.30 + index * 0.1,
                            "roe": 0.1937 - index * 0.01,
                            "netProfitMargin": 0.39 - index * 0.05,
                            "debtToEquity": 0.03 + index * 0.05,
                            "currentRatio": 4.33 - index * 0.4,
                            "marketCap": 22_518_478_084 + index * 1_000_000_000,
                        },
                        "valuation": {"notes": [f"PE {11.87 + index:.2f}，估值便宜", "PB 合理"]},
                        "profitability": {
                            "notes": [
                                f"ROE {(0.1937 - index * 0.01) * 100:.1f}%，盈利能力良好",
                                f"净利率 {(0.39 - index * 0.05) * 100:.1f}%，利润率优秀",
                            ]
                        },
                        "financial_health": {"notes": ["负债水平可控", "流动性稳定"]},
                        "scale": {"notes": ["大盘股，流动性较好"]},
                    },
                }
            )
        return {
            "generatedAt": "2026-03-12T14:57:29",
            "strategyName": "低估值高质量科技股",
            "stockCount": len(stocks),
            "stocks": stocks,
            "allRoePending": all_roe_pending,
            "outputs": {
                "report": str(self.paths.outputs_dir / "FMP筛选报告_20260312_145729.md"),
                "json": str(self.paths.outputs_dir / "FMP筛选结果_20260312_145729.json"),
                "watchlist": str(self.paths.watchlist_dir / "候选股.md"),
                "top3": str(self.paths.watchlist_dir / "本周Top3.md"),
                "candidate": str(self.paths.watchlist_dir / "候选股-自动筛选.md"),
            },
        }

    def write_output_files(self, slug: str = "20260312_145729") -> None:
        (self.paths.outputs_dir / f"FMP筛选报告_{slug}.md").write_text("# report\n", encoding="utf-8")
        (self.paths.outputs_dir / f"FMP筛选结果_{slug}.json").write_text("[]\n", encoding="utf-8")
        (self.paths.watchlist_dir / "候选股.md").write_text("# watchlist\n", encoding="utf-8")
        (self.paths.watchlist_dir / "本周Top3.md").write_text("# top3\n", encoding="utf-8")
        (self.paths.watchlist_dir / "候选股-自动筛选.md").write_text("# candidate\n", encoding="utf-8")

    def write_result(self, slug: str, payload: object) -> None:
        result_path = self.paths.outputs_dir / f"FMP筛选结果_{slug}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_strategy(self, name: str = "low_valuation_quality", display_name: str = "低估值高质量科技股") -> None:
        strategy_path = self.paths.strategy_dir / f"{name}.yaml"
        strategy_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_path.write_text(f"name: {display_name}\n", encoding="utf-8")

    def persist_db_run(
        self,
        slug: str = "20260312_190000",
        strategy_key: str = "low_valuation_quality",
        display_name: str = "低估值高质量科技股",
        count: int = 1,
    ) -> None:
        ranked_stocks = json.loads(json.dumps(self.realistic_run_data(count=count)["stocks"], ensure_ascii=False))
        for stock in ranked_stocks:
            detail = dict(stock.get("scoreDetail", {}))
            detail["eligibility"] = {"passed": True, "reasons": ["通过估值门槛"]}
            stock["scoreDetail"] = detail
        persist_screening_run(
            strategy_key=strategy_key,
            strategy_display_name=display_name,
            screened_stocks=ranked_stocks,
            ranked_stocks=ranked_stocks,
            generated_at=datetime.strptime(slug, "%Y%m%d_%H%M%S"),
            correlation_id=f"cid-{strategy_key}-{slug}",
            ranking={"top_n": len(ranked_stocks)},
            paths=self.paths,
        )

    def test_build_notification_text_uses_top3_by_default(self) -> None:
        self.write_output_files()
        text = build_notification_text(self.realistic_run_data(), paths=self.paths)

        self.assertIn("一眼先看这里", text)
        self.assertIn("Top 1：ZM ｜ 严格通过 ｜ 分数 78.36 ｜ 价格 $76.05", text)
        self.assertIn("Top 3：CSCO ｜ 质量待观察 ｜ 分数 76.36 ｜ 价格 $78.05", text)
        self.assertNotIn("Top 4：ANET", text)
        self.assertIn("详细报告摘要", text)
        self.assertIn("建议级别：强烈关注", text)
        self.assertIn("Top 1｜ZM - Zoom Communications, Inc.", text)
        self.assertIn("盈利指标：ROE 19.37% ｜ 净利率 39.00%", text)
        self.assertIn("规模补充：大盘股，流动性较好", text)
        self.assertIn("Markdown 报告：outputs/fmp-screening/FMP筛选报告_20260312_145729.md", text)
        self.assertIn("这些路径只是本地留档", text)

    def test_build_notification_text_supports_full_watchlist_and_warning(self) -> None:
        self.write_output_files()
        text = build_notification_text(
            self.realistic_run_data(all_roe_pending=True),
            digest_mode="full_watchlist",
            paths=self.paths,
        )

        self.assertIn("Top 4：ANET", text)
        self.assertIn("风险提示：本轮全部为 ROE待补充", text)
        self.assertIn("Top 4｜ANET - Arista Networks, Inc.", text)

    def test_build_notification_text_hides_missing_and_external_paths(self) -> None:
        data = self.realistic_run_data()
        data["outputs"] = {
            "report": "/tmp/report.md",
            "json": str(self.paths.outputs_dir / "FMP筛选结果_20260312_145729.json"),
        }
        (self.paths.outputs_dir / "FMP筛选结果_20260312_145729.json").write_text("[]\n", encoding="utf-8")

        text = build_notification_text(data, paths=self.paths)

        self.assertNotIn("/tmp/report.md", text)
        self.assertNotIn("/tmp/result.json", text)
        self.assertIn("JSON 结果：outputs/fmp-screening/FMP筛选结果_20260312_145729.json", text)
        self.assertIn("详细报告摘要", text)
        self.assertNotIn("Markdown 报告：/tmp/report.md", text)

    def test_send_run_notification_requires_enabled_flag(self) -> None:
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": False,
                        "webhook_url": "https://example.com/hook",
                    }
                }
            },
            self.paths,
        )

        with self.assertRaises(NotificationConfigError):
            send_run_notification(self.realistic_run_data(), paths=self.paths)

    def test_send_run_notification_requires_webhook(self) -> None:
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "",
                    }
                }
            },
            self.paths,
        )

        temp_env = self.root / ".env"
        temp_env.write_text("")

        with patch.dict(os.environ, {}, clear=True):
            with patch("us_stock_research.notifications.load_dotenv") as mock_load_dotenv:
                mock_load_dotenv.side_effect = lambda path: None
                with self.assertRaises(NotificationConfigError):
                    send_run_notification(self.realistic_run_data(), paths=self.paths)

    def test_send_run_notification_rejects_fixture_payload(self) -> None:
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "https://example.com/hook",
                    }
                }
            },
            self.paths,
        )

        with self.assertRaises(NotificationConfigError):
            send_run_notification(self.sample_run_data(), paths=self.paths)

    def test_send_run_notification_accepts_env_webhook_fallback(self) -> None:
        self.write_output_files()
        sent: dict[str, object] = {}
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "",
                        "digest_mode": "full_watchlist",
                    }
                }
            },
            self.paths,
        )

        def sender(title: str, lines: list[str], webhook_url: str) -> dict[str, object]:
            sent["title"] = title
            sent["lines"] = lines
            sent["webhook_url"] = webhook_url
            return {"ok": True}

        with patch.dict(os.environ, {"FEISHU_WEBHOOK_URL": "https://example.com/from-env"}, clear=True):
            response = send_run_notification(self.realistic_run_data(), paths=self.paths, sender=sender)

        self.assertEqual(response, {"ok": True})
        self.assertEqual(sent["webhook_url"], "https://example.com/from-env")
        self.assertIn("低估值高质量科技股", str(sent["title"]))
        self.assertIn("Top 4：ANET ｜ 质量待观察 ｜ 分数 75.36 ｜ 价格 $79.05", list(sent["lines"]))
        self.assertIn("详细报告摘要", list(sent["lines"]))
        self.assertIn("Top 1｜ZM - Zoom Communications, Inc.", list(sent["lines"]))

    def test_send_run_notification_calls_sender(self) -> None:
        self.write_output_files()
        sent: dict[str, object] = {}
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "https://example.com/hook",
                        "digest_mode": "full_watchlist",
                    }
                }
            },
            self.paths,
        )

        def sender(title: str, lines: list[str], webhook_url: str) -> dict[str, object]:
            sent["title"] = title
            sent["lines"] = lines
            sent["webhook_url"] = webhook_url
            return {"ok": True}

        response = send_run_notification(self.realistic_run_data(), paths=self.paths, sender=sender)

        self.assertEqual(response, {"ok": True})
        self.assertEqual(sent["webhook_url"], "https://example.com/hook")
        self.assertIn("Top 4：ANET ｜ 质量待观察 ｜ 分数 75.36 ｜ 价格 $79.05", list(sent["lines"]))
        self.assertIn("详细报告摘要", list(sent["lines"]))
        self.assertIn("Top 1｜ZM - Zoom Communications, Inc.", list(sent["lines"]))
        self.assertIn("Markdown 报告：outputs/fmp-screening/FMP筛选报告_20260312_145729.md", list(sent["lines"]))

    def test_send_latest_notification_prefers_db_result_over_newer_legacy_file(self) -> None:
        sent: dict[str, object] = {}
        self.write_output_files(slug="20260312_190000")
        self.persist_db_run(slug="20260312_190000")
        self.write_result("20260312_200000", self.sample_run_data(count=1))
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "https://example.com/hook",
                    }
                }
            },
            self.paths,
        )

        def sender(title: str, lines: list[str], webhook_url: str) -> dict[str, object]:
            sent["title"] = title
            sent["lines"] = lines
            sent["webhook_url"] = webhook_url
            return {"delivered": True}

        response = send_latest_notification(
            paths=self.paths,
            strategy_name_hint="low_valuation_quality",
            sender=sender,
        )

        self.assertEqual(response, {"delivered": True})
        self.assertEqual(sent["webhook_url"], "https://example.com/hook")
        self.assertIn("低估值高质量科技股", str(sent["title"]))
        self.assertIn("Top 1：ZM ｜ 严格通过 ｜ 分数 78.36 ｜ 价格 $76.05", list(sent["lines"]))
        self.assertIn("详细报告摘要", list(sent["lines"]))
        self.assertIn("Top 1｜ZM - Zoom Communications, Inc.", list(sent["lines"]))
        self.assertIn("Markdown 报告：outputs/fmp-screening/FMP筛选报告_20260312_190000.md", list(sent["lines"]))
        self.assertNotIn("Top 1：STK1 ｜ 严格通过 ｜ 分数 80.00 ｜ 价格 $100.00", list(sent["lines"]))

    def test_send_latest_notification_reads_latest_result(self) -> None:
        sent: dict[str, object] = {}
        self.write_strategy()
        self.write_output_files(slug="20260312_190000")
        self.write_result("20260312_190000", [self.realistic_run_data(count=1)["stocks"][0]])
        save_app_config(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "https://example.com/hook",
                    }
                }
            },
            self.paths,
        )

        def sender(title: str, lines: list[str], webhook_url: str) -> dict[str, object]:
            sent["title"] = title
            sent["lines"] = lines
            sent["webhook_url"] = webhook_url
            return {"delivered": True}

        response = send_latest_notification(
            paths=self.paths,
            strategy_name_hint="low_valuation_quality",
            sender=sender,
        )

        self.assertEqual(response, {"delivered": True})
        self.assertEqual(sent["webhook_url"], "https://example.com/hook")
        self.assertIn("低估值高质量科技股", str(sent["title"]))
        self.assertIn("Top 1：ZM ｜ 严格通过 ｜ 分数 78.36 ｜ 价格 $76.05", list(sent["lines"]))
        self.assertIn("详细报告摘要", list(sent["lines"]))
        self.assertIn("Top 1｜ZM - Zoom Communications, Inc.", list(sent["lines"]))


if __name__ == "__main__":
    unittest.main()
