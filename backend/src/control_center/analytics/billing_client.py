"""Thin, read-only httpx wrapper over omnibioai-billing's existing
per-organization usage/subscription/entitlement endpoints (task brief
Section 5) -- reuses `routes_dashboard.py::_business_section`'s own
forwarded-Authorization pattern for this exact upstream (same
`{BILLING_URL}/billing/organizations/{id}/...` paths that module already
calls) rather than a new one. Never computes or duplicates any billing
math -- every number here is exactly what omnibioai-billing's own API
already returned; this module only fetches and passes it through.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

BILLING_URL = os.environ.get("BILLING_URL", "http://billing-service:8005")
_TIMEOUT_SECONDS = 5.0


async def _get(path: str, authorization: Optional[str]) -> tuple[bool, Optional[dict]]:
    """Returns (billing_service_available, json_body_or_None).
    `billing_service_available` distinguishes "billing-service
    unreachable" from "reachable, but this org has no subscription yet"
    (a 404) -- same distinction
    routes_dashboard.py::_business_section's own `billing_service_available`
    boolean already makes for this exact upstream; collapsing the two
    would misrepresent an outage as a normal empty state.
    """
    headers = {"Authorization": authorization} if authorization else {}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BILLING_URL}{path}", headers=headers, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return False, None

    if r.status_code != 200:
        return True, None
    try:
        return True, r.json()
    except ValueError:
        return True, None


async def get_usage(org_id: int, authorization: Optional[str]) -> tuple[bool, Optional[dict]]:
    return await _get(f"/billing/organizations/{org_id}/usage", authorization)


async def get_subscription(org_id: int, authorization: Optional[str]) -> tuple[bool, Optional[dict]]:
    return await _get(f"/billing/organizations/{org_id}/subscription", authorization)


async def get_usage_limits(org_id: int, authorization: Optional[str]) -> tuple[bool, Optional[dict]]:
    """Current usage / limit / remaining / percentage-consumed per
    entitled feature -- omnibioai-billing's own
    `/subscription/usage-limits` endpoint (app/routers/billing.py::
    read_subscription_usage_limits) already computes this; not
    recomputed here, per the task brief's explicit "do not modify
    billing rating logic" constraint."""
    return await _get(f"/billing/organizations/{org_id}/subscription/usage-limits", authorization)
