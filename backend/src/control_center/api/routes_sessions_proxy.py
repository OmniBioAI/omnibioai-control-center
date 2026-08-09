from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

# PR-C (Control Center Sessions Integration). Same reasoning as every
# other proxy file in this directory (routes_audit_proxy.py in
# particular, whose shape this mirrors exactly): no authorization
# decision is made here -- omnibioai-auth's own self-service session
# endpoints (GET /sessions, GET /sessions/{session_id}, POST
# /sessions/{session_id}/revoke -- Phase 4 PR-A) already scope every
# request to the calling user's own `sub` claim and 404 (not 403) on
# someone else's session_id; this file only relays the caller's own
# Authorization header and never inspects, caches, or logs the request/
# response bodies it forwards.
#
# session_id path segments are opaque uuid4 strings (see PR-A's
# UserSession.session_id), not integers -- unlike user_id/org_id path
# params elsewhere in this directory, so every route below takes `str`.
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


# ---------------- Sessions (self-service) ----------------

@router.get("/sessions")
async def list_my_sessions_proxy(request: Request) -> Response:
    return await _proxy("GET", "/sessions", request)


@router.get("/sessions/{session_id}")
async def get_my_session_proxy(session_id: str, request: Request) -> Response:
    return await _proxy("GET", f"/sessions/{session_id}", request)


@router.post("/sessions/{session_id}/revoke")
async def revoke_my_session_proxy(session_id: str, request: Request) -> Response:
    return await _proxy("POST", f"/sessions/{session_id}/revoke", request)
