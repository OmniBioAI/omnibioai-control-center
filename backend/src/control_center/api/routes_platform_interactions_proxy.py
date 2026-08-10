from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR-B5-B (Control Center Interaction Admin View). Same reasoning as
# every other proxy file in this directory (routes_audit_proxy.py in
# particular, whose shape this mirrors exactly): no authorization
# decision is made here -- omnibioai-auth's own
# require_permission(manage_all_orgs) on GET /platform/interactions
# (PR-B5-A) decides every request, pre-existing (reused, not new) and
# unmodified by this PR. A pure relay: never inspects, caches, or logs
# the response bodies it forwards -- matters here because an
# interaction's own metadata could in principle be large or
# sensitive-looking even though the write path (interaction_service.py's
# own _redact_metadata, reused by app/workers/interaction_consumer.py)
# already strips secret-shaped keys before persistence; see
# frontend/cc-ui/src/interactions.ts's own maskSensitiveFields for the
# UI-side defense-in-depth layer this PR adds on top, not instead of,
# that guarantee.
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


# ---------------- Interactions (read-only, platform-admin only) -----------

# GET only -- no PATCH/PUT/DELETE route is proxied here because
# omnibioai-auth exposes none (PR-B5-A is GET /platform/interactions[/{id}]
# only). Interactions are a durable ledger, immutable through this proxy
# by simply never defining any other verb -- same convention
# routes_audit_proxy.py already established for AuditEvent.

@router.get("/platform/interactions")
async def list_interactions_proxy(request: Request) -> Response:
    return await _proxy("GET", "/platform/interactions", request)


@router.get("/platform/interactions/{interaction_id}")
async def get_interaction_proxy(interaction_id: str, request: Request) -> Response:
    return await _proxy("GET", f"/platform/interactions/{interaction_id}", request)
