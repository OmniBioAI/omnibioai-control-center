from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# PR E1 (Admin Settings integration). Deliberately a separate file from
# routes_auth_proxy.py rather than an extension of it, same reasoning
# routes_org_proxy.py's own module comment already documents for the
# identical situation: routes_auth_proxy.py's scope is specifically
# session-flow /auth/* routes (login/validate/refresh/logout), all of
# which forward the omnibioai_session cookie, never the caller's own
# Authorization header (there's no session yet at login time). This
# route needs the opposite -- the caller's own already-issued bearer
# token, forwarded unchanged, no cookie involved -- so it gets its own
# small file with its own _proxy() helper, same tradeoff org_proxy.py's
# comment already accepted (~15 duplicated boilerplate lines, in
# exchange for not growing one file to cover two different auth-
# forwarding mechanisms).
#
# Read-only in this PR (GET only) -- deliberate scope decision, not an
# oversight. omnibioai-auth's own PUT /auth/config (gated by
# manage_config, a real pre-existing seeded permission -- see
# docs/pr-d-admin-placeholder-audit.md §3.4) can set a platform-wide LLM
# API key and cloud credentials; shipping the read side first (visible,
# reviewable, no credential-input UI yet) before adding a write form
# follows the same "read-only first" discipline PR A1/PR A3 already
# applied to their own services' write endpoints. GlobalConfigOut's own
# schema never echoes credential values back regardless of caller role
# (has_llm_api_key/has_cloud_credentials booleans only) -- this proxy
# relays that shape unchanged, it does not add or remove any field.
router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")


async def _proxy(path: str, request: Request) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{IAM_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"auth-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/auth/config")
async def get_platform_config_proxy(request: Request) -> JSONResponse:
    return await _proxy("/auth/config", request)
