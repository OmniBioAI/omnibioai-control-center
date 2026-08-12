"""A small HTTP-API client for a real Prometheus server (task brief
Section 6) -- `GET {PROMETHEUS_URL}/api/v1/query`/`query_range`, not
scraping any service's own `/metrics` text output directly.

No Prometheus server is deployed anywhere in this workspace today: every
repo/compose file was grepped for "prometheus" during this feature's
discovery phase and the only hits are per-service `/metrics` endpoints
(via `prometheus-fastapi-instrumentator`) -- nothing scrapes them, no
`prometheus.yml`, no compose service. Every function here therefore
degrades to `{"available": False, ...}` in every real call made from
this environment right now, and that is the expected, tested behavior --
not a rare failure edge case. The client is still fully implemented and
tested (never raises past the module boundary) so it starts working the
moment a real Prometheus server exists, with zero code change required
anywhere that calls it.

Async (httpx.AsyncClient), matching routes_dashboard.py's own pattern --
this is used from async FastAPI route handlers (a later PR), same as
that module's `_get_json` helper.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "")
_TIMEOUT_SECONDS = float(os.environ.get("PROMETHEUS_TIMEOUT_SECONDS", "3"))

_UNAVAILABLE: dict[str, Any] = {"available": False, "result": None}


def is_configured() -> bool:
    """False by default -- PROMETHEUS_URL is empty unless explicitly set,
    unlike every other upstream URL in this codebase (which default to
    an in-network hostname) precisely because no such host exists in any
    deployment of this platform today. Set the env var once one does."""
    return bool(PROMETHEUS_URL)


async def _get_json(url: str, params: dict) -> Optional[dict]:
    if not is_configured():
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, timeout=_TIMEOUT_SECONDS)
        if r.status_code >= 400:
            return None
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


async def instant_query(promql: str) -> dict[str, Any]:
    """One Prometheus instant query (`/api/v1/query`). Returns
    `{"available": True, "result": [...]}` on success (the raw
    `data.result` array Prometheus's own API returns -- callers pick
    apart vector/scalar shapes themselves, this function does not
    interpret PromQL result types), or `_UNAVAILABLE` on ANY failure --
    unreachable, timeout, non-2xx, malformed JSON, or a `status != "success"`
    body. Never raises.
    """
    data = await _get_json(f"{PROMETHEUS_URL}/api/v1/query", {"query": promql})
    if not isinstance(data, dict) or data.get("status") != "success":
        return dict(_UNAVAILABLE)
    result = (data.get("data") or {}).get("result")
    if result is None:
        return dict(_UNAVAILABLE)
    return {"available": True, "result": result}


async def range_query(promql: str, start: float, end: float, step: str = "60s") -> dict[str, Any]:
    """One Prometheus range query (`/api/v1/query_range`) -- same success/
    failure contract as instant_query. `start`/`end` are Unix timestamps
    (seconds), matching Prometheus's own API."""
    data = await _get_json(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        {"query": promql, "start": start, "end": end, "step": step},
    )
    if not isinstance(data, dict) or data.get("status") != "success":
        return dict(_UNAVAILABLE)
    result = (data.get("data") or {}).get("result")
    if result is None:
        return dict(_UNAVAILABLE)
    return {"available": True, "result": result}


def _extract_scalar(result: list) -> Optional[float]:
    """Pulls the single numeric value out of a `histogram_quantile(...)`
    instant-query result vector -- that PromQL shape always returns at
    most one series with no `by` labels left, `[timestamp, "value"]`.
    Returns None for an empty/unexpected shape (e.g. NaN, which
    Prometheus itself returns when a bucket has no samples in the
    window) rather than fabricating a number."""
    if not result:
        return None
    try:
        value = result[0]["value"][1]
        parsed = float(value)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed


async def query_latency_quantiles(
    metric: str = "http_request_duration_seconds_bucket",
    job: Optional[str] = None,
    window: str = "5m",
) -> dict[str, Any]:
    """Convenience builder for the standard `histogram_quantile` PromQL
    shape a `prometheus_fastapi_instrumentator`-exposed histogram
    supports (the library every /metrics endpoint in this workspace
    already uses -- see analytics/metrics.py's own docstring). Issues
    three instant queries (P50/P95/P99) and reports the whole thing
    unavailable if Prometheus itself is unreachable or ANY of the three
    fails -- a partial quantile set is not a result worth displaying.
    Values come back in the histogram's own unit (seconds, for this
    library's default buckets); callers convert to ms if needed.
    """
    if not is_configured():
        return dict(_UNAVAILABLE)

    label_selector = f'{{job="{job}"}}' if job else ""
    base = f"sum(rate({metric}{label_selector}[{window}])) by (le)"

    quantiles = {}
    for pct, label in ((0.50, "p50"), (0.95, "p95"), (0.99, "p99")):
        response = await instant_query(f"histogram_quantile({pct}, {base})")
        if not response["available"]:
            return dict(_UNAVAILABLE)
        quantiles[label] = _extract_scalar(response["result"])

    return {"available": True, **quantiles}
