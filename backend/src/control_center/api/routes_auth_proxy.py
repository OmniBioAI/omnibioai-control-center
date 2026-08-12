from __future__ import annotations

import json
import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# control.omnibioai.org's Cloudflare Tunnel ingress rule routes directly to
# control-center's own :7070 (see /etc/cloudflared/config.yml's "Admin
# only" group), bypassing nginx-router entirely -- unlike every other
# webstudio.omnibioai.org path, there is no nginx `location ^~ /auth/
# { proxy_pass http://auth; }` in front of this domain to reach
# auth-service. The Admin tab's fetch('/auth/login')/fetch('/auth/validate')
# calls (bare relative paths, deliberately not routed through admApi()
# since /auth/* isn't nested under /_svc/control) otherwise 404 against
# control-center itself, which has no such routes of its own.
#
# These routes mirror nginx-router.conf's own /auth/ proxy, scoped to
# just what the Admin tab needs, using the same internal hostname
# (IAM_URL) api-gateway and model-registry already use to reach
# auth-service.
#
# SSO Phase 2 PR8: added /auth/refresh and /auth/logout, closing a gap
# PR7 confirmed live in production (control.omnibioai.org: /auth/login
# and /auth/validate proxied fine, /auth/refresh and /auth/logout both
# 404'd) -- cc-ui's refresh/logout calls (PR5) were unreachable on this
# deployment path. Both reuse the exact same _proxy_to_auth helper as the
# two existing routes below -- no new auth logic, this service still only
# ever relays to auth-service and returns its response verbatim.
#
# SSO Phase 2 PR13: _proxy_to_auth now also relays the omnibioai_session
# cookie in both directions -- previously it forwarded only the JSON body
# and status code, silently dropping any Set-Cookie from auth-service's
# response (PR10) and never forwarding the browser's own Cookie header
# upstream. Without this, a browser logging in directly on
# control.omnibioai.org would never actually receive the session cookie
# at all (only a browser arriving here already cookied from elsewhere
# would appear to work), and auth-service's own body-or-cookie fallback
# for /auth/refresh (PR10) would never see the cookie either, since each
# proxy hop is an independent HTTP request that doesn't automatically
# carry the original one's cookies.
router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")
SESSION_COOKIE_NAME = "omnibioai_session"


async def _proxy_to_auth(path: str, request: Request, body: bytes | None = None) -> JSONResponse:
    if body is None:
        body = await request.body()

    headers = {"Content-Type": "application/json"}
    # Forward only the one cookie this ecosystem actually uses -- not the
    # raw incoming Cookie header verbatim -- so no unrelated cookie a
    # browser might be holding for this domain leaks to auth-service.
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if session_cookie:
        headers["Cookie"] = f"{SESSION_COOKIE_NAME}={session_cookie}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{IAM_URL}{path}", content=body, headers=headers)
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"auth-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "auth-service returned a non-JSON response"}

    resp = JSONResponse(payload, status_code=r.status_code)
    for set_cookie_value in r.headers.get_list("set-cookie"):
        resp.headers.append("set-cookie", set_cookie_value)
    return resp


@router.post("/auth/login")
async def auth_login_proxy(request: Request) -> JSONResponse:
    return await _proxy_to_auth("/auth/login", request)


@router.post("/auth/validate")
async def auth_validate_proxy(request: Request) -> JSONResponse:
    return await _proxy_to_auth("/auth/validate", request)


@router.post("/auth/refresh")
async def auth_refresh_proxy(request: Request) -> JSONResponse:
    return await _proxy_to_auth("/auth/refresh", request)


# Mode B Phase 2: Workspace Switcher. Same _proxy_to_auth helper as every
# other route in this file, no new logic -- the request body (team_id,
# optionally refresh_token) and the omnibioai_session cookie both pass
# through unmodified, and auth-service's own response (access_token/
# refresh_token JSON body + its Set-Cookie) is relayed back exactly like
# /auth/login and /auth/refresh already are. This service never inspects
# or trusts team_id itself -- it's an opaque relay, same posture as
# every other route here.
@router.post("/auth/switch-team")
async def auth_switch_team_proxy(request: Request) -> JSONResponse:
    return await _proxy_to_auth("/auth/switch-team", request)


@router.post("/auth/logout")
async def auth_logout_proxy(request: Request) -> JSONResponse:
    # SSO Phase 2 PR13: auth-service's LogoutRequest.refresh_token is still
    # required server-side (deliberately not relaxed there -- omnibioai-auth
    # is out of scope for this PR, unlike RefreshRequest which PR10 already
    # made optional). cc-ui no longer stores the refresh token in
    # localStorage to hand back in the body (PR13's "never duplicate
    # refresh token storage in localStorage" requirement), so this fills
    # it in from the omnibioai_session cookie when the frontend's own body
    # omits it -- the same body-or-cookie substitution auth-service itself
    # already does natively for /auth/refresh, done here instead because
    # /auth/logout's contract isn't optional-token-aware upstream.
    raw_body = await request.body()
    try:
        parsed = json.loads(raw_body) if raw_body else {}
    except ValueError:
        parsed = {}

    if not parsed.get("refresh_token"):
        cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
        if cookie_token:
            parsed["refresh_token"] = cookie_token

    return await _proxy_to_auth("/auth/logout", request, body=json.dumps(parsed).encode())
