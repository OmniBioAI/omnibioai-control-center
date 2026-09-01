# PR A4 — Admin Console RAG / PubMed Page

Status: implemented. Backend proxy + frontend page + tests, read-only.

> **Security fix (post-PR-A4 audit):** this doc originally asserted
> "Admin Console visibility is controlled by control-center admin
> authorization" without that control actually existing —
> `routes_rag_proxy.py` had no `Depends(require_permission(...))` on any
> route and no router-inclusion-level dependency in `main.py` either
> (unlike `services_router`/`docker_router`/`config_router`, all gated
> there behind `platform.manage_infra`). Because `/v1/studies` and
> `/v1/cache/stats` authenticate via the `RAGBIO_API_KEY` service
> credential rather than the caller's own token, there was also no
> upstream per-caller check to fall back on the way
> `routes_org_proxy.py`/`routes_workflow_bundles_proxy.py` get "for free"
> by forwarding the caller's `Authorization` header. Net effect,
> confirmed live: a request to `/rag/studies` with **no** `Authorization`
> header at all got a `200` with real data back — `hasAdminAccess()` in
> `navigation.ts` is a client-side, locally-decoded-JWT check that never
> reaches the backend, so it was the *only* thing that looked like a
> gate, and calling the route directly bypassed it entirely.
>
> Fixed: `GET /rag/studies` and `GET /rag/cache-stats` now each require
> `Depends(require_permission("platform.manage_infra"))` directly on the
> route (not at router-inclusion time, since that would also gate
> `GET /rag/health`, which stays open — it's a liveness probe with no
> auth upstream either). `platform.manage_infra` is the same permission
> every other `hasAdminAccess()`-gated Infra/Operations page already
> requires server-side, and every account holding the `admin` role
> `hasAdminAccess()` checks is seeded with it
> (`omnibioai-auth/app/db/init_admin.py`), so the frontend nav gate and
> this backend gate now agree on the same audience — the claim below is
> true as of this fix, where it previously was not.



## What this PR does

Exposes `omnibioai-rag`'s existing knowledge-base and query-cache
status APIs inside Admin Console (`navigation.ts`'s `rag`/`pubmed` nav
items, previously `functional: false`), via a new proxy router
(`routes_rag_proxy.py`) and a new page (`RAGPage.tsx`) — same pattern as
PR A1–A3. No new backend service, no duplicated retrieval-pipeline
logic, no IAM redesign, no entitlement changes.

## Pre-implementation finding: RAG has two independent auth models

Verified directly against `omnibioai-rag/ragbio/api/server.py` +
`ragbio/api/iam.py` (not assumed from `routes_dashboard.py`'s existing
comments or the original capability audit):

| Endpoint | Auth mechanism |
|---|---|
| `GET /v1/studies`, `GET /v1/cache`, `GET /v1/cache/stats`, `POST /v1/ingest`, `POST /v1/embed`, `POST /v1/kg/build`, `GET /v1/benchmark` | `_verify` — bearer token must **literally equal** the `RAGBIO_API_KEY` env var. A static shared service secret, not per-user auth. |
| `POST /v1/query`, `GET /v1/kg/stats`, `GET /v1/kg/entity`, `GET /v1/kg/drug-disease` | `Depends(require_permission("dataset.read"))` — real per-user JWT, independently verified via the shared `iam_client` package. |
| `GET /health` | No auth. |

**RAG corpus metadata endpoints currently authenticate through the
RAGBIO_API_KEY service credential. Admin Console visibility is
controlled by control-center admin authorization. This PR does not
introduce per-user RAG authorization.**

This is a genuine architectural difference from PR A1 (TES) and PR A3
(Workflows), both of which forward the *admin's own* JWT and get a real,
independently-verified per-user authorization decision back. Here, for
`GET /v1/studies` and `GET /v1/cache/stats`, forwarding the admin's own
token would always fail (it will never equal `RAGBIO_API_KEY`) — so
`routes_rag_proxy.py` injects the service credential itself, server-side,
exactly matching the precedent `routes_dashboard.py`'s own
`_knowledge_section()` already set for this same upstream (`RAGBIO_API_KEY`
is described there as "a service-held secret ... not the caller's own
token," same category as `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` in
`routes_llm.py`). `GET /health` needs no credential of either kind.

Not hiding this distinction: `RAGPage.tsx` uses a dedicated
`ServiceCredentialState` component (not the `EmptyState`+`ShieldAlert`
"Permission denied" pattern A1–A3 use) whose copy explicitly says a
401/403 here "reflects control-center's RAGBIO_API_KEY configuration,
not your own admin permissions" — because it doesn't.

## Scope decision: Knowledge Graph endpoints deferred

`GET /v1/kg/stats`/`/v1/kg/entity`/`/v1/kg/drug-disease` are real,
per-user-authorized (`dataset.read`, independently verified) and would
follow the A1/A3 forward-the-caller's-JWT pattern properly — unlike
`/v1/studies`. Per explicit product direction, they are **not** included
in this PR: mixing a shared-secret-authenticated tab and a genuinely
per-user-authorized tab behind one page in one PR would blur which trust
model actually applies to which part of the UI. Tracked as a future,
separately-scoped PR: **"RAG Knowledge Graph Admin Integration"**, with
its own proper `dataset.read` JWT forwarding, not a service-key shortcut.

## What the three tabs actually show (real fields only)

- **Knowledge Base** — `GET /v1/studies` (`{studies: [{name, abstract_count}]}`), one row per indexed collection.
- **PubMed / Literature Index** — the same `GET /v1/studies` response, aggregated (collection count, summed `abstract_count`) client-side. RAG's only indexed corpus today is PubMed abstracts (`list_studies()` counts files under `ABSTRACT_FOLDER`, no other corpus type exists in this service) — this tab is an honest re-framing of the same real numbers, not a second data source.
- **Query Service Status** — `GET /health` (`status`, `version`, `faiss_version`, embedded cache summary) + `GET /v1/cache/stats` (fuller Redis cache breakdown: `enabled`, `connected`, `cached_queries`, `ttl_seconds`, `hits`, `misses`, `hit_rate`). These are the only two endpoints RAG exposes about its own operational state. **Not shown, because they don't exist anywhere in this service's API:** document counts beyond `abstract_count`, retrieval-accuracy/relevance metrics, query latency, embedding statistics, or model identity. `fetchCacheStats()` failing independently (e.g. `RAGBIO_API_KEY` unconfigured) degrades that one card to "not available," it does not hide the health data that succeeded.

## Testing

- `backend/tests/test_routes_rag_proxy.py` — success/auth-injection/unreachable/non-JSON/status-propagation for all three routes, plus two tests specifically asserting the auth-injection behavior above: the admin's own token is never sent to `/rag/studies`/`/rag/cache-stats` (the service key is, when configured), and `/rag/health` forwards whatever the caller sent (or nothing) without ever injecting the service key.
- `frontend/cc-ui/src/pages/operations/RAGPage.test.tsx` — loading, empty, real-data rendering, the `ServiceCredentialState` path (403), generic error + retry, tab switching (including the aggregated PubMed totals being the real sum of the fixture data, not a hardcoded number), and cache-stats failing independently of health.
