"""Orchestration layer for every /analytics/* endpoint (router.py, this
same PR). Assembles a response from aggregator.py's pre-aggregated Redis
reads plus prometheus.py/billing_client.py/tes_client.py -- never
computes anything by replaying a stream, never duplicates billing math.

Team-level attribution (Section 8's `AnalyticsScope.team_id`) is
implemented via roster intersection against `analytics:user_activity`/
`analytics:active_users` -- confirmed safe by this feature's own hard
verification gate before this PR started: omnibioai-auth's
`GET /orgs/{org_id}/teams/{team_id}/members` is unpaginated (a single
`.all()` query, see `team_service.list_team_members`) and returns the
complete roster in one call, so a single fetch is always complete. Any
call site below that needs it treats a *failed* roster fetch (auth-service
unreachable) as "team scope unavailable" and returns null fields with
`team_scope_available: false`, never silently falling back to the org-
level number mislabeled as team-scoped.

`/analytics/performance` and the `latency_source="events"` fallback used
elsewhere are PLATFORM-WIDE ONLY -- `audit:events` carries no
organization_id (see aggregator.py's own module docstring) -- and are
always returned with `org_id`/`team_id` set to null, never echoing the
caller's own requested scope, per this feature's explicit requirement
that these numbers are never presented as tenant-scoped.

`/analytics/workflows` (and the `workflows_run` field on
`/analytics/overview`) is null for a platform_admin -- confirmed via the
same hard verification gate: TES's `GET /api/runs` is scoped to the
*forwarded token's own* organization_id/team_id (Mode B Phase 1B's
`store.list(organization_id=identity.organization_id, team_id=
identity.team_id, filtered=True)`), not by a query parameter a caller can
aim at an arbitrary org. That's exactly right for org_admin/team_admin
(their own AnalyticsScope.org_id is, by permissions.py's own
construction, always their token's own org_id) but cannot honestly
answer "org X's workflows" for a platform_admin whose own token identity
may not even belong to org X -- returned as null rather than silently
describing the wrong organization.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from control_center.analytics import aggregator, billing_client, cache, prometheus, tes_client
from control_center.analytics.permissions import AnalyticsScope

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")
_TEAM_ROSTER_TIMEOUT_SECONDS = 5.0
_TEAM_ROSTER_CACHE_TTL_SECONDS = 300

DEFAULT_RANGE_DAYS = 30


def resolve_date_range(from_date: Optional[date], to_date: Optional[date]) -> tuple[date, date]:
    """Defaults to the last 30 days (task brief Section 7) when either
    bound is omitted. `to_date` defaults to today even if only `from_date`
    was supplied, and vice versa -- there is no partial-range state."""
    resolved_to = to_date or date.today()
    resolved_from = from_date or (resolved_to - timedelta(days=DEFAULT_RANGE_DAYS - 1))
    return resolved_from, resolved_to


async def _team_roster(org_id: int, team_id: int, authorization: Optional[str]) -> Optional[set[str]]:
    """Fetches team-membership via the same IAM endpoint
    routes_team_proxy.py already relays (GET /orgs/{org}/teams/{team}/members),
    called directly here since service.py already talks to other
    upstreams (billing/TES) the same way. Cached 5 minutes -- team
    membership changes rarely enough that a short lag is acceptable, the
    same TTL every other analytics cache entry uses. Returns None on any
    failure (unreachable, non-200, malformed body) -- callers treat that
    as "team scope unavailable", never as an empty roster."""
    cache_key = f"analytics:team_roster:{org_id}:{team_id}"

    async def _compute() -> Optional[list[str]]:
        headers = {"Authorization": authorization} if authorization else {}
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{IAM_URL}/orgs/{org_id}/teams/{team_id}/members",
                    headers=headers, timeout=_TEAM_ROSTER_TIMEOUT_SECONDS,
                )
            if r.status_code != 200:
                return None
            body = r.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(body, list):
            return None
        return [str(m["user_id"]) for m in body if isinstance(m, dict) and "user_id" in m]

    roster = await cache.get_or_set_async(cache_key, "team_roster", _compute, ttl=_TEAM_ROSTER_CACHE_TTL_SECONDS)
    return set(roster) if roster is not None else None


async def _resolve_team_roster_if_needed(
    scope: AnalyticsScope, authorization: Optional[str],
) -> tuple[Optional[set[str]], bool]:
    """Returns (roster, applicable). applicable=False means this request
    isn't team-scoped at all (org- or platform-level) -- roster is always
    None in that case and callers must use the org/platform aggregate
    directly, not treat a None roster as a failed lookup."""
    if scope.team_id is None or scope.org_id is None:
        return None, False
    roster = await _team_roster(scope.org_id, scope.team_id, authorization)
    return roster, True


def _daily_query_counts(org_id: Optional[int], date_strs: list[str], roster: Optional[set[str]]) -> list[int]:
    counts = []
    for date_str in date_strs:
        if roster is not None:
            activity = aggregator.read_user_activity(org_id, date_str)
            counts.append(sum(v for uid, v in activity.items() if uid in roster))
        else:
            counts.append(aggregator.read_agg(date_str, org_id=org_id)["query_count"])
    return counts


def _active_user_count(org_id: Optional[int], date_strs: list[str], roster: Optional[set[str]]) -> int:
    if roster is not None:
        return len(aggregator.read_active_user_ids(date_strs, org_id=org_id) & roster)
    return aggregator.read_active_user_count(date_strs, org_id=org_id)


async def _workflow_run_count(scope: AnalyticsScope, from_date: date, to_date: date, authorization: Optional[str]) -> Optional[int]:
    if scope.is_platform_admin:
        return None
    runs = await tes_client.get_runs(authorization)
    if runs is None:
        return None
    from_epoch, to_epoch = _epoch_bounds(from_date, to_date)
    return sum(
        1 for run in runs
        if isinstance(run.get("created_epoch"), (int, float)) and from_epoch <= run["created_epoch"] <= to_epoch
    )


def _epoch_bounds(from_date: date, to_date: date) -> tuple[float, float]:
    return (
        datetime.combine(from_date, datetime.min.time()).timestamp(),
        datetime.combine(to_date, datetime.max.time()).timestamp(),
    )


async def get_overview(scope: AnalyticsScope, from_date: date, to_date: date, authorization: Optional[str]) -> dict[str, Any]:
    date_strs = aggregator.date_range(from_date, to_date)
    roster, team_applicable = await _resolve_team_roster_if_needed(scope, authorization)

    result: dict[str, Any] = {
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
        "org_id": scope.org_id, "team_id": scope.team_id,
    }

    if team_applicable and roster is None:
        result.update(total_queries=None, active_users=None, team_scope_available=False)
    else:
        result["total_queries"] = sum(_daily_query_counts(scope.org_id, date_strs, roster))
        result["active_users"] = _active_user_count(scope.org_id, date_strs, roster)
        if team_applicable:
            result["team_scope_available"] = True

    # error_rate always reflects the org/platform-level counters (no
    # per-user error tracking exists to roster-intersect -- see this
    # module's own docstring on team-level limitations).
    org_agg = aggregator.read_agg_range(date_strs, org_id=scope.org_id)
    result["error_rate"] = round(org_agg["query_error_count"] / org_agg["query_count"], 4) if org_agg["query_count"] else 0.0
    result["workflows_run"] = await _workflow_run_count(scope, from_date, to_date, authorization)
    return result


async def get_queries(scope: AnalyticsScope, from_date: date, to_date: date, authorization: Optional[str]) -> dict[str, Any]:
    date_strs = aggregator.date_range(from_date, to_date)
    roster, team_applicable = await _resolve_team_roster_if_needed(scope, authorization)

    result: dict[str, Any] = {
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
        "org_id": scope.org_id, "team_id": scope.team_id,
    }
    if team_applicable and roster is None:
        result.update(total_queries=None, daily=[{"date": d, "count": None} for d in date_strs], team_scope_available=False)
        return result

    counts = _daily_query_counts(scope.org_id, date_strs, roster)
    result["daily"] = [{"date": d, "count": c} for d, c in zip(date_strs, counts)]
    result["total_queries"] = sum(counts)
    if team_applicable:
        result["team_scope_available"] = True
    return result


async def get_users(scope: AnalyticsScope, from_date: date, to_date: date, authorization: Optional[str]) -> dict[str, Any]:
    date_strs = aggregator.date_range(from_date, to_date)
    roster, team_applicable = await _resolve_team_roster_if_needed(scope, authorization)

    result: dict[str, Any] = {"org_id": scope.org_id, "team_id": scope.team_id}
    if team_applicable and roster is None:
        result.update(daily=[{"date": d, "count": None} for d in date_strs], dau=None, wau=None, mau=None, team_scope_available=False)
        return result

    daily = [{"date": d, "count": _active_user_count(scope.org_id, [d], roster)} for d in date_strs]

    wau_dates = aggregator.date_range(to_date - timedelta(days=6), to_date)
    mau_dates = aggregator.date_range(to_date - timedelta(days=29), to_date)

    result["daily"] = daily
    result["dau"] = _active_user_count(scope.org_id, [to_date.isoformat()], roster)
    result["wau"] = _active_user_count(scope.org_id, wau_dates, roster)
    result["mau"] = _active_user_count(scope.org_id, mau_dates, roster)
    if team_applicable:
        result["team_scope_available"] = True
    return result


async def get_services(scope: AnalyticsScope, from_date: date, to_date: date) -> dict[str, Any]:
    """Always org-level (never roster-intersected to a team) -- no
    per-user-per-service granularity is tracked, see this module's own
    docstring. A team_admin still sees their own org's full service
    breakdown, same as an org_admin would."""
    result: dict[str, Any] = {
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
        "org_id": scope.org_id, "team_id": scope.team_id,
    }
    if scope.org_id is None:
        result["services"] = []
        result["note"] = "service breakdown requires an organization scope"
        return result

    date_strs = aggregator.date_range(from_date, to_date)
    rows = []
    for svc in aggregator.read_known_services(scope.org_id):
        totals = aggregator.read_agg_range(date_strs, org_id=scope.org_id, service=svc)
        total_calls = int(totals["query_count"])
        errors = int(totals["query_error_count"])
        rows.append({
            "service": svc,
            "total_calls": total_calls,
            "errors": errors,
            "error_rate": round(errors / total_calls, 4) if total_calls else 0.0,
            # No per-service latency source exists today (interactions:events
            # carries no duration_ms -- see schemas.py's own docstring);
            # P95/P99 remain the primary performance indicator via
            # /analytics/performance (platform-wide), not this field.
            "avg_latency_ms": None,
        })
    rows.sort(key=lambda r: -r["total_calls"])
    result["services"] = rows
    return result


async def get_performance(from_date: date, to_date: date) -> dict[str, Any]:
    """PLATFORM-WIDE ONLY. See this module's own docstring."""
    hours = aggregator.hours_for_range(
        datetime.combine(from_date, datetime.min.time()),
        datetime.combine(to_date, datetime.max.time()),
    )
    date_strs = aggregator.date_range(from_date, to_date)
    agg = aggregator.read_agg_range(date_strs)

    request_count = int(agg["request_count"])
    error_count = int(agg["request_error_count"])
    error_rate = round(error_count / request_count, 4) if request_count else 0.0
    days = max((to_date - from_date).days + 1, 1)
    throughput_per_day = round(request_count / days, 2)

    prom = await prometheus.query_latency_quantiles(job="api-gateway")
    if prom.get("available"):
        latency_source = "prometheus"
        p50 = prom["p50"] * 1000 if prom["p50"] is not None else None
        p95 = prom["p95"] * 1000 if prom["p95"] is not None else None
        p99 = prom["p99"] * 1000 if prom["p99"] is not None else None
    else:
        latency_source = "events"
        estimated = aggregator.read_platform_latency_percentiles(hours)
        p50, p95, p99 = estimated["p50"], estimated["p95"], estimated["p99"]

    return {
        "scope": "platform",
        "org_id": None,
        "team_id": None,
        "p50_latency_ms": p50, "p95_latency_ms": p95, "p99_latency_ms": p99,
        "error_rate": error_rate,
        "throughput_per_day": throughput_per_day,
        "latency_source": latency_source,
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
    }


async def get_workflows(scope: AnalyticsScope, from_date: date, to_date: date, authorization: Optional[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "from_date": from_date.isoformat(), "to_date": to_date.isoformat(),
        "org_id": scope.org_id, "team_id": scope.team_id,
    }
    if scope.is_platform_admin:
        result.update(
            workflows_run=None, daily=None, success_rate=None,
            note="TES's run-listing API is scoped to the caller's own identity, not by an arbitrary org_id -- unavailable for a platform_admin request",
        )
        return result

    runs = await tes_client.get_runs(authorization)
    if runs is None:
        result.update(workflows_run=None, daily=None, success_rate=None)
        return result

    from_epoch, to_epoch = _epoch_bounds(from_date, to_date)
    by_day: dict[str, int] = {}
    completed = failed = total = 0
    for run in runs:
        created = run.get("created_epoch")
        if not isinstance(created, (int, float)) or not (from_epoch <= created <= to_epoch):
            continue
        total += 1
        day = datetime.fromtimestamp(created).date().isoformat()
        by_day[day] = by_day.get(day, 0) + 1
        state = run.get("state")
        if state == "COMPLETED":
            completed += 1
        elif state == "FAILED":
            failed += 1

    finished = completed + failed
    result["workflows_run"] = total
    result["daily"] = [{"date": d, "count": c} for d, c in sorted(by_day.items())]
    result["success_rate"] = round(completed / finished, 4) if finished else None
    return result


async def get_usage(scope: AnalyticsScope, authorization: Optional[str]) -> dict[str, Any]:
    """Billing/entitlement consumption -- passes omnibioai-billing's own
    numbers through unmodified (task brief: "do not modify billing
    rating logic"). org_id=None (platform-wide/no explicit org) has no
    billing counterpart -- billing is always per-organization."""
    if scope.org_id is None:
        return {"org_id": None, "team_id": scope.team_id, "billing_available": False, "usage": None, "limits": None, "note": "billing usage requires an organization scope"}

    usage_available, usage = await billing_client.get_usage(scope.org_id, authorization)
    limits_available, limits = await billing_client.get_usage_limits(scope.org_id, authorization)

    return {
        "org_id": scope.org_id, "team_id": scope.team_id,
        "billing_available": usage_available and limits_available,
        "usage": usage,
        "limits": limits,
    }
