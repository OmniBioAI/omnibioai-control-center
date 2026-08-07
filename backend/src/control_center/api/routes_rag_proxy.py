from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# PR A4 (Admin Console Capability Parity -- RAG/PubMed). Same reasoning
# as every other *_proxy.py: no authorization decision is made here.
#
# RAG corpus metadata endpoints currently authenticate through the
# RAGBIO_API_KEY service credential. Admin Console visibility is
# controlled by control-center admin authorization. This PR does not
# introduce per-user RAG authorization.
#
# Verified directly from omnibioai-rag/ragbio/api/server.py + api/iam.py
# (not assumed): this service runs TWO independent auth models on
# different endpoints, not one --
#   - GET /v1/studies, GET /v1/cache/stats (and /v1/cache, /v1/ingest,
#     /v1/embed, /v1/kg/build, /v1/benchmark -- none of those last five
#     used here) are gated by `_verify`: the bearer token must literally
#     equal the RAGBIO_API_KEY env var (`creds.credentials != api_key`
#     -> 403). A static shared service secret, not a per-user check --
#     the identical convention routes_dashboard.py's own
#     _knowledge_section() already uses for this same upstream
#     ("RAGBIO_API_KEY is a service-held secret... not the caller's own
#     token", same category as ANTHROPIC_API_KEY/OPENAI_API_KEY in
#     routes_llm.py).
#   - POST /v1/query and GET /v1/kg/stats|entity|drug-disease are gated
#     by Depends(require_permission("dataset.read")) -- real per-user
#     JWT, independently verified via the shared iam_client package.
#     None of those are used by this proxy; deliberately deferred to a
#     future "RAG Knowledge Graph Admin Integration" PR that can forward
#     the caller's own Authorization header properly, the way
#     routes_tes_proxy.py/routes_workflow_bundles_proxy.py already do
#     for their own permission-gated routes. Mixing both auth models
#     behind one Admin Console page in one PR would blur which trust
#     model actually applies to which tab.
#
# Because /v1/studies and /v1/cache/stats need the shared secret, not
# the admin's own token, this proxy injects RAGBIO_API_KEY itself --
# server-side, control-center-held, identical to how routes_dashboard.py
# already calls this same upstream -- rather than forwarding the
# caller's Authorization header (which would never equal RAGBIO_API_KEY
# and would always 403). If RAGBIO_API_KEY isn't configured on
# control-center's side, no Authorization header is sent at all and
# whatever RAG's own HTTPBearer/`_verify` responds with (a 403 "Not
# authenticated", or a 503 "RAGBIO_API_KEY not configured on server" if
# RAG's own key is also unset) is relayed unchanged -- this file makes
# no authorization decision of its own, it only decides which secret,
# if any, to attach.
#
# GET /health has no auth on the RAG side at all -- this proxy never
# injects RAGBIO_API_KEY for it, but does still forward the caller's own
# Authorization header if one was sent (harmless, since RAG's /health
# ignores it either way), same "forward whatever's present, fabricate
# nothing" behavior every other proxy in this app already has for its
# own unauthenticated routes (e.g. routes_tes_proxy.py's /tools).
router = APIRouter()

RAG_URL = os.environ.get("RAG_URL", "http://rag:8096")
RAGBIO_API_KEY = os.environ.get("RAGBIO_API_KEY", "")


async def _proxy(path: str, request: Request, *, use_service_key: bool) -> JSONResponse:
    headers = {"Content-Type": "application/json"}
    if use_service_key:
        if RAGBIO_API_KEY:
            headers["Authorization"] = f"Bearer {RAGBIO_API_KEY}"
    else:
        auth_header = request.headers.get("authorization")
        if auth_header:
            headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{RAG_URL}{path}",
                params=request.query_params,
                headers=headers,
            )
    except httpx.RequestError as e:
        return JSONResponse(
            {"error": f"rag-service unreachable: {type(e).__name__}: {e}"}, status_code=503,
        )

    try:
        payload = r.json()
    except ValueError:
        payload = {"error": "rag-service returned a non-JSON response"}
    return JSONResponse(payload, status_code=r.status_code)


@router.get("/rag/studies")
async def list_studies_proxy(request: Request) -> JSONResponse:
    return await _proxy("/v1/studies", request, use_service_key=True)


@router.get("/rag/cache-stats")
async def cache_stats_proxy(request: Request) -> JSONResponse:
    return await _proxy("/v1/cache/stats", request, use_service_key=True)


@router.get("/rag/health")
async def health_proxy(request: Request) -> JSONResponse:
    return await _proxy("/health", request, use_service_key=False)
