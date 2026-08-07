from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# PR A1 (Admin Console Capability Parity -- Tool Execution). Same
# reasoning as routes_billing_proxy.py and every other *_proxy.py in
# this package: no authorization decision is made here. omnibioai-tes's
# own require_permission(WORKFLOW_EXECUTE) dependency (independent JWT
# verification, api/routes_runs.py) decides GET /api/runs and
# GET /api/runs/{run_id} entirely -- this file only relays the
# Authorization header verbatim and preserves the upstream status code.
# GET /api/tools and /api/tools/capabilities are unauthenticated
# upstream today (confirmed by reading api/routes_tools.py -- no
# Depends(...) on either route), so those two are relayed the same way
# but with nothing to forward beyond a possibly-empty Authorization
# header.
#
# TES enforces organization isolation server-side: GET /api/runs
# returns only runs belonging to the caller's own identity.
# organization_id (api/routes_runs.py's list_runs), and a run belonging
# to a different org 404s rather than 403s (_require_same_org, same
# enumeration-oracle avoidance already used elsewhere in this
# ecosystem). There is no org_id path/query parameter to relay -- unlike
# routes_billing_proxy.py's /organizations/{organization_id}/... shape,
# TES has no equivalent "view any org's runs" endpoint for an admin to
# pick a different organization, so this proxy (and the admin page built
# on it) is a flat, self-scoped view, not an org-picker.
#
# Read-only (GET) only, matching this PR's own scope -- no
# /runs/{run_id}/cancel, no /runs/submit. Logs/results are also left out
# of this first PR (potentially large payloads, not needed for a first
# read-only overview) and can be added as their own follow-up routes if
# the page needs a detail drill-down later.
router = APIRouter()

TES_URL = os.environ.get("TES_URL", "http://tes:8081")


async def _proxy(path: str, request: Request) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{TES_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"tes-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "tes-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/tes/tools")
async def list_tools_proxy(request: Request) -> JSONResponse:
    return await _proxy("/api/tools", request)


@router.get("/tes/tools/capabilities")
async def tools_capabilities_proxy(request: Request) -> JSONResponse:
    return await _proxy("/api/tools/capabilities", request)


@router.get("/tes/runs")
async def list_runs_proxy(request: Request) -> JSONResponse:
    return await _proxy("/api/runs", request)


@router.get("/tes/runs/{run_id}")
async def get_run_proxy(run_id: str, request: Request) -> JSONResponse:
    return await _proxy(f"/api/runs/{run_id}", request)
