from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FMP_BASE_URL = "https://financialmodelingprep.com/stable"
DEFAULT_FEISHU_DIGEST_MODE = "top3_only"
DEFAULT_SCHEDULE_CRON = "0 9 * * 0"
DEFAULT_SCHEDULE_TIMEZONE = "Asia/Shanghai"
DEFAULT_STRATEGY_NAME = "low_valuation_quality"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path = ROOT
    config_dir: Path = ROOT / "config"
    strategy_dir: Path = ROOT / "config" / "strategies"
    app_config_path: Path = ROOT / "config" / "app.yaml"
    outputs_dir: Path = ROOT / "outputs" / "fmp-screening"
    watchlist_dir: Path = ROOT / "watchlist"
    data_dir: Path = ROOT / "data"
    database_path: Path = ROOT / "data" / "stock_research.db"
    logs_dir: Path = ROOT / "logs"

    def ensure(self) -> None:
        for path in (
            self.config_dir,
            self.strategy_dir,
            self.app_config_path.parent,
            self.outputs_dir,
            self.watchlist_dir,
            self.data_dir,
            self.database_path.parent,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AppSettings:
    fmp_api_key: str
    fmp_base_url: str = DEFAULT_FMP_BASE_URL
    request_timeout: int = 15
    perplexity_api_key: str = ""
    perplexity_base_url: str = "https://api.perplexity.ai"
    perplexity_model: str = "sonar-pro"
    perplexity_timeout: int = 45


def load_settings() -> AppSettings:
    load_dotenv(ROOT / ".env")
    return AppSettings(
        fmp_api_key=os.getenv("FMP_API_KEY", "").strip(),
        fmp_base_url=os.getenv("FMP_BASE_URL", DEFAULT_FMP_BASE_URL).strip() or DEFAULT_FMP_BASE_URL,
        request_timeout=int(os.getenv("FMP_TIMEOUT", "15")),
        perplexity_api_key=os.getenv("PERPLEXITY_API_KEY", "").strip(),
        perplexity_base_url=os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai").strip() or "https://api.perplexity.ai",
        perplexity_model=os.getenv("PERPLEXITY_MODEL", "sonar-pro").strip() or "sonar-pro",
        perplexity_timeout=int(os.getenv("PERPLEXITY_TIMEOUT", "45")),
    )


def load_yaml_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return deepcopy(default)

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if data is None:
        return deepcopy(default)
    return data


def save_yaml_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)


def deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def default_app_config() -> dict[str, Any]:
    return {
        "notifications": {
            "feishu": {
                "enabled": False,
                "webhook_url": "",
                "digest_mode": DEFAULT_FEISHU_DIGEST_MODE,
            }
        },
        "research": {
            "perplexity": {
                "enabled": False,
                "prompt_template_id": "baseline_perplexity_template",
                "prompt_version": "v1.0",
                "fallback_to_derived": True,
            }
        },
        "schedule": {
            "enabled": False,
            "cron": DEFAULT_SCHEDULE_CRON,
            "timezone": DEFAULT_SCHEDULE_TIMEZONE,
            "run_strategy": DEFAULT_STRATEGY_NAME,
            "top_n": 10,
        },
    }


def load_app_config(paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    raw = load_yaml_file(paths.app_config_path, default={}) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"App config is invalid: {paths.app_config_path}")
    return deep_merge_dict(default_app_config(), raw)


def save_app_config(config: dict[str, Any], paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    if not isinstance(config, dict):
        raise ValueError("App config must be a dictionary")
    merged = deep_merge_dict(default_app_config(), config)
    save_yaml_file(paths.app_config_path, merged)
    return merged


def load_strategy(name: str, paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    strategy_name = name[:-5] if name.endswith(".yaml") else name
    strategy_path = paths.strategy_dir / f"{strategy_name}.yaml"
    data = load_yaml_file(strategy_path, default={}) or {}
    if not strategy_path.exists():
        raise FileNotFoundError(f"Strategy file not found: {strategy_path}")
    if not isinstance(data, dict):
        raise ValueError(f"Strategy file is invalid: {strategy_path}")
    return data


def save_strategy(name: str, data: dict[str, Any], paths: ProjectPaths | None = None) -> dict[str, Any]:
    paths = paths or ProjectPaths()
    if not isinstance(data, dict):
        raise ValueError("Strategy config must be a dictionary")
    strategy_name = name[:-5] if name.endswith(".yaml") else name
    strategy_path = paths.strategy_dir / f"{strategy_name}.yaml"
    save_yaml_file(strategy_path, data)
    return data


def list_strategy_names(paths: ProjectPaths | None = None) -> list[str]:
    paths = paths or ProjectPaths()
    if not paths.strategy_dir.exists():
        return []
    return sorted(path.stem for path in paths.strategy_dir.glob("*.yaml"))
