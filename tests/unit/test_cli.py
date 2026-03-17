from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.cli import (  # noqa: E402
    build_candidate_markdown,
    build_top3_markdown,
    build_watchlist_markdown,
    calculate_score,
    candidate_tier,
    enrich_candidates,
    evaluate_candidate_eligibility,
    stock_status,
)


class StubFMPClient:
    def __init__(self, ratios_by_symbol: dict[str, dict[str, float]]) -> None:
        self.ratios_by_symbol = ratios_by_symbol

    def ratios_ttm(self, symbol: str) -> dict[str, float] | None:
        return self.ratios_by_symbol.get(symbol)


class CliScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stock = {
            "symbol": "TEST",
            "companyName": "Test Corp",
            "marketCap": 12_000_000_000,
            "price": 88.5,
            "ratios": {
                "priceToEarningsRatioTTM": 12.0,
                "priceToBookRatioTTM": 1.8,
                "roeRatioTTM": 0.18,
                "netProfitMarginTTM": 0.22,
                "debtToEquityRatioTTM": 0.35,
                "currentRatioTTM": 2.1,
            },
        }
        self.ranking = {
            "gates": {
                "max_pe": 30,
                "max_pb": 5,
                "min_valuation_score": 2,
                "require_positive_pe": True,
                "require_positive_pb": True,
                "min_roe_for_quality": 0.10,
            }
        }

    def test_calculate_score_returns_detail(self) -> None:
        score, detail = calculate_score(self.stock)
        self.assertGreater(score, 0)
        self.assertIn("valuation", detail)
        self.assertEqual(detail["metrics"]["pe"], 12.0)

    def test_markdown_builders_include_symbol(self) -> None:
        score, detail = calculate_score(self.stock)
        detail["tier"] = candidate_tier(detail, self.ranking)
        stock = {**self.stock, "score": score, "scoreDetail": detail}
        candidate = build_candidate_markdown([stock], __import__("datetime").datetime(2026, 3, 11, 23, 30), "测试策略")
        top3 = build_top3_markdown([stock], __import__("datetime").datetime(2026, 3, 11, 23, 30), "测试策略")
        watchlist = build_watchlist_markdown([stock], __import__("datetime").datetime(2026, 3, 11, 23, 30), "测试策略")
        self.assertIn("TEST", candidate)
        self.assertIn("TEST", top3)
        self.assertIn("TEST", watchlist)
        self.assertIn("严格通过", candidate)

    def test_score_payload_is_json_serializable(self) -> None:
        score, detail = calculate_score(self.stock)
        detail["tier"] = candidate_tier(detail, self.ranking)
        payload = {**self.stock, "score": score, "scoreDetail": detail}
        json.dumps(payload, ensure_ascii=False)

    def test_missing_roe_uses_conservative_profitability_score(self) -> None:
        stock = {
            **self.stock,
            "ratios": {
                **self.stock["ratios"],
                "roeRatioTTM": None,
                "returnOnEquityTTM": None,
                "netProfitMarginTTM": 0.25,
            },
        }
        score, detail = calculate_score(stock)
        self.assertIsNone(detail["metrics"]["roe"])
        self.assertEqual(detail["profitability"]["score"], 3.0)
        self.assertIn("ROE 数据缺失，盈利能力评分降权", detail["profitability"]["notes"])
        self.assertTrue(any("保守加分" in note for note in detail["profitability"]["notes"]))
        self.assertGreater(score, 0)

    def test_return_on_equity_fallback_is_used(self) -> None:
        stock = {
            **self.stock,
            "ratios": {
                **self.stock["ratios"],
                "roeRatioTTM": None,
                "returnOnEquityTTM": 0.21,
            },
        }
        _, detail = calculate_score(stock)
        self.assertEqual(detail["metrics"]["roe"], 0.21)
        self.assertEqual(detail["profitability"]["score"], 40.0)

    def test_high_valuation_candidate_fails_eligibility_gate(self) -> None:
        _, detail = calculate_score(
            {
                **self.stock,
                "ratios": {
                    **self.stock["ratios"],
                    "priceToEarningsRatioTTM": 71.87,
                    "priceToBookRatioTTM": 14.56,
                },
            }
        )
        eligibility = evaluate_candidate_eligibility(detail, self.ranking)
        self.assertFalse(eligibility["passed"])
        self.assertTrue(any("PE 71.87" in reason for reason in eligibility["reasons"]))
        self.assertTrue(any("PB 14.56" in reason for reason in eligibility["reasons"]))

    def test_candidate_tier_returns_strict_pass_when_roe_meets_threshold(self) -> None:
        _, detail = calculate_score(self.stock)
        tier = candidate_tier(detail, self.ranking)
        self.assertEqual(tier["code"], "strict_pass")
        self.assertTrue(tier["strict_quality_pass"])

    def test_candidate_tier_returns_roe_pending_when_roe_missing(self) -> None:
        stock = {
            **self.stock,
            "ratios": {
                **self.stock["ratios"],
                "roeRatioTTM": None,
                "returnOnEquityTTM": None,
            },
        }
        _, detail = calculate_score(stock)
        tier = candidate_tier(detail, self.ranking)
        self.assertEqual(tier["code"], "roe_pending")
        self.assertEqual(tier["label"], "ROE待补充")

    def test_candidate_tier_returns_quality_watch_when_roe_below_threshold(self) -> None:
        stock = {
            **self.stock,
            "ratios": {
                **self.stock["ratios"],
                "roeRatioTTM": 0.06,
            },
        }
        _, detail = calculate_score(stock)
        tier = candidate_tier(detail, self.ranking)
        self.assertEqual(tier["code"], "quality_watch")
        self.assertFalse(tier["strict_quality_pass"])

    def test_stock_status_uses_tier_label(self) -> None:
        strict_stock = {"scoreDetail": {"tier": {"code": "strict_pass"}}}
        roe_pending_stock = {"scoreDetail": {"tier": {"code": "roe_pending"}}}
        quality_watch_stock = {"scoreDetail": {"tier": {"code": "quality_watch"}}}
        self.assertEqual(stock_status(strict_stock, 1), "通过")
        self.assertEqual(stock_status(strict_stock, 5), "待研究")
        self.assertEqual(stock_status(roe_pending_stock, 1), "ROE待补充")
        self.assertEqual(stock_status(quality_watch_stock, 1), "质量待观察")

    def test_enrich_candidates_filters_out_high_valuation_names(self) -> None:
        candidates = [
            {
                "symbol": "GOOD",
                "companyName": "Good Corp",
                "marketCap": 20_000_000_000,
                "price": 100.0,
            },
            {
                "symbol": "EXP",
                "companyName": "Expensive Corp",
                "marketCap": 40_000_000_000,
                "price": 300.0,
            },
        ]
        client = StubFMPClient(
            {
                "GOOD": {
                    "priceToEarningsRatioTTM": 14.0,
                    "priceToBookRatioTTM": 1.9,
                    "roeRatioTTM": 0.20,
                    "netProfitMarginTTM": 0.22,
                    "debtToEquityRatioTTM": 0.30,
                    "currentRatioTTM": 2.0,
                },
                "EXP": {
                    "priceToEarningsRatioTTM": 80.0,
                    "priceToBookRatioTTM": 12.0,
                    "roeRatioTTM": 0.28,
                    "netProfitMarginTTM": 0.30,
                    "debtToEquityRatioTTM": 0.20,
                    "currentRatioTTM": 3.0,
                },
            }
        )

        enriched = enrich_candidates(client, candidates, self.ranking)
        self.assertEqual([stock["symbol"] for stock in enriched], ["GOOD"])
        self.assertTrue(enriched[0]["scoreDetail"]["eligibility"]["passed"])
        self.assertEqual(enriched[0]["scoreDetail"]["tier"]["code"], "strict_pass")


if __name__ == "__main__":
    unittest.main()
