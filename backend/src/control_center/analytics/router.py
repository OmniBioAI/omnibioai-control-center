"""The /analytics/* HTTP surface (task brief Section 7). Every route:
1. resolves+enforces scope via `Depends(require_analytics_scope)` (401/403
   handled entirely by that dependency -- no authorization decision is
   made in this file);
2. resolves the date range (`service.resolve_date_range`, default last
   30 days);
3. reads-through a 5-minute Redis cache (`cache.get_or_set_async`) keyed
   by endpoint+scope+range, never computing twice for the same request
   shape within the TTL;
4. delegates all computation to service.py -- no route function contains
   aggregation logic itself.

No new authentication path: the same `require_analytics_scope`
dependency (built on `core.jwt_verify.verify_token`, the one JWT
verifier this whole service already uses) gates every route here.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any, Callable, Coroutine, Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse

from control_center.analytics import cache, service
from control_center.analytics.metrics import API_ERRORS, API_REQUESTS
from control_center.analytics.permissions import AnalyticsScope, require_analytics_scope

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _cache_key(endpoint: str, scope: AnalyticsScope, from_date: date, to_date: date) -> str:
    return f"analytics:{endpoint}:{scope.org_id}:{scope.team_id}:{from_date.isoformat()}:{to_date.isoformat()}"


async def _run(endpoint: str, cache_key: str, compute_coro: Callable[[], Coroutine[Any, Any, dict]]) -> JSONResponse:
    API_REQUESTS.labels(endpoint=endpoint).inc()
    try:
        data = await cache.get_or_set_async(cache_key, endpoint, compute_coro, ttl=cache.DEFAULT_TTL_SECONDS)
    except Exception:
        API_ERRORS.labels(endpoint=endpoint, status_code="500").inc()
        raise
    return JSONResponse(data)


@router.get("/overview")
async def overview(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    key = _cache_key("overview", scope, resolved_from, resolved_to)
    return await _run("overview", key, lambda: service.get_overview(scope, resolved_from, resolved_to, authorization))


@router.get("/queries")
async def queries(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    key = _cache_key("queries", scope, resolved_from, resolved_to)
    return await _run("queries", key, lambda: service.get_queries(scope, resolved_from, resolved_to, authorization))


@router.get("/users")
async def users(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    key = _cache_key("users", scope, resolved_from, resolved_to)
    return await _run("users", key, lambda: service.get_users(scope, resolved_from, resolved_to, authorization))


@router.get("/services")
async def services(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    key = _cache_key("services", scope, resolved_from, resolved_to)
    return await _run("services", key, lambda: service.get_services(scope, resolved_from, resolved_to))


@router.get("/workflows")
async def workflows(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    key = _cache_key("workflows", scope, resolved_from, resolved_to)
    return await _run("workflows", key, lambda: service.get_workflows(scope, resolved_from, resolved_to, authorization))


@router.get("/performance")
async def performance(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    # Still gated by require_analytics_scope (any admin role -- 403 for a
    # regular user) even though the response itself is platform-wide and
    # ignores scope.org_id/team_id entirely -- an authenticated admin of
    # any organization may see platform-wide operational health, but a
    # regular user still may not reach analytics at all.
    _scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    key = f"analytics:performance:platform:{resolved_from.isoformat()}:{resolved_to.isoformat()}"
    return await _run("performance", key, lambda: service.get_performance(resolved_from, resolved_to))


@router.get("/usage")
async def usage(
    authorization: Optional[str] = Header(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> JSONResponse:
    key = f"analytics:usage:{scope.org_id}:{scope.team_id}"
    return await _run("usage", key, lambda: service.get_usage(scope, authorization))


_EXPORTABLE: dict[str, Callable[[AnalyticsScope, date, date, Optional[str]], Coroutine[Any, Any, dict]]] = {
    "overview": lambda scope, f, t, auth: service.get_overview(scope, f, t, auth),
    "queries": lambda scope, f, t, auth: service.get_queries(scope, f, t, auth),
    "users": lambda scope, f, t, auth: service.get_users(scope, f, t, auth),
    "services": lambda scope, f, t, auth: service.get_services(scope, f, t),
    "workflows": lambda scope, f, t, auth: service.get_workflows(scope, f, t, auth),
    "performance": lambda scope, f, t, auth: service.get_performance(f, t),
}


def _rows_for_export(export_type: str, data: dict) -> tuple[list[str], list[list[Any]]]:
    """Turns one service.py response dict into (header, rows) for CSV --
    the "daily trend" shape (queries/users) becomes one row per date, the
    "services" shape becomes one row per service, everything else
    (overview/workflows/performance) becomes one summary row."""
    if export_type in ("queries", "users") and isinstance(data.get("daily"), list):
        header = ["date", "count"]
        rows = [[row.get("date"), row.get("count")] for row in data["daily"]]
        return header, rows
    if export_type == "services":
        header = ["service", "total_calls", "errors", "error_rate", "avg_latency_ms"]
        rows = [
            [r.get("service"), r.get("total_calls"), r.get("errors"), r.get("error_rate"), r.get("avg_latency_ms")]
            for r in data.get("services", [])
        ]
        return header, rows
    scalar_items = [(k, v) for k, v in data.items() if not isinstance(v, (list, dict))]
    return [k for k, _ in scalar_items], [[v for _, v in scalar_items]]


@router.get("/export")
async def export(
    type: str = Query(...),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
    scope: AnalyticsScope = Depends(require_analytics_scope),
) -> StreamingResponse:
    builder = _EXPORTABLE.get(type)
    if builder is None:
        return JSONResponse({"error": f"unknown export type: {type!r}"}, status_code=400)

    resolved_from, resolved_to = service.resolve_date_range(from_date, to_date)
    API_REQUESTS.labels(endpoint="export").inc()
    data = await builder(scope, resolved_from, resolved_to, authorization)

    header, rows = _rows_for_export(type, data)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="analytics_{type}.csv"'},
    )
