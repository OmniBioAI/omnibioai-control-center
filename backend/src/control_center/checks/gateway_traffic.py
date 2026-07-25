from __future__ import annotations

import datetime
import json
import os
from typing import Any

# Same Redis instance omnibioai-api-gateway's AuditMiddleware writes every
# request to (redis stream "audit:events") -- see
# omnibioai-api-gateway/app/services/audit_client.py. api-gateway has no
# /metrics endpoint and isn't scraped by Prometheus, so this stream is the
# only queryable source of gateway traffic today.
AUDIT_REDIS = os.environ.get("AUDIT_REDIS", "redis://redis:6379")

_CONNECT_TIMEOUT_S = 5
_WINDOW_DAYS = 7
_TOP_ROUTES_LIMIT = 15
_MAX_ENTRIES = 200_000

# auth_failed/policy_denied/hpc_denied fire *before* a response object exists,
# so the audit payload itself carries no status_code -- these are read
# directly from the gateway's middleware source (app/middleware/auth.py,
# policy.py, hpc.py), where each path always returns exactly this status.
_DENY_EVENT_STATUS = {
    "auth_failed": 401,
    "policy_denied": 403,
    "hpc_denied": 403,
}

_EMPTY: dict[str, Any] = {
    "requests_7d": 0,
    "health_check_pings_7d": 0,
    "p50_latency_ms": 0,
    "p95_latency_ms": 0,
    "p99_latency_ms": 0,
    "auth_failure_rate_pct": 0.0,
    "requests_by_route": [],
    "status_code_breakdown": {"2xx": 0, "4xx": 0, "5xx": 0},
}


def get_gateway_traffic() -> dict[str, Any]:
    try:
        import redis

        r = redis.Redis.from_url(
            AUDIT_REDIS, socket_connect_timeout=_CONNECT_TIMEOUT_S,
            socket_timeout=_CONNECT_TIMEOUT_S, decode_responses=True,
        )
        cutoff_ms = int(datetime.datetime.now().timestamp() * 1000) - _WINDOW_DAYS * 86400 * 1000
        entries = r.xrange("audit:events", min=str(cutoff_ms), count=_MAX_ENTRIES)
    except Exception:
        return dict(_EMPTY)

    requests_7d = 0
    health_pings = 0
    latencies: list[float] = []
    route_counts: dict[str, int] = {}
    status_buckets = {"2xx": 0, "4xx": 0, "5xx": 0}
    deny_count = 0
    total_attempts = 0

    for _eid, fields in entries:
        try:
            event = json.loads(fields.get("data", "{}"))
        except (TypeError, ValueError):
            continue

        event_type = event.get("event_type")
        action = event.get("action", "") or ""

        if event_type == "request":
            if action.endswith("/health"):
                health_pings += 1
                continue
            requests_7d += 1
            total_attempts += 1
            route_counts[action] = route_counts.get(action, 0) + 1
            if event.get("decision") == "deny":
                deny_count += 1
            latency = event.get("latency_ms")
            if isinstance(latency, (int, float)):
                latencies.append(latency)
            status_code = event.get("status_code")
            if isinstance(status_code, int):
                bucket = f"{status_code // 100}xx"
                if bucket in status_buckets:
                    status_buckets[bucket] += 1
        elif event_type in _DENY_EVENT_STATUS:
            requests_7d += 1
            total_attempts += 1
            deny_count += 1
            route_counts[action] = route_counts.get(action, 0) + 1
            status_buckets[f"{_DENY_EVENT_STATUS[event_type] // 100}xx"] += 1

    latencies.sort()
    top_routes = [
        {"route": route, "count": count}
        for route, count in sorted(route_counts.items(), key=lambda kv: -kv[1])[:_TOP_ROUTES_LIMIT]
    ]
    auth_failure_pct = round(100 * deny_count / total_attempts, 2) if total_attempts else 0.0

    return {
        "requests_7d": requests_7d,
        "health_check_pings_7d": health_pings,
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "p99_latency_ms": _percentile(latencies, 0.99),
        "auth_failure_rate_pct": auth_failure_pct,
        "requests_by_route": top_routes,
        "status_code_breakdown": status_buckets,
    }


def _percentile(sorted_values: list[float], pct: float) -> int:
    if not sorted_values:
        return 0
    idx = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return int(sorted_values[idx])
