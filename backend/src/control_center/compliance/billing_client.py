"""HIPAA Basic Compliance Report v0.8.0: thin async httpx client to
omnibioai-billing's usage_events read endpoint (Step 1 of this report,
omnibioai-billing PR feature/hipaa-report-usage-events-read). Same
_get/Authorization-forwarding shape as auth_client.py and
analytics/billing_client.py -- not merged with the latter, see
auth_client.py's own module docstring for why.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Optional

import httpx

BILLING_URL = os.environ.get("BILLING_URL", "http://billing-service:8005")
_TIMEOUT_SECONDS = 10.0

# Same reasoning/value as auth_client.py's own _MAX_PAGES: a bound on how
# much of one report's window this will fan out for before treating the
# result as a truncated sample rather than a complete one.
_MAX_PAGES = 100
_PAGE_SIZE = 200  # usage_event_query_service.py's own _MAX_PAGE_SIZE


async def list_all_usage_events(
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
    resource: Optional[str] = None,
    authorization: Optional[str],
) -> tuple[list[dict], bool]:
    """Pages through GET /billing/organizations/{organization_id}/usage-events
    until exhausted or _MAX_PAGES is hit. Returns (all events, truncated).
    """
    headers = {"Authorization": authorization} if authorization else {}
    items: list[dict] = []
    offset = 0
    page = 0

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        while page < _MAX_PAGES:
            params: dict[str, Any] = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "limit": _PAGE_SIZE,
                "offset": offset,
            }
            if resource is not None:
                params["resource"] = resource

            try:
                r = await client.get(
                    f"{BILLING_URL}/billing/organizations/{organization_id}/usage-events",
                    params=params, headers=headers,
                )
            except httpx.RequestError:
                break
            if r.status_code != 200:
                break

            result = r.json()
            page_events = result.get("events", [])
            items.extend(page_events)

            total_count = result.get("total_count", 0)
            offset += len(page_events)
            page += 1
            if offset >= total_count or not page_events:
                return items, False

    return items, page >= _MAX_PAGES
