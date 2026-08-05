from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR11.4b (Enterprise Identity Audit Trail Foundation). Same reasoning
# as every other proxy file in this directory: no authorization
# decision is made here -- omnibioai-auth's own require_permission
# (manage_all_orgs) on GET /platform/audit-events decides every
# request, pre-existing (reused, not new) and unmodified by this PR. A
# pure relay: never inspects, caches, or logs the response bodies it
# forwards -- matters here because an audit event's own metadata could
# in principle be large or sensitive-looking even though no call site
# in omnibioai-auth ever writes a real secret into one (see
# docs/pr11-identity-audit-discovery.md and docs/admin-console-pr11-
# audit-logs.md for the full secret-exclusion note).
router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")


async def _proxy(method: str, path: str, request: Request) -> Response:
    body = await request.body()
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(
                method,
                f"{IAM_URL}{path}",
                params=request.query_params,
                content=body if method in ("POST", "PATCH", "PUT") else None,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"auth-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    if not r.content:
        return Response(status_code=r.status_code)

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


# ---------------- Audit events (read-only, platform-admin only) -----------

# GET only -- no PATCH/PUT/DELETE route is proxied here because
# omnibioai-auth exposes none. Audit events are immutable structurally,
# not by convention (see routes_platform_audit.py's own docstring); this
# proxy inherits that by simply never defining any other verb.
@router.get("/platform/audit-events")
async def list_audit_events_proxy(request: Request) -> Response:
    return await _proxy("GET", "/platform/audit-events", request)
