# PR11.5.6 — Enterprise Admin Console Security UI: Discovery

**Status: discovery only, written before any code changed, per this
PR's own instruction.** Every claim below was verified directly against
source in this session (both repos) — file paths and line numbers are
given throughout so each claim is independently re-checkable. This
builds on `docs/pr11-security-foundation-discovery.md` (PR11.5, this
repo) and `omnibioai-auth`'s `docs/pr11-mfa-org-policy-discovery.md`
(PR11.5.5) — neither is re-litigated here except where this session's
direct re-read found the task brief's own assumption didn't match
current source (§1).

---

## 1. Where the Security page belongs — the task brief's assumption doesn't match current source

The task brief says: *"Enable existing reserved navigation item:
Current: `Security` / `Coming Soon`. Change to: `Security` /
`functional=true`."* This describes the `sessions` nav item shape
(reserved, `functional: false`, one leaf) — but **there is no such
single reserved leaf item named `Security`.**

Re-read `frontend/cc-ui/src/navigation.ts` in full this session.
`'security'` is already the **section key** (`navigation.ts:101-103`),
not a leaf item — a `NavSection` containing four items today:

| Item key | Label | `functional` | Gate |
|---|---|---|---|
| `iam` | IAM / SSO Management | `true` (PR11.3) | `hasOrganizationsAccess` |
| `audit-logs` | Audit Logs | `true` (PR11.4b) | `hasPlatformAdminAccess` |
| `sessions` | Sessions | `false` — genuinely reserved, unclaimed | *(none)* |
| `api-keys` | API Keys / Service Accounts | `true` (PR11.4) | `hasOrganizationsAccess` |

This matches PR11.5's own discovery finding (§4.1 of
`docs/pr11-security-foundation-discovery.md`, written before MFA
existed): *"There is currently no dedicated 'Security' or 'MFA' nav
entry at all — one would need to be added (not yet reserved, unlike
`sessions`)."* Re-confirmed directly, not assumed — that finding still
holds.

**Decision: add two new leaf items to the existing `security` section**,
not repurpose `sessions` (that slot is for a future session-list/revoke
feature — §1.8 of the PR11.5 discovery doc — and has nothing to do with
MFA; claiming it for this PR would misuse a reservation meant for
different, still-unbuilt work):

```ts
{ key: 'security-overview', label: 'Security Overview', functional: true, visible: hasPlatformAdminAccess },
{ key: 'mfa-policy',        label: 'MFA Policy',        functional: true, visible: hasOrganizationsAccess },
```

Placed first in the section (before `iam`), since a dashboard overview
is the natural entry point into the section, matching how `overview` is
the first item in the top-level nav.

**Why two different gates, not one for the whole section**: the
Security Dashboard aggregates data across every organization (users,
orgs, MFA adoption) — the same shape as `audit-logs`
(`GET /platform/audit-events`, `manage_all_orgs`-gated), so it reuses
`hasPlatformAdminAccess` for the identical reason `audit-logs` does
(navigation.ts:118-130's own comment). MFA Policy management is
per-organization (`GET/POST/PATCH /orgs/{org_id}/mfa-policy`,
`manage_sso`-gated, org-scoped) — the same shape as `iam`/`api-keys`, so
it reuses `hasOrganizationsAccess` for the identical reason those two
do. **No new permission is created anywhere in this decision** — both
gates are existing functions from `auth.ts`, reused verbatim, exactly
as the task requires.

User MFA management (extending `UserDetailPage.tsx`) and Audit
Integration (extending `audit.ts`'s `KNOWN_EVENT_TYPES`, read by the
existing `AuditLogsPage.tsx`) need **no new nav entry at all** — they
extend pages already reached through `users`/`audit-logs`.

---

## 2. Existing Admin Console routing (`AdminApp.tsx`)

Read `frontend/cc-ui/src/apps/AdminApp.tsx` in full. Confirmed pattern,
used identically by `iam` and `api-keys` today (`AdminApp.tsx:360-395`):
a nav destination whose resource is per-organization is a **picker →
detail** flow, reusing `OrganizationsPage` as the picker (no second
org-list component built) — `selected<X>OrgId` state,
`ssoOrgIdFromPath`-style deep-link parsing (`/iam/{orgId}`), a
`popstate` handler branch, and a `handleNavigate` reset clause. `iam`
is the closer template for `mfa-policy` than `api-keys` (both are a
single settings page per org, not a tabbed resource list).

`audit-logs` (`AdminApp.tsx:347-349`) is the template for
`security-overview`: **flat**, no picker, no deep-link — `canSeeAuditLogs`
computed once (`hasPlatformAdminAccess()`) and the page rendered
directly.

**This PR's routing additions**, following both templates exactly:

- `security-overview`: flat, `canSeeSecurityOverview = hasPlatformAdminAccess()`,
  renders `<SecurityDashboardPage />` directly — no picker, no deep-link,
  same shape as `audit-logs`.
- `mfa-policy`: picker → detail, `selectedMfaPolicyOrgId` state,
  `mfaPolicyOrgIdFromPath()` (`/security/mfa-policy/{orgId}`, mirroring
  `/iam/{orgId}`'s own shape), a `popstate` branch, a `handleNavigate`
  reset clause, rendered as
  `selectedMfaPolicyOrgId != null ? <OrganizationMFAPolicyPage .../> : <OrganizationsPage onSelect={...} />`.

No changes to `users`/`organizations`/`audit-logs`/`iam`/`api-keys`
routing branches themselves.

---

## 3. Existing IAM pages — read in full this session

- `pages/identity/SSOSettingsPage.tsx` (589 lines) — **the direct
  structural template for `OrganizationMFAPolicyPage.tsx`**: org-label
  resolution (`useOrgLabel`, tries `fetchPlatformOrgDetail` then falls
  back to `fetchMyOrg`, never blocks the page on failure), a
  loading/denied(403)/not-configured(404)/error(other) state machine
  driven by parsing the thrown `Error`'s trailing status code (the
  `sso.ts`/`security.ts` convention — see §5), a "current config" card,
  a mutation card with inline confirm-before-destructive-toggle, and a
  permission-gated (`hasPermission(...)`) break-glass card with a
  required-reason input and its own confirm step. `OrganizationMFAPolicyPage`
  reuses every one of these shapes almost verbatim — the two config
  objects (`OrgSSOConfig` vs. the new `OrgMFAPolicy`) differ in fields,
  not structure.
- `pages/identity/ServiceAccountsPage.tsx` — confirms there is **no
  shared `Modal` component**; every page that needs one defines its own
  local `function Modal(...)` (`ServiceAccountsPage.tsx:32`). This PR's
  pages follow the same local-Modal convention rather than introducing
  a new shared primitive the task didn't ask for.
- `pages/identity/TeamsPage.tsx`/`RolesPage.tsx` — confirms the
  `initialOrgId` hint pattern (`AdminApp.tsx`'s `teamsOrgHint`) exists
  for cross-page navigation, not otherwise reused by this PR (no other
  page links into MFA Policy management yet).
- `pages/audit/AuditLogsPage.tsx` (full read) — confirmed
  `KNOWN_EVENT_TYPES` (from `audit.ts`) is the **only** thing that
  drives the event-type filter `<select>` (`AuditLogsPage.tsx:184`);
  extending that one array is sufficient for "Audit Integration," no
  page edit required (§7).

---

## 4. Existing UI primitives — confirmed present, no new primitive needed

`components/ui/index.ts` exports exactly: `PageContainer`,
`SectionHeader`, `Card`, `StatCard`, `DataTable`, `Button`, `EmptyState`,
`ComingSoon`, `LoadingState`, `ErrorState`, `ActionToolbar`. All eight
primitives the task names (`AppShell`, `Card`, `SectionHeader`,
`DataTable`, `LoadingState`, `ErrorState`, `EmptyState`, `Modal`) exist
**except** `Modal` — confirmed not a shared component (§3); this PR's
Modals follow the existing per-page-local convention instead of adding
one. `Confirmation dialogs` are not a component either — every existing
page (SSO enforcement, break-glass override, `UserStatusAction.tsx`)
implements confirm-then-act as local `confirming` state + a two-button
row, not a shared primitive. This PR's own confirmation flows (enable
MFA requirement, break-glass override, admin MFA reset) follow that
same local-state convention, not a new one.

`StatCard` (`components/ui/StatCard.tsx`) is the exact primitive for
the Dashboard's MFA Adoption/Organization Policy tiles — `label`,
`value`, optional `icon`/`accent`, and a `placeholder` flag for
not-yet-real data (this PR needs `placeholder` on **none** of its tiles
— every number is a real, current aggregate, see §6).

---

## 5. Existing API client patterns

Read `audit.ts`, `sso.ts`, `organizations.ts`, `users.ts`, `roles.ts`,
`serviceAccounts.ts`, `api.ts` in full. Every one of these files
independently redefines an identical `apiFetch` wrapper (`authHeaders()`
+ 401 → `reportUnauthorized()`) rather than sharing one from `api.ts` —
confirmed a deliberate, repeated convention (each file's own comment
says "mirroring `X.ts`'s own shape"), not an oversight; `security.ts`
follows the same convention rather than introducing a shared import
that no existing sibling file uses.

`sso.ts`'s `_errorMessage(r, path)` helper (prefers the backend's own
`detail`/`error` JSON field over a bare `"<path> <status>"` fallback) is
the exact shape needed for `omnibioai-auth`'s MFA policy error bodies —
`create_org_mfa_policy`'s `409` (`HTTPException(409, str(e))`, `detail`
is a plain string) and the override endpoints' validation errors both
match the `typeof data?.detail === 'string'` branch already there.
`security.ts` copies this helper rather than importing it from `sso.ts`
(no existing api-client file imports another's private helper; each
stays self-contained, same convention as the duplicated `apiFetch`
above).

`organizations.ts`'s `PlatformOrgSummary.sso_enabled: boolean` field
(computed server-side via `_org_ids_with_sso`, `platform_admin_service.py:65-73`)
is the direct precedent for the new `mfa_policy_required` field this PR
adds the same way (§6).

---

## 6. Missing backend capabilities — identified, and why each is in scope

The task allows exactly one category of backend change: *"No backend
changes expected unless discovery identifies a missing read-only
endpoint."* Three gaps were found, all read-only, all additive fields
on **existing** response shapes (no new endpoint, no new table, no new
migration in `omnibioai-auth`):

### 6.1 `PlatformUserDetailOut` has no MFA fields (`omnibioai-auth`)

`GET /platform/users/{user_id}` (`app/schemas/user_admin.py:47-59`,
already the exact endpoint `UserDetailPage.tsx` calls) returns nothing
about MFA today. But `User` (`app/db/models.py:85-89`, PR11.5.1) already
carries `mfa_enabled`, `mfa_status`, `mfa_primary_method`,
`mfa_enabled_at`, `mfa_last_verified_at` — live columns, not a
derivation. **Fix: add these five fields to `PlatformUserDetailOut`**,
same pattern PR11.1 already used to add `last_login_at`/
`authentication_method` to this identical schema.

Device list (label, `device_type`, `created_at`/"Added",
`last_used_at`/"Last Used") and recovery-code remaining count are *not*
on `User` — they're `MFADevice`/`MFARecoveryCode` rows
(`app/db/models.py:437-486`). **Fix: add `mfa_devices: list[MFADeviceSummary]`
and `mfa_recovery_codes_remaining: int` to the same schema**, computed
in `get_platform_user`'s existing service call
(`user_admin_service.get_user_detail`) with two small, already-scoped
(`user_id`-filtered) queries — no N+1 risk (single user, not a list
endpoint). Device summary reuses `MFADeviceOut`'s existing field
selection (`device_type`, `label`, `created_at`, `verified_at`,
`last_used_at`) *minus* `id`/`encrypted_secret`-adjacent anything — this
schema is platform-admin read-only, never returns a device id that
could be handed to a self-service `DELETE /users/me/mfa/devices/{id}`
call for a *different* user's device.

**This is a read-only field addition to an existing endpoint, not a new
endpoint** — squarely inside the task's allowance.

### 6.2 `PlatformOrgSummary` has no MFA-policy field (`omnibioai-auth`)

`GET /platform/orgs` (`app/schemas/platform_admin.py:6-19`) has
`sso_enabled: bool` (computed via `_org_ids_with_sso`) but nothing
about MFA policy — needed for the Dashboard's "Organizations requiring
MFA / without MFA policy" tiles (§7). **Fix: add
`mfa_policy_required: bool`**, computed with a new
`_org_ids_requiring_mfa(db, org_ids)` helper
(`platform_admin_service.py`), copying `_org_ids_with_sso`'s exact
shape (`.filter(OrganizationMFAPolicy.organization_id.in_(org_ids), OrganizationMFAPolicy.required == True)`) —
same one-query-per-page-of-org-ids performance discipline this file's
own module docstring requires (`platform_admin_service.py:10-17`).

### 6.3 Two new control-center backend **proxy** routes (`omnibioai-control-center`, not `omnibioai-auth`)

Distinct from §6.1/§6.2: this is not an `omnibioai-auth` change at all,
it's `omnibioai-control-center`'s own `backend/src/control_center/`
pure-relay layer, the thing that makes any of PR11.5.5's already-shipped
endpoints reachable from this app's frontend in the first place (the
frontend never calls `omnibioai-auth` directly — confirmed by every
`*.ts` client file's own comment, §5). Read all eight existing
`routes_*_proxy.py` files; each is zero-authorization-decision pure
relay (`_proxy(method, path, request)`, forwards the `Authorization`
header, never inspects the body for a permission check) — **adding one
is explicitly not "IAM logic," it's wiring**, the same category the
task's own objective ("without duplicating IAM logic") is drawing the
line around, not against.

Confirmed missing by direct read of both existing proxy files:

- **`routes_org_mfa_proxy.py`** (new file) — `/orgs/{org_id}/mfa-policy`
  (GET/POST/PATCH) and `/orgs/{org_id}/mfa-policy/override`
  (POST/DELETE) have **no proxy at all** today. Copies
  `routes_org_sso_proxy.py` (`backend/src/control_center/api/`) line for
  line, changing only the path segment and this PR's own docstring
  reference — same `_proxy` helper shape, same 204-empty-body handling,
  same `httpx.RequestError` → 503 handling.
- **`routes_user_proxy.py`** (existing file, one route added) —
  `POST /platform/users/{user_id}/mfa/reset` (PR11.5.4, already live in
  `omnibioai-auth`) has no proxy route in the existing file, which only
  has `GET /platform/users`, `GET /platform/users/{user_id}`,
  `PATCH /platform/users/{user_id}`. One `@router.post(...)` added,
  identical shape to the other three.

Both need registering in `backend/src/control_center/main.py`
(`routes_org_mfa_proxy` as a new import + `app.include_router(...)`
line, next to `org_sso_proxy_router`; `routes_user_proxy`'s existing
import/router already covers the new route with zero registration
change).

**Test coverage**: every existing proxy file has a mirrored
`backend/tests/test_routes_<x>_proxy.py` (confirmed: 8 proxy files, 8
test files, 1:1). This PR adds `test_routes_org_mfa_proxy.py` (mirrors
`test_routes_org_sso_proxy.py`'s exact test shape/mocking convention)
and extends `test_routes_user_proxy.py` with the new route's tests —
not in the task's own literal file list, but required by this repo's
own established "every proxy gets a test file" convention, the same
reasoning PR11.5.5's `omnibioai-auth` session applied to
`tests/test_route_authorization_coverage.py`.

---

## 7. Security Dashboard — data sourcing, no new aggregation endpoint

Task instruction: *"Use existing: Audit API, Users API, Organizations
API. Do not create backend aggregation unless required."*

- **MFA Adoption** (Total/Enabled/Disabled/Enrollment %): sourced from
  `GET /platform/users`, paginated (`page_size` capped at 100,
  `routes_platform_users.py:31`). With `mfa_enabled` added to
  `PlatformUserSummary` (the list-view schema, same minimal addition as
  §6.1) the dashboard walks every page (bounded by `total_pages`,
  computed from the first response) and counts client-side. **Known
  scaling limit, flagged not solved**: for a platform with many
  thousands of users this becomes many sequential requests; a real
  aggregation endpoint (`SELECT COUNT(*), SUM(mfa_enabled)`) would be
  the correct fix past that point. Not built here because (a) the task
  explicitly says not to add backend aggregation unless required, and
  (b) this platform's actual current scale (confirmed by every
  `page_size<=100`-capped list this session has read across both repos)
  doesn't require it today. A future PR should revisit this the same
  way PR11.5's own §8 flagged the MFA-policy bootstrapping gap: named,
  not silently absorbed.
- **Organization Policies** (requiring MFA / without a policy):
  sourced from `GET /platform/orgs`, same pagination-walk, using the
  new `mfa_policy_required` field (§6.2). Same scaling caveat as above,
  same reasoning for not solving it here.
- **Recent Security Events**: `GET /platform/audit-events` filtered to
  MFA event types client-side (already paginated, already the
  `AuditLogsPage.tsx`-proven pattern) — `fetchAuditEvents({ pageSize: 10 })`
  and filter the returned page to `event_type` values in the MFA set
  (§9), no new query parameter needed since the backend already accepts
  `event_type` as a single value, not a list — a small in-page filter
  (fetch a modestly larger page, e.g. 50, and take the first 10 MFA-typed
  rows) is simpler than 10 separate single-event-type requests and
  avoids the "list API accepts only one `event_type` value" constraint
  entirely).

No backend aggregation endpoint is added anywhere in this PR.

---

## 8. Permission model — final decision, no new permission created anywhere

| Surface | Gate (frontend `visible`) | Gate (backend, pre-existing, unmodified) |
|---|---|---|
| `security-overview` nav item / SecurityDashboardPage | `hasPlatformAdminAccess()` | Same as `audit-logs`/`/platform/users`/`/platform/orgs` — all `manage_all_orgs` |
| `mfa-policy` nav item / OrganizationMFAPolicyPage — view + enable/disable policy | `hasOrganizationsAccess()` | `require_org_permission_or_platform_admin(MANAGE_SSO)` (`omnibioai-auth`, PR11.5.5, unmodified) |
| OrganizationMFAPolicyPage — break-glass override card | `hasPermission('manage_all_orgs')` (same pattern `SSOSettingsPage.tsx`'s `canOverride` uses for `override_sso_enforcement`) | `require_permission(MANAGE_ALL_ORGS)` (PR11.5.5, unmodified) |
| UserDetailPage — Reset MFA button | Page is already platform-admin-only (`UserDetailPage.tsx:69-70`'s own comment) | `require_permission(MANAGE_ALL_ORGS)` (`routes_platform_users.py`, PR11.5.4, unmodified) |

Zero new permissions in either repo. Every gate above is an existing
function (`hasPlatformAdminAccess`/`hasOrganizationsAccess`/
`hasPermission`) or an existing backend dependency, reused verbatim —
consistent with every PR11.x page before this one.

---

## 9. Audit Integration — the verified event-type list

Read `omnibioai-auth`'s `app/services/audit_service.py`'s
`AuditEventType` class directly (not the task brief's paraphrase, which
uses slightly different names in two places — `MFA_RECOVERY_USED` vs.
the actual `mfa_recovery_code_used`). The real, current, full MFA event
list to add to `audit.ts`'s `KNOWN_EVENT_TYPES`:

```
mfa_device_enrollment_started, mfa_device_added, mfa_device_removed,
mfa_enabled, mfa_disabled,
mfa_challenge_required, mfa_verified, mfa_verification_failed,
mfa_recovery_codes_generated, mfa_recovery_codes_regenerated,
mfa_recovery_code_used, mfa_reset_by_admin,
mfa_policy_enabled, mfa_policy_disabled,
mfa_policy_override_created, mfa_policy_override_removed
```

16 event types, not the 10 the task brief lists — the brief's own list
(`MFA_ENABLED`, `MFA_DISABLED`, `MFA_DEVICE_ADDED`, `MFA_DEVICE_REMOVED`,
`MFA_POLICY_ENABLED`, `MFA_POLICY_DISABLED`,
`MFA_POLICY_OVERRIDE_CREATED`, `MFA_POLICY_OVERRIDE_REMOVED`,
`MFA_RECOVERY_USED`, `MFA_RESET_BY_ADMIN`) is a reasonable *subset* for
day-to-day filtering relevance, not the full backend registry. Adding
all 16 (not just the brief's 10) means the filter dropdown never has a
real, emitted event type it can't select — the same completeness
`KNOWN_EVENT_TYPES`'s own existing entries already have for every other
PR11.x event type. The Dashboard's "Recent Security Events" tile (§7)
uses the same full 16-value set to decide which audit rows are
"security events" worth surfacing there.

No new label overrides (`EVENT_TYPE_LABEL_OVERRIDES`)/descriptions
(`EVENT_TYPE_DESCRIPTIONS`) are added — `formatEventType`'s existing
generic word-splitting already produces readable output ("Mfa Policy
Enabled" → capitalized per-word) for all 16 without a special case, the
same as the majority of pre-existing entries in that list.

---

## 10. Verification method

- Full reads: `navigation.ts`, `AdminApp.tsx`, `SSOSettingsPage.tsx`,
  `SSOSettingsPage.test.tsx`, `ServiceAccountsPage.tsx`,
  `AuditLogsPage.tsx`, `UserDetailPage.tsx`, `UserStatusAction.tsx`,
  `auth.ts`, `audit.ts`, `sso.ts`, `organizations.ts`, `users.ts`,
  `api.ts`, `components/ui/index.ts`, `components/ui/StatCard.tsx`.
- Full reads (`omnibioai-auth`): `app/api/routes_platform_users.py`,
  `app/schemas/user_admin.py`, `app/db/models.py` (`User`, `MFADevice`,
  `MFARecoveryCode`, `OrganizationMFAPolicy`), `app/services/
  platform_admin_service.py`, `app/schemas/platform_admin.py`,
  `app/services/audit_service.py`'s `AuditEventType`.
- Full reads (`omnibioai-control-center` backend): all 8
  `routes_*_proxy.py` files, `main.py`'s router registration block,
  `test_routes_org_sso_proxy.py`, `test_routes_user_proxy.py`,
  `test_main.py` (confirmed no global route-count assertion needs
  updating there).
- Grepped for an existing `Modal`/`ConfirmDialog` shared component
  (none found — confirmed via `grep -rl "Modal\|ConfirmDialog"`, three
  hits, all page-local definitions).
- Re-read `docs/pr11-security-foundation-discovery.md` (this repo) and
  `omnibioai-auth`'s `docs/pr11-mfa-org-policy-discovery.md` in full for
  continuity — no claim in either is treated as still-current without
  re-verifying against today's source in this pass.

No code was changed, no migration was written, and no endpoint was
added in the course of this discovery, per this PR's own instructions.
