from __future__ import annotations

from typing import Any

from .config import ProjectPaths, load_app_config, load_strategy, save_app_config, save_strategy


def load_strategy_config_data(strategy_name: str = "low_valuation_quality", paths: ProjectPaths | None = None) -> dict[str, Any]:
    return load_strategy(strategy_name, paths)


def save_strategy_config_data(
    strategy_name: str,
    data: dict[str, Any],
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    return save_strategy(strategy_name, data, paths)


def load_app_config_data(paths: ProjectPaths | None = None) -> dict[str, Any]:
    return load_app_config(paths)


def save_app_config_data(data: dict[str, Any], paths: ProjectPaths | None = None) -> dict[str, Any]:
    return save_app_config(data, paths)
