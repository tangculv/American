from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from us_stock_research.config import ProjectPaths  # noqa: E402
from us_stock_research.config_store import (  # noqa: E402
    load_app_config_data,
    load_strategy_config_data,
    save_app_config_data,
    save_strategy_config_data,
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


class ConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.paths = make_paths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_and_load_strategy_config_round_trip(self) -> None:
        strategy = {
            "name": "测试策略",
            "screen": {
                "limit": 25,
                "market_cap_min": 1_000_000_000,
                "market_cap_max": 50_000_000_000,
                "volume_min": 2_000_000,
                "sector": "Technology",
                "exchange": "NASDAQ",
            },
            "ranking": {
                "top_n": 8,
                "gates": {
                    "max_pe": 25,
                    "max_pb": 4,
                    "min_valuation_score": 5,
                    "min_roe_for_quality": 0.12,
                },
            },
        }

        saved = save_strategy_config_data("demo_strategy", strategy, paths=self.paths)
        loaded = load_strategy_config_data("demo_strategy", paths=self.paths)

        self.assertEqual(saved, strategy)
        self.assertEqual(loaded, strategy)
        self.assertTrue((self.paths.strategy_dir / "demo_strategy.yaml").exists())

    def test_load_strategy_config_accepts_yaml_suffix(self) -> None:
        strategy = {"name": "后缀测试策略", "screen": {}, "ranking": {}}
        save_strategy_config_data("suffix_case", strategy, paths=self.paths)

        loaded = load_strategy_config_data("suffix_case.yaml", paths=self.paths)

        self.assertEqual(loaded["name"], "后缀测试策略")

    def test_save_and_load_app_config_data_merges_defaults(self) -> None:
        saved = save_app_config_data(
            {
                "notifications": {
                    "feishu": {
                        "enabled": True,
                        "webhook_url": "https://example.com/hook",
                    }
                },
                "schedule": {
                    "enabled": True,
                    "top_n": 25,
                },
            },
            paths=self.paths,
        )
        loaded = load_app_config_data(paths=self.paths)

        self.assertTrue(saved["notifications"]["feishu"]["enabled"])
        self.assertEqual(loaded["notifications"]["feishu"]["webhook_url"], "https://example.com/hook")
        self.assertEqual(loaded["notifications"]["feishu"]["digest_mode"], "top3_only")
        self.assertTrue(loaded["schedule"]["enabled"])
        self.assertEqual(loaded["schedule"]["top_n"], 25)
        self.assertEqual(loaded["schedule"]["cron"], "0 9 * * 0")
        self.assertEqual(loaded["schedule"]["timezone"], "Asia/Shanghai")
        self.assertEqual(loaded["schedule"]["run_strategy"], "low_valuation_quality")


if __name__ == "__main__":
    unittest.main()
