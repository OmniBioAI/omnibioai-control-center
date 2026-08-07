from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# PR A3 (Admin Console Capability Parity -- Workflows). Same reasoning
# as routes_tes_proxy.py: no authorization decision is made here.
# Unlike routes_model_registry_proxy.py's three routes, every route this
# proxy relays IS gated on the omnibioai-workflow-bundles side today --
# confirmed by reading api/server.py + api/iam.py directly, not assumed
# from routes_dashboard.py's own (stale -- see below) comment. Depends(
# require_permission("workflow.read")) guards GET /v1/workflows,
# GET /v1/workflows/{name}, GET /v1/categories, and
# GET /v1/workflows/{id}/inputs; Depends(require_permission(
# "workflow.execute")) guards GET /v1/runs and GET /v1/runs/{run_id}.
# Both are pre-existing permissions (workflow-bundles' own merged IAM
# integration) -- this proxy adds none, it only relays whatever
# 401 (missing/invalid token) or 403 (missing permission) that
# dependency raises, same as every other *_proxy.py.
#
# routes_dashboard.py's _workflow_section() calls GET /v1/categories
# with no Authorization header at all, on the assumption workflow-
# bundles is unauthenticated -- that assumption is false today (see
# above), so that call is presumably already failing with a 403 in
# production. Not this PR's file to fix; flagging in case it's picked
# up separately.
#
# IMPORTANT -- multi-tenancy gap, not introduced by this PR, not fixable
# here: GET /v1/runs has NO organization filtering upstream. Its own
# source comment states plainly that "organization_id" on each run
# record is "logging/audit context only -- not an access-control
# boundary" and that org isolation for runs is "deferred, tracked as a
# follow-up pending a multi-tenant data model migration." Unlike TES's
# GET /api/runs (which filters to identity.organization_id server-side),
# this endpoint returns every organization's runs to any caller holding
# workflow.execute. This proxy relays that behavior unchanged -- it does
# not attempt to filter client-side, since a client-side filter here
# would be exactly the kind of "duplicated authorization logic" this
# PR's own rules forbid, and would give a false impression of isolation
# that doesn't actually exist server-side. WorkflowsPage.tsx surfaces
# this explicitly to the admin viewing it rather than hiding it.
#
# Read-only (GET) only, matching this PR's own scope -- no
# PATCH /v1/workflows/{id}/toggle (workflow.manage), no
# POST /v1/workflows/{id}/run (workflow.execute, a write), no
# POST /v1/register (workflow.publish).
router = APIRouter()

WORKFLOW_BUNDLES_URL = os.environ.get("WORKFLOW_BUNDLES_URL", "http://workflow-bundles:8098")


async def _proxy(path: str, request: Request) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{WORKFLOW_BUNDLES_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"workflow-bundles-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "workflow-bundles-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/workflow-bundles/workflows")
async def list_workflows_proxy(request: Request) -> JSONResponse:
    return await _proxy("/v1/workflows", request)


@router.get("/workflow-bundles/workflows/{name}")
async def get_workflow_versions_proxy(name: str, request: Request) -> JSONResponse:
    return await _proxy(f"/v1/workflows/{name}", request)


@router.get("/workflow-bundles/categories")
async def list_categories_proxy(request: Request) -> JSONResponse:
    return await _proxy("/v1/categories", request)


@router.get("/workflow-bundles/workflows/{workflow_id}/inputs")
async def get_workflow_inputs_proxy(workflow_id: int, request: Request) -> JSONResponse:
    return await _proxy(f"/v1/workflows/{workflow_id}/inputs", request)


@router.get("/workflow-bundles/runs")
async def list_runs_proxy(request: Request) -> JSONResponse:
    return await _proxy("/v1/runs", request)


@router.get("/workflow-bundles/runs/{run_id}")
async def get_run_proxy(run_id: str, request: Request) -> JSONResponse:
    return await _proxy(f"/v1/runs/{run_id}", request)
