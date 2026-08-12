"""Observability for the analytics subsystem itself (task brief Section
13). `prometheus_client` is already a transitive dependency here via
`prometheus-fastapi-instrumentator` (see pyproject.toml) -- these
counters/gauges/histogram register on the same process-global default
registry that library's `Instrumentator().expose(app)` already serves at
GET /metrics, so no new endpoint or dependency is introduced. Both the
API process (main.py) and the analytics worker process (consumer.py,
run via `python -m control_center.analytics.consumer`) import this
module and update the same metric *names*, scraped as two distinct
`instance`/`job` labels by whatever eventually scrapes them (Prometheus
attaches those labels itself; this module doesn't need to).
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

EVENTS_PROCESSED = Counter(
    "analytics_events_processed_total",
    "Analytics events successfully applied to the aggregates",
    ["stream"],
)
EVENTS_FAILED = Counter(
    "analytics_events_failed_total",
    "Analytics events that could not be processed (malformed, missing required field)",
    ["stream"],
)
CONSUMER_LAG = Gauge(
    "analytics_consumer_lag",
    "Pending (delivered, not yet acked) entries for the analytics consumer group",
    ["stream"],
)
API_REQUESTS = Counter(
    "analytics_api_requests_total",
    "Requests to an /analytics/* endpoint",
    ["endpoint"],
)
API_ERRORS = Counter(
    "analytics_api_errors_total",
    "Non-2xx responses from an /analytics/* endpoint",
    ["endpoint", "status_code"],
)
CACHE_HITS = Counter(
    "analytics_cache_hits_total",
    "Analytics response cache hits",
    ["endpoint"],
)
CACHE_MISSES = Counter(
    "analytics_cache_misses_total",
    "Analytics response cache misses",
    ["endpoint"],
)
AGGREGATION_DURATION = Histogram(
    "analytics_aggregation_duration_seconds",
    "Time spent applying one event to the Redis aggregates",
    ["stream"],
)
