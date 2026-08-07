from __future__ import annotations

"""PR10: Live Platform Dashboard.

Single aggregation endpoint (GET /dashboard/summary) that fans out to the
existing APIs of every service the Overview dashboard wants a number
from, plus control-center's own already-existing checks -- no new
service is stood up anywhere, this module only calls things that already
exist, exactly the same "control center as read-only orchestration
layer" principle routes_org_proxy.py etc. already established for
omnibioai-auth.

Auth model, deliberately NOT a single `Depends(require_permission(...))`
on the whole router (unlike summary_router/docker_router/config_router/
services_router): this endpoint aggregates data that lives behind
several *different* trust boundaries, and gating it behind one
permission would either over-restrict (a platform-admin-only user, who
today can already see Organizations/Users via /platform/orgs directly,
would lose that on this page if gated by platform.manage_infra) or
under-restrict. Instead:
  - Identity (auth-service) / Workflow (TES) sections: the caller's own
    Authorization header is forwarded as-is to each upstream call, which
    independently re-validates it and 401s/403s on its own terms --
    exactly what routes_org_proxy.py already does. No authorization
    decision is made here.
  - AI Platform (model-registry) / part of Workflow (workflow-bundles):
    both upstream APIs are unauthenticated today (confirmed by reading
    their source, not assumed) -- called with no header.
  - Knowledge (RAG): RAGBIO_API_KEY is a service-held secret (like
    ANTHROPIC_API_KEY/OPENAI_API_KEY in routes_llm.py), not the caller's
    own token -- forwarded only if control-center itself has it
    configured.
  - Infrastructure / Operations: this is the one section computed
    in-process (containers/gpu/storage/health/known-issues) rather than
    over HTTP, so there is no upstream service to delegate the
    authorization decision to. summary_router/docker_router already gate
    the equivalent data behind platform.manage_infra -- reusing those
    functions directly here would silently bypass that existing gate, so
    this section is included only when `_has_permission` confirms the
    caller's own token carries platform.manage_infra, checked locally
    with the same verify_token() core/auth.py's require_permission uses,
    just without raising.
  - Business (PR C, replacing a PR10-era hardcoded-null placeholder --
    see _business_section()'s own docstring for the full history): the
    caller's own Authorization header is forwarded to IAM's own /orgs
    (membership-scoped, not /platform/orgs) to resolve which
    organization to show, then to omnibioai-billing's own
    /organizations/{id}/subscription and /organizations/{id}/usage --
    same forward-and-let-the-upstream-decide posture as Identity/
    Workflow above, no authorization decision made here either.

Every section that isn't visible/reachable/configured for a given caller
is `null` in the response, never fabricated -- the frontend renders
those as "Preview data"/"--", matching the same honesty convention
Phase 2's dashboard cards already established.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from control_center.api.routes_docker import get_containers_status
from control_center.api.routes_llm import get_llms
from control_center.checks.gpu import get_gpu_status
from control_center.checks.known_issues import KNOWN_ISSUES_PATH_DEFAULT, list_known_issues
from control_center.core.jwt_verify import TokenInvalid, verify_token
from control_center.core.runner import run_all_checks
from control_center.checks.disk import run_disk_checks
from control_center.core.settings import load_settings
from control_center.api.routes_storage import _compute_storage
from pathlib import Path

router = APIRouter()

IAM_URL = os.environ.get("IAM_URL", "http://auth-service:8001")
MODEL_REGISTRY_URL = os.environ.get("MODEL_REGISTRY_URL", "http://model-registry:8095")
RAG_URL = os.environ.get("RAG_URL", "http://rag:8096")
RAGBIO_API_KEY = os.environ.get("RAGBIO_API_KEY", "")
WORKFLOW_BUNDLES_URL = os.environ.get("WORKFLOW_BUNDLES_URL", "http://workflow-bundles:8098")
TES_URL = os.environ.get("TES_URL", "http://tes:8081")
BILLING_URL = os.environ.get("BILLING_URL", "http://billing-service:8005")

_TIMEOUT = 5.0


def _has_permission(authorization: Optional[str], permission: str) -> bool:
    """Non-raising counterpart to core.auth.require_permission -- used only
    to decide whether to include the in-process Infrastructure/Operations
    section, never to reject the request outright (a missing/insufficient
    token just means that one section comes back null, like every other
    section here)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = verify_token(token)
    except TokenInvalid:
        return False
    return permission in (payload.get("permissions") or [])


async def _get_json(
    client: httpx.AsyncClient, url: str, *, headers: dict | None = None, params: dict | None = None,
) -> Any:
    """Best-effort GET -- returns None on any failure (unreachable,
    timeout, non-2xx, non-JSON) rather than raising, so one slow/down
    upstream degrades only its own section of the dashboard instead of
    failing the whole request."""
    try:
        r = await client.get(url, headers=headers, params=params, timeout=_TIMEOUT)
        if r.status_code >= 400:
            return None
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


async def _identity_section(client: httpx.AsyncClient, authorization: Optional[str]) -> dict:
    if not authorization:
        return {"organizations": None, "users": None, "teams": None, "roles": None, "active_sessions": None}

    headers = {"Authorization": authorization}
    orgs, users, roles = await asyncio.gather(
        _get_json(client, f"{IAM_URL}/platform/orgs", headers=headers, params={"page": 1, "page_size": 100}),
        _get_json(client, f"{IAM_URL}/platform/users", headers=headers, params={"page": 1, "page_size": 1}),
        _get_json(client, f"{IAM_URL}/platform/roles", headers=headers),
    )

    organizations = orgs.get("total") if isinstance(orgs, dict) else None
    # Approximation: sums team_count across only the first 100 orgs
    # (platform/orgs' own page_size cap) -- exact for any platform with
    # <=100 organizations, an undercount beyond that. No platform-wide
    # "teams" endpoint exists to do better without N+1 per-org calls.
    teams = (
        sum(o.get("team_count", 0) for o in orgs["items"])
        if isinstance(orgs, dict) and isinstance(orgs.get("items"), list)
        else None
    )
    users_total = users.get("total") if isinstance(users, dict) else None
    roles_total = len(roles) if isinstance(roles, list) else None

    return {
        "organizations": organizations,
        "users": users_total,
        "teams": teams,
        "roles": roles_total,
        # No refresh-token/session-listing endpoint exists anywhere in
        # omnibioai-auth's API today (confirmed by reading app/api/* --
        # RefreshToken is a DB model with no route exposing it). Always
        # null, not estimated.
        "active_sessions": None,
    }


_BUSINESS_NULL = {
    "organization_id": None, "organization_name": None, "plan_name": None,
    "subscription_status": None, "usage_services_count": None, "billing_service_available": None,
}


async def _business_section(client: httpx.AsyncClient, authorization: Optional[str]) -> dict:
    """PR C: replaces the PR10-era hardcoded-null placeholder. That
    placeholder's own comment claimed "no billing/subscription/credits
    system exists anywhere in this workspace" -- true when PR10 shipped,
    false since PR14.4-14.7 and PR B built and proxied exactly that
    system (see routes_billing_proxy.py). This section reuses it
    read-only, same as every other section in this file.

    No platform-wide billing aggregate exists (omnibioai-billing's own
    reporting API is entirely org-scoped -- confirmed by reading
    app/routers/billing.py directly, see docs/pr-b-billing-usage-
    consolidation.md), so unlike identity/ai_platform/knowledge/workflow
    this section cannot show a platform total. It shows the *caller's
    own* organization's billing instead -- same "my org" resolution
    BillingPage.tsx's own useOrgLabel() already relies on client-side
    (fetchMyOrg/fetchMyOrgs -> GET /orgs, IAM's own membership-scoped
    listing, not the platform-admin-only /platform/orgs), just resolved
    server-side here. A platform admin with no personal org membership
    still sees null/"Preview data" here, same as everyone else that
    section's own convention already covers -- this is not a
    "fabricate a total" shortcut.

    organization_id/organization_name/plan_name/subscription_status
    come from the caller's first org membership + its subscription (both
    proxied, independently re-verified by their own services, same
    forwarded-Authorization pattern as every other section here).
    usage_services_count is the count of distinct (service, action,
    resource) dimensions with recorded consumption this period (GET
    /organizations/{id}/usage, added by PR B) -- a count, not a
    computed metric; no math happens in this file.
    billing_service_available distinguishes "the billing service itself
    is unreachable" from "this org has no subscription yet" (a 404) --
    both would otherwise collapse to the same null via the generic
    _get_json() helper, and conflating them would misrepresent an
    outage as a normal empty state.
    """
    if not authorization:
        return dict(_BUSINESS_NULL)

    headers = {"Authorization": authorization}
    my_orgs = await _get_json(client, f"{IAM_URL}/orgs", headers=headers)
    if not isinstance(my_orgs, list) or not my_orgs:
        return dict(_BUSINESS_NULL)

    org = my_orgs[0]
    org_id = org.get("id")
    org_name = org.get("name")

    try:
        sub_resp = await client.get(
            f"{BILLING_URL}/billing/organizations/{org_id}/subscription", headers=headers, timeout=_TIMEOUT,
        )
        billing_available = True
        subscription = sub_resp.json() if sub_resp.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        billing_available = False
        subscription = None

    usage = await _get_json(client, f"{BILLING_URL}/billing/organizations/{org_id}/usage", headers=headers)
    usage_services_count = (
        len(usage["services"]) if isinstance(usage, dict) and isinstance(usage.get("services"), list) else None
    )

    return {
        "organization_id": org_id,
        "organization_name": org_name,
        "plan_name": subscription.get("plan_name") if isinstance(subscription, dict) else None,
        "subscription_status": subscription.get("status") if isinstance(subscription, dict) else None,
        "usage_services_count": usage_services_count,
        "billing_service_available": billing_available,
    }


def _dedupe_models(models: list[dict]) -> tuple[int, int]:
    """model-registry's GET /v1/models returns one row per registered
    *version*, not per distinct model -- dedupe on (task, model_name) so
    "Registered Models"/"Active Models" count models, not versions.
    "Active" has no boolean field in this service; a model counts as
    active if any of its versions has stage in (staging, production) --
    the same convention model-registry's own POST /v1/stage uses for
    those two stage values."""
    by_model: dict[tuple[str, str], list[str]] = {}
    for row in models:
        key = (row.get("task"), row.get("model_name"))
        by_model.setdefault(key, []).append(row.get("stage") or "none")
    total = len(by_model)
    active = sum(1 for stages in by_model.values() if any(s in ("staging", "production") for s in stages))
    return total, active


async def _ai_platform_section(client: httpx.AsyncClient) -> dict:
    models, llms = await asyncio.gather(
        _get_json(client, f"{MODEL_REGISTRY_URL}/v1/models"),
        get_llms(),  # control-center's own existing /llms logic, reused in-process
    )

    registered = active = None
    if isinstance(models, list):
        registered, active = _dedupe_models(models)

    llm_providers = None
    if isinstance(llms, JSONResponse):
        body = json.loads(llms.body)
        api_keys = body.get("api_keys", {})
        llm_providers = sum(1 for v in api_keys.values() if v.get("configured"))
        if body.get("ollama", {}).get("status") == "running":
            llm_providers += 1

    return {
        "registered_models": registered,
        "active_models": active,
        # model-registry has no concept of an "embedding" model type
        # anywhere in its schema (task is a freeform string) -- confirmed
        # by reading its full source, not a fetch failure.
        "embedding_models": None,
        "llm_providers": llm_providers,
    }


async def _knowledge_section(client: httpx.AsyncClient) -> dict:
    if not RAGBIO_API_KEY:
        return {"rag_collections": None, "indexed_documents": None, "indexed_publications": None, "knowledge_bases": None}

    data = await _get_json(client, f"{RAG_URL}/v1/studies", headers={"Authorization": f"Bearer {RAGBIO_API_KEY}"})
    studies = data.get("studies") if isinstance(data, dict) else None
    if not isinstance(studies, list):
        return {"rag_collections": None, "indexed_documents": None, "indexed_publications": None, "knowledge_bases": None}

    collections = len(studies)
    documents = sum(s.get("abstract_count", 0) for s in studies)
    return {
        "rag_collections": collections,
        "indexed_documents": documents,
        # RAG's only indexed corpus today is PubMed abstracts -- "documents"
        # and "publications" are the same underlying abstract_count sum,
        # not two independently-tracked figures. Same for "Knowledge
        # Bases" vs. "RAG Collections": ragbio has one aggregation unit
        # ("study"), no separate knowledge-base concept.
        "indexed_publications": documents,
        "knowledge_bases": collections,
    }


async def _workflow_section(client: httpx.AsyncClient, authorization: Optional[str]) -> dict:
    categories = await _get_json(client, f"{WORKFLOW_BUNDLES_URL}/v1/categories")
    bundles = sum(c.get("count", 0) for c in categories) if isinstance(categories, list) else None

    running = queued = failed = None
    if authorization:
        runs = await _get_json(client, f"{TES_URL}/api/runs", headers={"Authorization": authorization})
        if isinstance(runs, list):
            running = sum(1 for r in runs if r.get("state") == "RUNNING")
            queued = sum(1 for r in runs if r.get("state") == "QUEUED")
            failed = sum(1 for r in runs if r.get("state") == "FAILED")

    return {"workflow_bundles": bundles, "running_jobs": running, "queued_jobs": queued, "failed_jobs": failed}


def _infra_and_ops_section() -> tuple[dict, dict]:
    containers = get_containers_status()
    try:
        settings = load_settings()
        service_results = run_all_checks(settings)
        disk_results = run_disk_checks(settings)
    except FileNotFoundError:
        service_results, disk_results = [], []

    services_total = len(service_results)
    services_healthy = sum(1 for s in service_results if s.get("status") == "UP")
    overall = "UP"
    for r in service_results + disk_results:
        if r.get("status") == "DOWN":
            overall = "DOWN"
            break
        if r.get("status") == "WARN" and overall != "DOWN":
            overall = "WARN"

    gpu = get_gpu_status()
    gpu_utilization = gpu.get("utilization_pct") if gpu.get("reachable") else None

    workspace = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
    storage = _compute_storage(workspace)

    try:
        issues_path = Path(os.environ.get("WORKSPACE_ROOT", "/workspace")) / KNOWN_ISSUES_PATH_DEFAULT
        issues = list_known_issues(issues_path)
        alerts = sum(1 for i in issues if i.get("status") in ("open", "acknowledged"))
    except Exception:
        alerts = None

    infrastructure = {
        "containers_running": containers.get("running"),
        "containers_stopped": containers.get("stopped"),
        "services_healthy": services_healthy,
        "services_total": services_total,
        "gpu_utilization_pct": gpu_utilization,
        "storage_used_bytes": storage["disk"]["used"],
        "storage_total_bytes": storage["disk"]["total"],
        # No host-level CPU/memory metric exists anywhere in this backend
        # today (grep confirms no psutil/cpu_percent usage) -- GPU memory
        # (above) is a different thing and not substituted here.
        "cpu_pct": None,
        "memory_pct": None,
    }
    operations = {
        "health": overall,
        "alerts": alerts,
        "active_services": services_healthy,
        # No uptime tracking exists anywhere in this backend.
        "uptime": None,
    }
    return infrastructure, operations


@router.get("/dashboard/summary")
async def dashboard_summary(authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    async with httpx.AsyncClient() as client:
        identity, ai_platform, knowledge, workflow, business = await asyncio.gather(
            _identity_section(client, authorization),
            _ai_platform_section(client),
            _knowledge_section(client),
            _workflow_section(client, authorization),
            _business_section(client, authorization),
        )

    if _has_permission(authorization, "platform.manage_infra"):
        infrastructure, operations = await asyncio.to_thread(_infra_and_ops_section)
    else:
        infrastructure = {k: None for k in (
            "containers_running", "containers_stopped", "services_healthy", "services_total",
            "gpu_utilization_pct", "storage_used_bytes", "storage_total_bytes", "cpu_pct", "memory_pct",
        )}
        operations = {"health": None, "alerts": None, "active_services": None, "uptime": None}

    return JSONResponse({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "ai_platform": ai_platform,
        "knowledge": knowledge,
        "workflow": workflow,
        "infrastructure": infrastructure,
        "operations": operations,
        "business": business,
    })
