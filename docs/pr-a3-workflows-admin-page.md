# PR A3 — Admin Console Workflows Page

Status: implemented. Backend proxy + frontend page + tests, read-only.

## What this PR does

Exposes `omnibioai-workflow-bundles`' existing catalog and run-history
APIs inside Admin Console (`navigation.ts`'s `workflows` nav item,
previously `functional: false`), via a new proxy router
(`routes_workflow_bundles_proxy.py`) and a new page (`WorkflowsPage.tsx`)
— same pattern as PR A1 (Tool Execution / omnibioai-tes) and PR A2 (AI
Models / omnibioai-model-registry). No new backend service, no
duplicated business logic, no new IAM permissions.

## Pre-implementation findings (verified against source, not assumed)

Two assumptions carried over from the original capability-parity audit
and from `routes_dashboard.py`'s own comments turned out to be wrong
once `omnibioai-workflow-bundles/api/server.py` and `api/iam.py` were
read directly:

### 1. workflow-bundles is authenticated, not open

Every route except `GET /health` is gated by
`Depends(require_permission(...))`:

| Permission | Routes |
|---|---|
| `workflow.read` | `GET /v1/workflows`, `GET /v1/workflows/{name}`, `GET /v1/categories`, `GET /v1/workflows/{id}/inputs` |
| `workflow.execute` | `GET /v1/runs`, `GET /v1/runs/{run_id}`, `POST /v1/workflows/{id}/run` |
| `workflow.manage` | `PATCH /v1/workflows/{id}/toggle` (write, out of scope) |
| `workflow.publish` | `POST /v1/register` (write, out of scope) |

Both permissions used by this PR (`workflow.read`, `workflow.execute`)
are pre-existing (workflow-bundles' own merged IAM integration) — this
PR adds none. `require_permission` raises `401` for a missing/invalid
token, `403` for a valid token missing the permission (`api/iam.py`).

**Side effect, not fixed by this PR:** `routes_dashboard.py`'s
`_workflow_section()` calls `GET /v1/categories` with no `Authorization`
header, on the stale assumption this service is unauthenticated. That
call is presumably already failing with a 403 in production today.
Flagging for whoever owns that file next — out of scope here, this PR
doesn't touch `routes_dashboard.py`.

### 2. `GET /v1/runs` has no organization-level filtering

Confirmed directly in `run_workflow()`'s own source comment:

> `"organization_id": identity.org_id,` — *Logging/audit context only
> -- not an access-control boundary (see this PR's report: org
> isolation for runs is deferred, tracked as a follow-up pending a
> multi-tenant data model migration).*

Unlike `omnibioai-tes`'s `GET /api/runs` (which filters to
`identity.organization_id` server-side), workflow-bundles' `list_runs()`
returns **every organization's runs** to any caller holding
`workflow.execute` — there is no filtering in that handler at all.
Runs are also in-memory only (`RUNS: Dict[str, Any] = {}`), not
persisted to a database — lost on service restart.

## How this PR handles the multi-tenancy gap

Per explicit product direction: **surface it, don't hide it, don't
fake a fix.**

- `routes_workflow_bundles_proxy.py` is a transparent relay for all six
  routes, `/runs` included — it does not filter, group, or reshape the
  upstream response by `organization_id`. Adding such filtering in
  control-center would itself be "duplicated/invented authorization
  logic" — exactly what this PR's own rules forbid, and it would create
  a boundary that doesn't actually exist server-side, which is worse
  than no boundary at all (a false sense of isolation).
- `test_routes_workflow_bundles_proxy.py::TestListRunsProxy::
  test_multi_organization_response_passes_through_unfiltered` asserts
  this directly: a two-organization upstream fixture comes back through
  the proxy with both organizations' `organization_id` values intact,
  same row count, unmodified.
- `WorkflowsPage.tsx`'s Runs tab renders a permanent notice above the
  table (present in the loading-denied/error/empty/ready states alike):

  > "Workflow run visibility is currently provided by the upstream
  > workflow service. The current workflow-bundles API does not yet
  > enforce organization-level filtering for run history. Organization
  > isolation for workflow runs is tracked as an upstream multi-tenant
  > improvement."

  Explicitly labeled in the surrounding copy as **not** an Admin Console
  bug and **not** an IAM bypass introduced by this PR — an existing
  upstream limitation, disclosed rather than concealed.
- `WorkflowsPage.test.tsx`'s Runs-tab tests assert: the notice renders
  in every state (ready/empty/denied), `organization_id` is rendered
  verbatim from the mocked upstream response for both organizations in
  the fixture, and nothing in the page's own code path filters by org.

## Follow-up (not this PR, tracked here for visibility)

- `routes_dashboard.py`'s unauthenticated call to workflow-bundles'
  `/v1/categories` should get a real `Authorization` header, or accept
  it'll keep 403ing.
- workflow-bundles itself needs a multi-tenant data model migration
  before `GET /v1/runs` can be made org-scoped — that's an upstream
  change, not a control-center one.
