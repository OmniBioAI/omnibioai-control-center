"""Analytics aggregation: the single choke point for both writing one
normalized event into the Redis aggregate structures (`apply_*`, called
by consumer.py) and reading them back out (`read_*`, called by a later
PR's service.py). Mirrors omnibioai-auth/app/services/interaction_service.py's
"single choke point" shape -- every key this package touches is written
and read through exactly the functions here, so there is one place that
defines the on-the-wire aggregate shape.

Never replays a stream on the read path (task brief Section 4) -- every
`read_*` function below is O(1) Redis reads against pre-aggregated
structures, not an XRANGE scan.

Two independent aggregate families, kept deliberately separate because
their source streams carry different guarantees:

- `interactions:events` (via `apply_interaction_event`) carries
  `organization_id` on every event, so its counters are written at three
  granularities (platform/org/org+service) and its active-user tracking
  is real per-user Redis Sets, per task brief Section 3.
- `audit:events` (via `apply_audit_event`) carries no organization_id at
  all (confirmed by reading omnibioai-api-gateway's own
  app/services/audit_client.py::build_audit_event) -- its counters and
  latency histogram are written ONLY at the platform-wide, bare-date
  key, never under an org_id-keyed key. `read_platform_performance`
  documents and returns this as explicitly platform-wide, per this
  project's own hard requirement that these numbers never be presented
  as org/team-scoped.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import redis

from control_center.analytics.metrics import EVENTS_PROCESSED
from control_center.analytics.schemas import AnalyticsEvent, is_failure

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")

ACTIVE_USERS_TTL_SECONDS = 90 * 86400
AGG_TTL_SECONDS = 90 * 86400
DEDUPE_TTL_SECONDS = 48 * 3600
LATENCY_HIST_TTL_SECONDS = 7 * 86400

# Fixed-bucket latency histogram (upper bound, ms), used to estimate
# P50/P95/P99 from audit:events without a real Prometheus histogram --
# see prometheus.py (a later PR) for the client that supersedes this the
# moment a real Prometheus server exists. Bounded, fixed cardinality
# (8 buckets/hour) regardless of traffic volume, unlike a raw sample list.
LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000, float("inf"))

_redis = redis.from_url(REDIS_URL, decode_responses=True)


def _date_str(dt: datetime | date) -> str:
    if isinstance(dt, datetime):
        return dt.date().isoformat()
    return dt.isoformat()


def _hour_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H")


def _mark_processed(dedupe_key: str, event_id: str) -> bool:
    """Returns True the first time `event_id` is seen for this key,
    False on every redelivery/retry after that -- the idempotency
    primitive both apply_* functions below build on. A short TTL (48h,
    comfortably longer than any realistic redelivery window for a
    single-replica consumer) rather than 90 days: this set exists only
    to catch near-term redelivery, not to be a permanent ledger (the
    aggregate counters themselves are the permanent record)."""
    try:
        added = _redis.sadd(dedupe_key, event_id)
        _redis.expire(dedupe_key, DEDUPE_TTL_SECONDS)
        return bool(added)
    except Exception:
        # Fail open: if Redis is unreachable for the dedupe check itself,
        # the caller's own increments below will also fail (same client)
        # and be caught there -- returning True here just means "treat as
        # not-yet-seen", never silently drops an event over a dedupe-only
        # failure while the rest of Redis is healthy.
        return True


def apply_interaction_event(event: AnalyticsEvent) -> bool:
    """Applies one normalized `interactions:events`-sourced event to the
    aggregates. Returns True if newly applied, False if it was a
    duplicate (already-processed) -- both are a "success" from the
    caller's (consumer.py's) point of view and should be acked either
    way; the return value is informational (feeds EVENTS_PROCESSED's own
    label, and is asserted on directly in tests), not a signal to retry.
    """
    date_str = _date_str(event.timestamp)
    dedupe_key = f"analytics:processed:interactions:{date_str}"
    if not _mark_processed(dedupe_key, event.event_id):
        return False

    failed = is_failure(event.event_type)
    is_query = event.event_type.startswith("query.")

    keys = [f"analytics:agg:{date_str}"]
    if event.org_id is not None:
        keys.append(f"analytics:agg:{event.org_id}:{date_str}")
        keys.append(f"analytics:agg:{event.org_id}:{event.service}:{date_str}")

    pipe = _redis.pipeline()
    for key in keys:
        if is_query:
            pipe.hincrby(key, "query_count", 1)
            if failed:
                pipe.hincrby(key, "query_error_count", 1)
        else:
            pipe.hincrby(key, "event_count", 1)
            if failed:
                pipe.hincrby(key, "event_error_count", 1)
        pipe.expire(key, AGG_TTL_SECONDS)
    pipe.execute()

    if event.user_id is not None:
        active_keys = [f"analytics:active_users:{date_str}"]
        if event.org_id is not None:
            active_keys.append(f"analytics:active_users:{event.org_id}:{date_str}")
        pipe = _redis.pipeline()
        for key in active_keys:
            pipe.sadd(key, event.user_id)
            pipe.expire(key, ACTIVE_USERS_TTL_SECONDS)
        if event.org_id is not None:
            activity_key = f"analytics:user_activity:{event.org_id}:{date_str}"
            pipe.hincrby(activity_key, str(event.user_id), 1)
            pipe.expire(activity_key, ACTIVE_USERS_TTL_SECONDS)
        pipe.execute()

    EVENTS_PROCESSED.labels(stream="interactions:events").inc()
    return True


def _latency_bucket_label(duration_ms: float) -> str:
    for upper in LATENCY_BUCKETS_MS:
        if duration_ms <= upper:
            return "inf" if upper == float("inf") else str(int(upper))
    return "inf"  # pragma: no cover -- unreachable, LATENCY_BUCKETS_MS always ends in inf


def apply_audit_event(
    *,
    event_id: str,
    timestamp: datetime,
    is_request: bool,
    is_error: bool,
    latency_ms: Optional[float],
) -> bool:
    """Applies one `audit:events`-sourced request/deny event to the
    PLATFORM-WIDE aggregates only -- see this module's own docstring for
    why: that stream carries no organization_id, so nothing derived from
    it is ever written under an org_id-keyed aggregate key. Caller
    (consumer.py) has already done the event_type/decision -> is_request/
    is_error/latency_ms translation (the same one
    checks/gateway_traffic.py already performs for this exact stream),
    kept out of this module so aggregator.py stays about aggregation, not
    about audit:events' own wire shape.
    """
    date_str = _date_str(timestamp)
    dedupe_key = f"analytics:processed:audit:{date_str}"
    if not _mark_processed(dedupe_key, event_id):
        return False

    if is_request:
        key = f"analytics:agg:{date_str}"
        pipe = _redis.pipeline()
        pipe.hincrby(key, "request_count", 1)
        if is_error:
            pipe.hincrby(key, "request_error_count", 1)
        if latency_ms is not None:
            pipe.hincrbyfloat(key, "latency_sum", latency_ms)
            pipe.hincrby(key, "latency_count", 1)
        pipe.expire(key, AGG_TTL_SECONDS)
        pipe.execute()

        if latency_ms is not None:
            hist_key = f"analytics:latency_hist:{_hour_str(timestamp)}"
            bucket = _latency_bucket_label(latency_ms)
            _redis.hincrby(hist_key, bucket, 1)
            _redis.expire(hist_key, LATENCY_HIST_TTL_SECONDS)

    EVENTS_PROCESSED.labels(stream="audit:events").inc()
    return True


# --------------------------------------------------------------------- #
# Read side -- pure aggregate reads, no stream access, ever.
# --------------------------------------------------------------------- #

_AGG_FIELDS = (
    "query_count", "query_error_count", "event_count", "event_error_count",
    "request_count", "request_error_count", "latency_sum", "latency_count",
)


def read_agg(date_str: str, org_id: Optional[int] = None, service: Optional[str] = None) -> dict[str, int | float]:
    """Reads the daily aggregate hash for one (date[, org_id[, service]])
    scope. Missing fields default to 0, never absent, so a caller never
    has to guard every dict access."""
    if service is not None and org_id is None:
        raise ValueError("service scoping requires org_id")
    if org_id is not None and service is not None:
        key = f"analytics:agg:{org_id}:{service}:{date_str}"
    elif org_id is not None:
        key = f"analytics:agg:{org_id}:{date_str}"
    else:
        key = f"analytics:agg:{date_str}"

    try:
        raw = _redis.hgetall(key)
    except Exception:
        raw = {}
    result: dict[str, int | float] = {}
    for field in _AGG_FIELDS:
        value = raw.get(field, "0")
        result[field] = float(value) if field == "latency_sum" else int(float(value))
    return result


def read_agg_range(date_strs: list[str], org_id: Optional[int] = None, service: Optional[str] = None) -> dict[str, int | float]:
    """Sums `read_agg` across a list of dates -- the building block for
    any from_date/to_date-ranged endpoint (a later PR)."""
    totals: dict[str, int | float] = {field: 0 for field in _AGG_FIELDS}
    for date_str in date_strs:
        for field, value in read_agg(date_str, org_id=org_id, service=service).items():
            totals[field] += value
    return totals


def date_range(from_date: date, to_date: date) -> list[str]:
    days = (to_date - from_date).days
    return [(from_date + timedelta(days=i)).isoformat() for i in range(days + 1)]


def read_active_user_count(date_strs: list[str], org_id: Optional[int] = None) -> int:
    """Unique-user count across one or more dates (DAU for a single date,
    WAU/MAU for a 7/30-day range) -- a real SUNION over the per-day
    Redis Sets, per task brief Section 3 ("Use Redis Sets for unique
    users"), not a HyperLogLog approximation."""
    prefix = f"analytics:active_users:{org_id}:" if org_id is not None else "analytics:active_users:"
    keys = [f"{prefix}{d}" for d in date_strs]
    if not keys:
        return 0
    if len(keys) == 1:
        try:
            return int(_redis.scard(keys[0]))
        except Exception:
            return 0
    return _sunion_count(keys)


def _sunion_count(keys: list[str]) -> int:
    # SUNION (read-only, no temp key to clean up) rather than
    # SUNIONSTORE -- avoids leaving a stray key behind if the process is
    # killed between STORE and DEL, at the cost of O(total set size) per
    # call, acceptable at the scale of "distinct users active in a
    # 30-day window" this is used for.
    try:
        return len(_redis.sunion(*keys))
    except Exception:
        return 0


def read_daily_active_users(date_strs: list[str], org_id: Optional[int] = None) -> list[dict[str, Any]]:
    return [{"date": d, "count": read_active_user_count([d], org_id=org_id)} for d in date_strs]


def read_user_activity(org_id: int, date_str: str) -> dict[str, int]:
    """user_id -> query_count for one org/day -- never returned directly
    by any API response (task brief: "do not expose raw user IDs"); only
    ever consumed server-side, e.g. for a team-roster intersection in a
    later PR, contingent on that roster source being reliable (see the
    plan's hard verification gate)."""
    try:
        raw = _redis.hgetall(f"analytics:user_activity:{org_id}:{date_str}")
    except Exception:
        raw = {}
    return {k: int(v) for k, v in raw.items()}


def read_platform_latency_percentiles(hours: list[str]) -> dict[str, Optional[float]]:
    """Estimates P50/P95/P99 (ms) from the fixed-bucket histogram built
    by apply_audit_event, across the given hour keys (see _hour_str).
    PLATFORM-WIDE ONLY -- see this module's own docstring. Returns None
    for every percentile if there is no data at all (never fabricates a
    number), matching every other "unavailable" convention in this
    codebase.
    """
    totals: dict[str, int] = {}
    for hour in hours:
        try:
            raw = _redis.hgetall(f"analytics:latency_hist:{hour}")
        except Exception:
            raw = {}
        for bucket, count in raw.items():
            totals[bucket] = totals.get(bucket, 0) + int(count)

    total_count = sum(totals.values())
    if total_count == 0:
        return {"p50": None, "p95": None, "p99": None}

    ordered = sorted(
        totals.items(),
        key=lambda kv: float("inf") if kv[0] == "inf" else float(kv[0]),
    )

    def _percentile(pct: float) -> float:
        target = pct * total_count
        cumulative = 0
        for bucket, count in ordered:
            cumulative += count
            if cumulative >= target:
                return float(LATENCY_BUCKETS_MS[-2]) if bucket == "inf" else float(bucket)
        return float(LATENCY_BUCKETS_MS[-2])  # pragma: no cover - unreachable: cumulative always reaches total_count >= target by the last bucket

    return {"p50": _percentile(0.50), "p95": _percentile(0.95), "p99": _percentile(0.99)}


def hours_for_range(from_dt: datetime, to_dt: datetime) -> list[str]:
    hours = []
    current = from_dt.replace(minute=0, second=0, microsecond=0)
    end = to_dt.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        hours.append(_hour_str(current))
        current += timedelta(hours=1)
    return hours
