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

Pre-merge security review finding (2026-08-12): every function here used
to collapse "the fetch failed" and "the fetch succeeded and found
nothing" into the same empty-list/None shape. For a compliance report,
those are not the same thing -- a report that silently renders as "zero
users, zero events" because omnibioai-auth was unreachable is a false
negative, not an empty result. Every function now returns an explicit
status alongside its data (`"ok"` / `"not_found"` / `"unavailable"`, or
a `truncated`/`unavailable` bool pair for the paginated list functions)
so service.py can tell the two apart and surface it in
`sources_unavailable` rather than producing a misleadingly clean report.
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
# stopping here (and telling the caller so, via the returned `truncated`
# flag) beats an unbounded fan-out that could hang the request.
_MAX_PAGES = 100
_PAGE_SIZE = 100


async def _get(path: str, params: dict[str, Any], authorization: Optional[str]) -> tuple[Optional[dict], str]:
    """Returns (body, status) where status is "ok" (200, body is the
    parsed JSON), "not_found" (404 -- the resource genuinely doesn't
    exist), or "unavailable" (network error, timeout, or any other
    non-200 -- the resource's existence is simply unknown). Callers that
    only care about "did this succeed" can check `status == "ok"`;
    get_organization cares about the not_found/unavailable distinction
    specifically (see its own docstring)."""
    headers = {"Authorization": authorization} if authorization else {}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            r = await client.get(f"{IAM_URL}{path}", params=params, headers=headers)
    except httpx.RequestError:
        return None, "unavailable"
    if r.status_code == 404:
        return None, "not_found"
    if r.status_code != 200:
        return None, "unavailable"
    return r.json(), "ok"


async def get_organization(organization_id: int, authorization: Optional[str]) -> tuple[Optional[dict], str]:
    """GET /orgs/{organization_id} -- used for the report's own display
    name (organization_name). The not_found/unavailable distinction
    matters here specifically: service.py raises a real 404
    (OrganizationNotFoundError) on "not_found" -- a report for an org
    that doesn't exist should say so, not silently render an empty
    report labeled "Organization #N" -- but degrades to a placeholder
    label (and records the source as unavailable) on "unavailable",
    since a transient auth-service outage says nothing about whether the
    org actually exists.
    """
    return await _get(f"/orgs/{organization_id}", {}, authorization)


async def get_org_members(organization_id: int, authorization: Optional[str]) -> tuple[list[dict], str]:
    """GET /orgs/{organization_id}/members -- [{user_id, email, status,
    roles}, ...]. Unpaginated (the endpoint itself returns a plain list,
    no page/total envelope) -- same "confirmed unpaginated before relying
    on it" gate analytics/service.py's own team-roster fetch documents
    for its sibling call. Returns ([], status) on any failure -- status
    is "not_found"/"unavailable" from the underlying fetch, or
    "unavailable" if the response wasn't the list shape expected (a
    malformed/unexpected body is treated the same as a fetch failure,
    not silently accepted as "zero members").
    """
    result, status = await _get(f"/orgs/{organization_id}/members", {}, authorization)
    if status == "ok" and isinstance(result, list):
        return result, "ok"
    return [], status if status != "ok" else "unavailable"


async def list_all_audit_events(
    *,
    organization_id: Optional[int],
    start_date: datetime,
    end_date: datetime,
    event_type: Optional[str] = None,
    authorization: Optional[str],
) -> tuple[list[dict], bool, bool]:
    """Pages through GET /platform/audit-events until exhausted or
    _MAX_PAGES is hit. Returns (items, truncated, unavailable).

    `truncated=True` means the pagination cap was hit -- real data likely
    exists beyond what was fetched (the report window is probably too
    wide for a "basic" report). `unavailable=True` means a page fetch
    itself failed (network error or non-200) -- `items` holds whatever
    was collected before the failure, which must be treated as an
    unreliable partial sample, not a definitive (even if small) result.
    These are deliberately distinct signals: a wide-but-working report
    should say "truncated", not "unavailable" -- only a genuine fetch
    failure should say the latter.

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

        result, status = await _get("/platform/audit-events", params, authorization)
        if status != "ok":
            # A fetch failure mid-pagination still leaves `items` holding
            # whatever earlier pages already succeeded -- returned as-is,
            # but flagged unavailable so the caller never mistakes a
            # partial sample for a complete (if small) result.
            return items, False, True

        page_items = result.get("items", [])
        items.extend(page_items)

        total_pages = result.get("total_pages", 0)
        if page >= total_pages or not page_items:
            return items, False, False
        page += 1

    return items, True, False
