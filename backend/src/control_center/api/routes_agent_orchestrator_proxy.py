from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# Agentic AI nav item (feature/agentic-ai-navbar). Same reasoning as
# routes_tes_proxy.py / routes_model_registry_proxy.py / routes_rag_proxy.py:
# no authorization decision is made here, this just relays the caller's
# Authorization header unchanged. GET /api/agent/graphs/ itself
# (omnibioai-workbench's services/agent_orchestrator/views.py:api_graphs)
# has no Depends(...)/login_required of its own -- but reading that view in
# isolation is misleading: omnibioai-workbench registers
# plugins/multi_agent_bio_orchestrator/middleware.py's AuthenticationMiddleware
# globally in settings.py, and its path guard (`path.startswith('/api/') or
# ...`) matches every /api/* route project-wide despite that middleware's
# own comment claiming it's scoped to its own plugin mount -- confirmed
# live: GET /api/agent/graphs/ 401s with no token against a real running
# instance. So an Authorization header genuinely is required in practice;
# this proxy already forwarded it unconditionally (same as every other
# *_proxy.py here), so no code change was needed once this was found, only
# this comment.
#
# Read-only (GET) only, matching this PR's scope. api_graphs() calls
# list_graphs(include_disabled=False) with no way to opt into disabled
# graphs via a query param -- a graph_id with "enabled": false in
# definitions.json simply never appears in this response at all, it isn't
# returned with enabled=false. Every graph this proxy can ever surface is
# therefore enabled=true; that's the real, current shape of the upstream
# endpoint, not a filter this file adds. Every other agent_orchestrator
# route (api/agent/graphs/add|delete/, ops/agent/route/, ops/agent/run/...)
# is either a write action (staff-only or otherwise) or gated behind the
# separate OMNIBIOAI_ENABLE_AGENTIC_AI feature flag (router.route(), not
# api_graphs()) -- none of that is proxied here.
#
# There is no list-all-runs endpoint anywhere in agent_orchestrator today
# (only POST ops/agent/run/ to start one and GET .../status by run_id once
# you already have one) -- so there is nothing here to back a "recent runs"
# proxy route with; see AgenticAIPage.tsx's own Recent Runs section (in its
# per-graph drill-in) for how that absence is surfaced to the admin instead
# of being papered over.
router = APIRouter()

WORKBENCH_URL = os.environ.get("WORKBENCH_URL", "http://workbench:8000")


async def _proxy(path: str, request: Request) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{WORKBENCH_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"workbench-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "workbench-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/agent-orchestrator/graphs")
async def list_agent_graphs_proxy(request: Request) -> JSONResponse:
    return await _proxy("/api/agent/graphs/", request)
