"""Zero-key public FX rate client with resilient fallback."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from src.models import FxQuote

logger = logging.getLogger(__name__)

# Public, authentication-free FX endpoints
PUBLIC_FX_ENDPOINTS: List[Tuple[str, str, Callable[[dict], Optional[float]]]] = [
    (
        "Frankfurter (ECB)",
        "https://api.frankfurter.app/latest?from=USD&to=JPY",
        lambda d: d.get("rates", {}).get("JPY"),
    ),
    (
        "ExchangeRate-API (Open)",
        "https://open.er-api.com/v6/latest/USD",
        lambda d: d.get("rates", {}).get("JPY"),
    ),
]


def fetch_usd_jpy_rate(
    offline: bool = False,
    fallback_rate: float = 150.0,
    timeout_sec: float = 5.0,
) -> FxQuote:
    """Fetch USD/JPY from key-free public APIs; fall back cleanly on offline/error."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if offline:
        return FxQuote(
            pair="USD/JPY",
            rate=fallback_rate,
            source="offline-fallback",
            fetched_at_utc=now_utc,
            is_fallback=True,
        )

    for provider_name, url, parser in PUBLIC_FX_ENDPOINTS:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "crossborder-arbitrage-pipeline/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status != 200:
                    continue
                payload = json.loads(resp.read().decode("utf-8"))
                rate = parser(payload)
                if rate is not None and 50.0 < float(rate) < 400.0:
                    return FxQuote(
                        pair="USD/JPY",
                        rate=round(float(rate), 2),
                        source=provider_name,
                        fetched_at_utc=now_utc,
                        is_fallback=False,
                    )
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            logger.warning("FX provider %s unavailable: %s", provider_name, exc)

    logger.info("Using fallback USD/JPY rate: %.2f", fallback_rate)
    return FxQuote(
        pair="USD/JPY",
        rate=fallback_rate,
        source="fallback-default",
        fetched_at_utc=now_utc,
        is_fallback=True,
    )
