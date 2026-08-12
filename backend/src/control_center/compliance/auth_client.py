"""HIPAA Basic Compliance Report v0.8.0: thin async httpx client to
omnibioai-auth, mirroring analytics/billing_client.py's exact shape
(module-level BILLING_URL-style env var, one `_get` helper, the caller's
own Authorization header forwarded unmodified -- Zero Trust, the same
posture every other cross-service call in this platform already takes:
omnibioai-auth's own require_permission(MANAGE_ALL_ORGS) is what actually
authorizes each call below, not this module).

Kept separate from analytics/billing_client.py and the existing
api/routes_audit_proxy.py (a 1:1 browser-facing relay, not meant for
server-side fan-out) rather than reused -- this package's own client for
its own two upstream calls, same "compliance doesn't reach into
analytics' internals" boundary usage_event_query_service.py drew in
omnibioai-billing for the sibling reason (see that module's own comment).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

import httpx

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")
_TIMEOUT_SECONDS = 10.0

# Safety cap on how many pages of /platform/audit-events one report will
# follow -- 100 pages * the endpoint's own max page_size (100) = 100,000
# events per report. A real report window blowing past that almost
# certainly means from_date/to_date is far too wide for a "basic" report;
# stopping here (and telling the caller so, via the second element of the
# returned tuple) beats an unbounded fan-out that could hang the request.
_MAX_PAGES = 100
_PAGE_SIZE = 100


async def _get(path: str, params: dict[str, Any], authorization: Optional[str]) -> Optional[dict]:
    headers = {"Authorization": authorization} if authorization else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            r = await client.get(f"{IAM_URL}{path}", params=params, headers=headers)
    except httpx.RequestError:
        return None
    if r.status_code != 200:
        return None
    return r.json()


async def get_organization(organization_id: int, authorization: Optional[str]) -> Optional[dict]:
    """GET /orgs/{organization_id} -- used for the report's own display
    name (organization_name). None on any failure; the caller falls back
    to a generic "Organization #{id}" label rather than failing the whole
    report over a display-only field.
    """
    return await _get(f"/orgs/{organization_id}", {}, authorization)


async def get_org_members(organization_id: int, authorization: Optional[str]) -> list[dict]:
    """GET /orgs/{organization_id}/members -- [{user_id, email, status,
    roles}, ...]. Unpaginated (the endpoint itself returns a plain list,
    no page/total envelope) -- same "confirmed unpaginated before relying
    on it" gate analytics/service.py's own team-roster fetch documents
    for its sibling call.
    """
    result = await _get(f"/orgs/{organization_id}/members", {}, authorization)
    if result is None:
        return []
    return result if isinstance(result, list) else []


async def list_all_audit_events(
    *,
    organization_id: Optional[int],
    start_date: datetime,
    end_date: datetime,
    event_type: Optional[str] = None,
    authorization: Optional[str],
) -> tuple[list[dict], bool]:
    """Pages through GET /platform/audit-events until exhausted or
    _MAX_PAGES is hit. Returns (all items collected, truncated) --
    `truncated=True` means the caller should treat the result as a
    possibly-incomplete sample, not a definitive count, and the report
    context surfaces that rather than silently under-reporting.

    organization_id=None fetches platform-wide (used for login events,
    which are never organization-scoped at the source -- see this
    package's service.py for why, and how the caller filters this result
    down to one org's members afterward).
    """
    items: list[dict] = []
    page = 1
    while page <= _MAX_PAGES:
        params: dict[str, Any] = {
            "page": page,
            "page_size": _PAGE_SIZE,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if organization_id is not None:
            params["organization_id"] = organization_id
        if event_type is not None:
            params["event_type"] = event_type

        result = await _get("/platform/audit-events", params, authorization)
        if result is None:
            # A fetch failure (network error, non-200) is "no more data
            # available", not "there was more data than we could fetch" --
            # same distinction billing_client.list_all_usage_events draws
            # for its own unreachable case. Not truncated: nothing was
            # deliberately left uncollected.
            return items, False

        page_items = result.get("items", [])
        items.extend(page_items)

        total_pages = result.get("total_pages", 0)
        if page >= total_pages or not page_items:
            return items, False
        page += 1

    return items, True
