# PR B — Admin Console Billing / Usage Consolidation

Status: implemented.

## What this PR does

Removes two Coming Soon nav placeholders (`licenses`, `usage`) that, on
direct audit, turned out to duplicate capability that already exists —
and adds the one piece of real, previously-unproxied billing data that
was genuinely missing. No new billing APIs, no new subscription logic,
no new entitlement checks, no billing-service changes of any kind.

## Audit: current control-center billing implementation

Read directly, not assumed:

- **`BillingPage.tsx`** already has four tabs (Overview, Invoices,
  Subscription, Usage Limits) behind an org-picker, all reading from
  `routes_billing_proxy.py`. `SubscriptionPage.tsx` (PR14.6D) supplies
  the Subscription and Usage Limits tabs — `UsageLimitsTab` already
  shows per-resource consumption **relative to a plan's included
  allowance** (`included` / `used` / `remaining` / `percentage_used`).
- **`routes_billing_proxy.py`** proxied 7 of `omnibioai-billing`'s
  reporting endpoints before this PR: `summary`, `invoices`,
  `cost-breakdown`, `invoices/{id}`, `invoices/{id}/line-items`,
  `subscription`, `subscription/usage-limits`.
- **`navigation.ts`**: `billing` was `functional: true`; `licenses` and
  `usage` were `functional: false` (Coming Soon), with no page, no
  proxy route, no client function backing either.

## Audit: `omnibioai-billing` APIs directly

`app/routers/billing.py` (`prefix="/billing"`) exposes 12 GET routes,
not 7 — 5 more existed than were proxied:

| Endpoint | Proxied before this PR? | Schema |
|---|---|---|
| `/organizations/{id}/usage` | **No** | `UsageSummaryResponse` |
| `/organizations/{id}/costs` | No | `CostSummaryResponse` |
| `/organizations/{id}/allowances` | No | `AllowanceUsageResponse` |
| `/organizations/{id}/cost-history` | No | `CostHistoryResponse` |
| `/organizations/{id}/summary` | Yes | — |
| `/organizations/{id}/invoices` | Yes | — |
| `/organizations/{id}/cost-breakdown` | Yes | — |
| `/invoices/{id}`, `/invoices/{id}/line-items` | Yes | — |
| `/organizations/{id}/subscription`, `/subscription/usage-limits` | Yes | — |

`app/routers/entitlements.py` also exposes `GET /entitlements/{id}/check`
— **not touched by this PR**, per the explicit instruction that IAM
decides *who can access*, Billing decides *what a subscription
includes*, Usage decides *what was consumed*, and entitlement
enforcement is none of this PR's business.

Of the 4 previously-unproxied endpoints, reading `app/schemas/billing.py`
directly showed 3 of them duplicate data already exposed:

- **`/costs`** (`CostSummaryResponse`: `breakdown_by_service/action/resource`)
  duplicates **`/cost-breakdown`** (already proxied, drives
  `BillingPage.tsx`'s `CostBreakdownChart` via `group_by=service|action|resource|month`)
  — same breakdown, different endpoint shape.
- **`/allowances`** (`AllowanceUsageResponse.AllowanceUsageItem`:
  `service, action, resource, unit, period, included, used, remaining, percentage_used`)
  duplicates **`/subscription/usage-limits`** (already proxied, drives
  `UsageLimitsTab`) — `AllowanceUsageItem` and `SubscriptionUsageLimit`
  are **field-for-field identical schemas**.
- **`/cost-history`** (a cost time series by date) is answerable via
  `/cost-breakdown?group_by=month`, already proxied.
- **`/usage`** (`UsageSummaryResponse`: `services: [{service, action, resource, unit, quantity}]`)
  is genuinely new: **raw consumption**, no plan/limit context at all —
  distinct from `UsageLimitsTab`'s allowance-relative view. This is the
  one endpoint this PR adds a proxy route for.

## Changes

### Backend
- `routes_billing_proxy.py`: added `GET /billing/organizations/{id}/usage`
  → `omnibioai-billing`'s `GET /billing/organizations/{id}/usage`, same
  `_proxy()` helper every other route in this file already uses. No
  proxy added for `/costs`, `/allowances`, `/cost-history` — see audit
  above for why that would itself be duplicating an overlap that
  already exists inside `omnibioai-billing`, not this PR's to fix.
- `test_routes_billing_proxy.py`: 6 new tests for the `/usage` route
  (success, auth forwarding, path interpolation, 403, unreachable → 503,
  non-JSON), mirroring every existing test class in that file exactly.

### Frontend
- `billing.ts`: added `UsageDimensionSummary`/`OrganizationUsage` types
  (mirroring `UsageSummaryResponse`/`UsageDimensionSummary` field-for-
  field) and `fetchOrganizationUsage(orgId)`.
- `BillingPage.tsx`: added a 5th tab, **Usage** — raw consumption table
  (service / action / resource / consumed quantity), same
  loading/denied/error/empty state machine every other tab on this page
  already uses (`LoadState<T>`, `classify()`).
- `BillingPage.test.tsx`: 5 new tests for the Usage tab (loading, empty,
  rendering, 403-denied, error+retry).
- `navigation.ts`: removed the `licenses` and `usage` `NavItem` entries
  from the Business section (and their now-dead `PageKey` union
  members) — see the inline comment left at that removal for the full
  reasoning, summarized below.
- `SidebarNav.tsx`: removed the now-orphaned `licenses`/`usage` icon map
  entries (`FileText`/`BarChart3`) and their now-unused imports — the
  `ICONS` map is `Partial<Record<PageKey, IconComponent>>`, so this was
  required for `tsc -b` to pass once those two keys left `PageKey`, not
  optional cleanup.
- `AdminApp.test.tsx`: one pre-existing test (`renders Coming Soon for
  an unimplemented module`) used `Licenses` as its still-unimplemented
  example — updated to use `Settings` instead, which remains genuinely
  Coming Soon.

## The two consolidation decisions

**`usage`**: superseded. `BillingPage.tsx` already had a Usage Limits
tab (PR14.6D); this PR adds a plain Usage tab alongside it. A standalone
top-level nav destination for either would have duplicated a page that's
already one click away under Billing — consistent with the precedent
PR14.6D's own `SubscriptionPage.tsx` comment already set ("two more tabs
on this same page... not two new top-level nav entries").

**`licenses`**: not resurrected, migration documented. The only
"licenses" concept anywhere in this ecosystem is `omnibioai-auth`'s
legacy per-key desktop/Electron activation system
(`app/api/routes_license.py`, `LicenseValidateRequest.platform: web |
desktop | both`) — already a decommissioning target from the earlier
Phase 1 license-decommission work (verified against that file directly
in this session's earlier audit turn, not re-derived here). It is not
an organization-seat or subscription concept, and building an Admin
Console UI for it would mean resurrecting a superseded model, not
consolidating an existing one. **Organization-level plan/subscription
management is exactly what the `billing` nav entry's Subscription tab
already is** — that is the current model this ecosystem has moved to,
and where an admin should go for "what does this org's plan include."

## What was explicitly not done

- No new billing APIs, no new subscription logic, no new entitlement
  checks, no duplicate usage calculations (the one calculation this PR
  performs client-side — none — the Usage tab renders
  `UsageSummaryResponse.services` verbatim, no math).
- No entitlement enforcement introduced or touched — `entitlements.py`'s
  `GET /{id}/check` remains uncalled from anywhere in this app, exactly
  as before this PR.
- No changes to `omnibioai-billing` itself.
