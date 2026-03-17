from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.models.screening_repo import persist_screening_run  # noqa: E402
from us_stock_research.results_repo import (  # noqa: E402
    latest_result_file,
    load_latest_result,
    load_result,
    normalize_result_payload,
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


class ResultsRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_strategy(self, name: str = "low_valuation_quality", display_name: str = "低估值高质量科技股") -> None:
        strategy_path = self.paths.strategy_dir / f"{name}.yaml"
        strategy_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_path.write_text(f"name: {display_name}\n", encoding="utf-8")

    def write_result(self, slug: str, payload: object) -> Path:
        result_path = self.paths.outputs_dir / f"FMP筛选结果_{slug}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return result_path

    def sample_stock(self, symbol: str, tier_code: str = "strict_pass") -> dict[str, object]:
        tier_label = {
            "strict_pass": "严格通过",
            "roe_pending": "ROE待补充",
            "quality_watch": "质量待观察",
        }[tier_code]
        tier_summary = {
            "strict_pass": "估值通过，且 ROE 达到 10% 质量线",
            "roe_pending": "估值通过，但 ROE 缺失，需补充盈利质量验证",
            "quality_watch": "估值通过，但 ROE 低于 10% 质量线",
        }[tier_code]
        roe_value = {
            "strict_pass": 0.18,
            "roe_pending": None,
            "quality_watch": 0.08,
        }[tier_code]
        return {
            "symbol": symbol,
            "companyName": f"{symbol} Corp",
            "price": 123.45,
            "marketCap": 22_500_000_000,
            "score": 66.6,
            "scoreDetail": {
                "tier": {
                    "code": tier_code,
                    "label": tier_label,
                    "summary": tier_summary,
                },
                "eligibility": {
                    "passed": True,
                    "reasons": ["通过估值门槛"],
                },
                "metrics": {
                    "pe": 12.0,
                    "pb": 1.8,
                    "roe": roe_value,
                    "netProfitMargin": 0.22,
                    "debtToEquity": 0.35,
                    "currentRatio": 2.1,
                    "marketCap": 22_500_000_000,
                },
                "valuation": {"notes": ["PE 12.00，估值便宜", "PB 合理"]},
                "profitability": {"notes": ["盈利能力良好"]},
                "financial_health": {"notes": ["负债水平可控"]},
                "scale": {"notes": ["大盘股，流动性较好"]},
            },
        }

    def persist_db_run(
        self,
        slug: str = "20260312_190000",
        strategy_key: str = "low_valuation_quality",
        display_name: str = "低估值高质量科技股",
        stocks: list[dict[str, object]] | None = None,
    ) -> None:
        ranked_stocks = stocks or [
            self.sample_stock("DB1", tier_code="strict_pass"),
            self.sample_stock("DB2", tier_code="roe_pending"),
        ]
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

    def test_load_latest_result_returns_none_when_empty(self) -> None:
        self.assertIsNone(load_latest_result(self.paths))

    def test_latest_result_file_returns_newest_path(self) -> None:
        self.write_result("20260312_120000", [self.sample_stock("OLD")])
        newest = self.write_result("20260312_130000", [self.sample_stock("NEW")])

        self.assertEqual(latest_result_file(self.paths), newest)

    def test_load_result_normalizes_legacy_list_payload(self) -> None:
        self.write_strategy()
        result_path = self.write_result(
            "20260312_140500",
            [self.sample_stock("MSFT"), self.sample_stock("NVDA", tier_code="roe_pending")],
        )

        result = load_result(result_path, paths=self.paths, strategy_name_hint="low_valuation_quality")

        self.assertEqual(result["generatedAt"], "2026-03-12T14:05:00")
        self.assertEqual(result["strategyName"], "低估值高质量科技股")
        self.assertEqual(result["stockCount"], 2)
        self.assertEqual([stock["symbol"] for stock in result["topStocks"]], ["MSFT", "NVDA"])
        self.assertFalse(result["allRoePending"])
        self.assertTrue(result["outputs"]["report"].endswith("FMP筛选报告_20260312_140500.md"))
        self.assertEqual(result["resultFile"], str(result_path))

    def test_load_result_preserves_structured_payload_outputs(self) -> None:
        result_path = self.write_result(
            "20260312_150000",
            {
                "generatedAt": "2026-03-12T15:00:01",
                "strategyName": "自定义策略",
                "stocks": [self.sample_stock("AMD", tier_code="roe_pending")],
                "outputs": {
                    "report": "/tmp/report.md",
                    "json": "/tmp/result.json",
                },
            },
        )

        result = load_result(result_path, paths=self.paths)

        self.assertEqual(result["generatedAt"], "2026-03-12T15:00:01")
        self.assertEqual(result["strategyName"], "自定义策略")
        self.assertTrue(result["allRoePending"])
        self.assertEqual(result["outputs"]["report"], "/tmp/report.md")
        self.assertEqual(result["outputs"]["json"], "/tmp/result.json")
        self.assertIn("candidate", result["outputs"])

    def test_load_latest_result_prefers_db_snapshot_over_legacy_file(self) -> None:
        self.write_strategy()
        self.persist_db_run(slug="20260312_190000")
        self.write_result("20260312_200000", [self.sample_stock("LEGACY")])

        result = load_latest_result(self.paths, strategy_name_hint="low_valuation_quality")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["generatedAt"], "2026-03-12T19:00:00")
        self.assertEqual(result["strategyKey"], "low_valuation_quality")
        self.assertEqual(result["strategyName"], "低估值高质量科技股")
        self.assertEqual([stock["symbol"] for stock in result["stocks"]], ["DB1", "DB2"])
        self.assertEqual(result["resultFile"], str(self.paths.outputs_dir / "FMP筛选结果_20260312_190000.json"))

    def test_load_latest_result_respects_strategy_hint_for_db_runs(self) -> None:
        self.persist_db_run(slug="20260312_190000", strategy_key="low_valuation_quality", display_name="低估值高质量科技股")
        self.persist_db_run(
            slug="20260312_200000",
            strategy_key="growth_quality",
            display_name="成长质量策略",
            stocks=[self.sample_stock("GROW")],
        )

        result = load_latest_result(self.paths, strategy_name_hint="low_valuation_quality")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["strategyKey"], "low_valuation_quality")
        self.assertEqual(result["generatedAt"], "2026-03-12T19:00:00")
        self.assertEqual([stock["symbol"] for stock in result["stocks"]], ["DB1", "DB2"])

    def test_load_latest_result_falls_back_to_legacy_file_when_db_empty(self) -> None:
        self.write_strategy()
        self.write_result("20260312_170000", [self.sample_stock("MSFT")])

        result = load_latest_result(self.paths, strategy_name_hint="low_valuation_quality")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["generatedAt"], "2026-03-12T17:00:00")
        self.assertEqual([stock["symbol"] for stock in result["stocks"]], ["MSFT"])

    def test_normalize_result_payload_rejects_unsupported_payload(self) -> None:
        result_path = self.paths.outputs_dir / "FMP筛选结果_20260312_160000.json"

        with self.assertRaises(ValueError):
            normalize_result_payload({"unexpected": True}, result_path, paths=self.paths)


if __name__ == "__main__":
    unittest.main()
