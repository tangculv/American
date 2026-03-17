from __future__ import annotations

from datetime import timedelta
from typing import Any

import requests


class FMPClientError(RuntimeError):
    """Raised when the FMP client cannot complete a request."""


class FMPClient:
    def __init__(self, api_key: str, base_url: str, timeout: int = 15) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (ClaudeCode US Stock Research MVP)",
                "Accept": "application/json",
            }
        )

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        if not self.api_key:
            raise FMPClientError("FMP_API_KEY is missing. Please set it in .env or your shell environment.")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        merged_params = {**params, "apikey": self.api_key}

        try:
            response = self.session.get(url, params=merged_params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise FMPClientError(f"Request failed for {url}: {exc}") from exc
        except ValueError as exc:
            raise FMPClientError(f"Invalid JSON response from {url}") from exc

        if isinstance(payload, dict) and payload.get("Error Message"):
            raise FMPClientError(payload["Error Message"])

        return payload

    def company_screener(
        self,
        *,
        market_cap_min: int,
        market_cap_max: int,
        volume_min: int,
        sector: str,
        exchange: str,
        limit: int,
        beta_min: float | None = None,
        beta_max: float | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "marketCapMoreThan": market_cap_min,
            "marketCapLowerThan": market_cap_max,
            "volumeMoreThan": volume_min,
            "sector": sector,
            "exchange": exchange,
            "isEtf": "false",
            "isFund": "false",
            "isActivelyTrading": "true",
            "limit": limit,
        }
        if beta_min is not None:
            params["betaMoreThan"] = beta_min
        if beta_max is not None:
            params["betaLowerThan"] = beta_max
        payload = self._get("company-screener", params)
        return payload if isinstance(payload, list) else []

    def ratios_ttm(self, symbol: str) -> dict[str, Any]:
        payload = self._get("ratios-ttm", {"symbol": symbol, "limit": 1})
        if isinstance(payload, list) and payload:
            return payload[0]
        return {}

    def historical_price_full(self, symbol: str) -> list[dict[str, Any]]:
        payload = self._get("historical-price-eod/full", {"symbol": symbol, "serietype": "line"})
        if isinstance(payload, dict):
            historical = payload.get("historical", [])
            return historical if isinstance(historical, list) else []
        return []

    def earnings_calendar(self, symbol: str, days_ahead: int = 120) -> list[dict[str, Any]]:
        today = utc_today()
        to_date = today + timedelta(days=days_ahead)
        payload = self._get(
            "earnings-calendar",
            {
                "symbol": symbol,
                "from": today.isoformat(),
                "to": to_date.isoformat(),
            },
        )
        return payload if isinstance(payload, list) else []
