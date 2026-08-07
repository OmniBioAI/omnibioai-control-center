from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# PR A2 (Admin Console Capability Parity -- AI Models). Same reasoning
# as routes_tes_proxy.py and routes_billing_proxy.py: no authorization
# decision is made here. Unlike TES's /runs endpoints, none of the three
# routes this proxy relays are gated at all on the omnibioai-model-
# registry side today -- confirmed by reading service/app/main.py
# directly: GET /v1/models, GET /health, and GET /v1/auth/status have no
# Depends(require_auth) (only the write endpoints -- /v1/register,
# /v1/promote, /v1/tags, /v1/versions/patch, /v1/stage -- and the run-
# logging endpoints do). model-registry does have its own auth module
# (require_auth/require_write_auth, gated by a single model.use
# permission via the centralized IAM client, active only when that
# service's own auth_enabled config is set), it's just not applied to
# these three reads. The Authorization header is still forwarded
# unchanged below, same as every other *_proxy.py, so this proxy keeps
# working unmodified if that upstream posture ever changes -- this file
# makes no assumption either way, it just relays.
#
# Read-only (GET) only, matching this PR's own scope -- no
# /v1/register, /v1/promote, /v1/tags, /v1/versions/patch, /v1/stage.
# model-registry's read side already returns one row per registered
# *version*, not per distinct model (confirmed: GET /v1/models globs
# every version's model_meta.json) -- both the "Registered Models" and
# "Model Versions" admin UI tabs are built from this single endpoint's
# response, grouped differently client-side, not two separate upstream
# calls.
router = APIRouter()

MODEL_REGISTRY_URL = os.environ.get("MODEL_REGISTRY_URL", "http://model-registry:8095")


async def _proxy(path: str, request: Request) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    auth_header = request.headers.get("authorization")
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{MODEL_REGISTRY_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"model-registry-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "model-registry-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/model-registry/models")
async def list_models_proxy(request: Request) -> JSONResponse:
    # Query params (task, model_name, metric_gte) pass through untouched
    # -- model-registry's own list_models() reads them directly off the
    # request, this proxy makes no decision about which filters are
    # valid.
    return await _proxy("/v1/models", request)


@router.get("/model-registry/health")
async def health_proxy(request: Request) -> JSONResponse:
    return await _proxy("/health", request)


@router.get("/model-registry/auth-status")
async def auth_status_proxy(request: Request) -> JSONResponse:
    return await _proxy("/v1/auth/status", request)
