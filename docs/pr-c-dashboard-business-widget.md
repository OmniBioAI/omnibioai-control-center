# PR C — Fix Stale Dashboard Business Widget

Status: implemented.

## What was stale

`routes_dashboard.py`'s `GET /dashboard/summary` (PR10, "Live Platform
Dashboard") hardcoded:

```python
# Business: no billing/subscription/credits system exists anywhere in
# this workspace (confirmed absent, not merely unauthenticated) --
# always placeholders, same as Phase 2's dashboard already showed for
# Billing/Audit.
business = {"organizations": None, "subscription": None, "billing": None, "credits": None}
```

True when PR10 shipped. False since PR14.4–14.7 and PR B built and
proxied exactly that system. The module's own top-level docstring also
never mentioned a Business section at all — a second, separate staleness
(an omission, not just a wrong claim), fixed alongside the code.

## Audit before coding

- **`routes_dashboard.py`**: confirmed the hardcode above by reading the
  file directly, not from memory of the earlier capability-parity audit.
- **`routes_billing_proxy.py`**: confirmed which billing endpoints exist
  and how they authenticate (independent JWT verification per request,
  same as every other proxy — see PR B's own audit doc for the full
  endpoint inventory).
- **Frontend `DashboardPage.tsx`**: confirmed the Business grid renders
  4 `MetricCard`s, all `placeholder` (permanently flagged "Preview
  data"), reading `business.organizations/subscription/billing/credits`
  — all four always `null`.

## Why this isn't "just wire it up"

`omnibioai-billing`'s reporting API is **entirely organization-scoped**
— confirmed again here, same finding as PR B's audit. There is no
platform-wide billing aggregate endpoint, so this section cannot show a
platform total the way Identity/AI Platform/Knowledge/Workflow do.

**Resolution**: show the *caller's own* organization's billing instead.
This reuses the exact "my org" resolution `BillingPage.tsx`'s own
`useOrgLabel()` already does client-side (`fetchMyOrg`/`fetchMyOrgs` →
`GET /orgs`, IAM's membership-scoped listing — not `/platform/orgs`,
which is platform-admin-only) — just resolved server-side here instead.
A platform admin with no personal org membership still sees
null/"Preview data", exactly like every other section's own "never
fabricate" convention already establishes. This is not a "compute a
fake platform total" shortcut.

## Backend changes

`routes_dashboard.py`:
- Added `BILLING_URL` env var (same convention as every other upstream
  URL in this file).
- Added `_business_section(client, authorization)`: resolves the
  caller's own org via `IAM_URL/orgs`, then calls
  `BILLING_URL/billing/organizations/{id}/subscription` and
  `BILLING_URL/billing/organizations/{id}/usage` (the same two proxy
  routes `routes_billing_proxy.py`/PR B already expose) with the
  caller's forwarded token — same "no authorization decision made here"
  posture every other section in this file already has.
- `billing_service_available` is computed explicitly (connection
  exception → `False`, any response → `True`) rather than reusing the
  generic `_get_json()` helper, which collapses *every* failure mode
  (unreachable, 404, malformed) to `None` — that would have made "the
  billing service is down" indistinguishable from "this org just has no
  subscription yet" (a normal 404), misrepresenting an outage as a
  routine empty state.
- `dashboard_summary()`: `business` is now the 5th member of the
  existing `asyncio.gather(...)` alongside identity/ai_platform/
  knowledge/workflow, not a hardcoded dict assigned after the gather.
- Module docstring: added a paragraph for Business's auth model,
  matching the existing per-section paragraphs for Identity/AI
  Platform/Knowledge/Infrastructure (previously the docstring didn't
  mention Business at all).

**Not changed**: `_workflow_section()`'s own call to workflow-bundles'
`GET /v1/categories` sends no `Authorization` header, on the same
"unauthenticated upstream" assumption PR A3 found to be stale (that
service is actually `workflow.read`-permission-gated now). Flagged again
here for visibility — still out of scope for this PR, which is
Business/billing only, not Workflow.

## Frontend changes

`dashboard.ts`: `BusinessSummary` replaced field-for-field to match
`_business_section()`'s real response shape
(`organization_id`/`organization_name`/`plan_name`/
`subscription_status`/`usage_services_count`/`billing_service_available`).
`organizations` was **not** carried forward — it would have duplicated
`identity.organizations` (already live, platform-wide, right above this
section). `credits` was **not** carried forward either — no such concept
exists anywhere in `omnibioai-billing`'s schema, live or otherwise;
keeping it would have meant inventing a field with no backing API,
exactly what this PR's own rules forbid.

`DashboardPage.tsx`: the Business grid is now 4 cards, none `placeholder`
(this section has a real live source now, same status every other
non-structural field in this page already has):
- **Plan** (`MetricCard`) — `plan_name`, "—" when null.
- **Subscription** (`StatusCard`) — `subscription_status`, tone-colored
  (green for active/trial, red for suspended/cancelled, neutral
  otherwise), "Unknown" when null.
- **Usage (services)** (`MetricCard`) — `usage_services_count`, "—" when
  null.
- **Billing Service** (`StatusCard`) — "Available"/"Unavailable"/"Unknown",
  tone-colored — the one field that's explicitly about service health,
  not billing content, per this PR's own suggested field list.

**Not shown, because nothing in `omnibioai-billing` computes them**:
revenue, MRR, ARR, customer/financial analytics of any kind.

## Testing

**Backend** (`test_routes_dashboard.py`, `TestBusinessSection`, 6 new
tests): populates plan/subscription/usage for the caller's own org;
never fabricates when `Authorization` is missing; returns all-null when
the caller has no organization membership; distinguishes a 404
(no-subscription) from the billing service being unreachable
(`billing_service_available` `True` vs `False`); and a
partial-failure case where the usage call fails independently without
blocking subscription data — matching the same
"one section degrades without failing the request" convention every
other section's tests already establish.

**Frontend** (`DashboardPage.test.tsx`, 4 new/rewritten tests): normal
rendering (real plan/status/service values appear), the empty state
(no org membership → "—"/"Unknown", never fabricated), the
unavailable-billing-service state (explicit "Unavailable", distinct from
a plain empty state), and the whole-page-fetch-failure case (Business
heading still renders, values degrade to "Unknown" without throwing).
The pre-existing "Preview data" count test was updated to assert Business
cards **no longer** carry that tag — the opposite of what it asserted
before this PR, which is the point of the fix.

## Verified

- `pytest`: 879 passed, 99.79% coverage (≥98% required).
- `ruff check`: 12 pre-existing baseline errors on the two touched files
  → 13 after (the +1 is the new function's `Optional[str]` parameter,
  matching the exact convention every neighboring function in this file
  already uses — confirmed via `git stash` diff, not new debt).
- `npm test`: 343 passed / 29 files.
- `npm run build:admin` / `build:control`: both succeed;
  `dist-control`'s output hash is **byte-identical** to PR B's build —
  `DashboardPage.tsx` isn't imported by `ControlApp.tsx` at all (it has
  no Overview tab), so this change cannot reach that bundle by
  construction, not just by absence of a matching string.
- No `omnibioai-billing` changes. No unrelated files.
