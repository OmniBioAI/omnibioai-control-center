"""Thin, read-only httpx wrapper over TES's existing Run Store API (task
brief Section 5's "workflow executions") -- reuses
`routes_dashboard.py::_workflow_section`'s own `GET {TES_URL}/api/runs`
call (forwarded Authorization, no authorization decision made here)
rather than inventing a `workflow.*` interactions:events producer that
doesn't exist anywhere in this workspace today. Whether/how `/api/runs`
can be filtered by organization is confirmed and documented at the call
site in service.py (a later PR) per this feature's own hard verification
requirement -- this module only fetches the raw list; it does not assume
a filtering contract that hasn't been confirmed.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

TES_URL = os.environ.get("TES_URL", "http://tes:8081")
_TIMEOUT_SECONDS = 5.0


async def get_runs(authorization: Optional[str]) -> Optional[list[dict[str, Any]]]:
    """Returns the raw `GET /api/runs` list, or None on any failure
    (unreachable, timeout, non-2xx, non-list body) -- same
    best-effort-degrade-to-None contract every other client in this
    package uses. No `authorization` -> no header sent, matching
    `_workflow_section`'s own behavior (TES's own auth then decides what
    an unauthenticated caller sees, if anything -- no decision made
    here).
    """
    headers = {"Authorization": authorization} if authorization else {}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TES_URL}/api/runs", headers=headers, timeout=_TIMEOUT_SECONDS)
        if r.status_code >= 400:
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, list) else None
