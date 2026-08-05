# PR11.4b — Enterprise Identity Audit Trail Foundation: Discovery

Discovery pass performed before any implementation, per this PR's own
instructions. Everything below was verified directly against
`omnibioai-auth` and `omnibioai-control-center` source (both on `main`,
which now has PR11.1–PR11.4 all merged), not assumed.

## 1. Existing audit framework in `omnibioai-auth` (PR9, "Enterprise IAM
Foundation")

A real, working audit ledger already exists — this PR extends it, it
does not build a new one.

- **`app/services/audit_service.py`** — the single place every
  persistent audit event is written from. `log_event(db, event_type,
  actor_user_id=None, target_user_id=None, organization_id=None,
  resource_type=None, resource_id=None, before_state=None,
  after_state=None, metadata=None)`. Deliberately **never raises** — a
  failed audit write is logged (`logger.exception`) and rolled back,
  never allowed to break the real mutation it describes. Called from
  inside services, at the exact point each mutation happens — **never
  from a route handler** — so a mutation reachable from multiple
  routes still emits exactly one event.
- **`app/db/models.py::AuditEvent`** — `id, event_type (indexed),
  actor_user_id (indexed), target_user_id (indexed), organization_id
  (indexed), resource_type, resource_id, before_state (JSON),
  after_state (JSON), event_metadata (JSON, column name `metadata`),
  created_at (indexed)`. Deliberately **not** foreign keys with
  cascade behavior — a row must survive even if the referenced
  user/org is later deleted. This table is colocated in
  `omnibioai-auth`'s own database, deliberately separate from the
  unrelated `omnibioai-security-audit` service's Redis/consumer
  pipeline (a generic cross-service request/policy log with no
  actor/target/before-after columns — extending that would be a
  difference in kind, not degree).
- **`AuditEventType`** (class of string constants, not a real Python
  `Enum`) currently defines: `LOGIN_SUCCESS`, `LOGIN_FAILURE`,
  `ROLE_CREATED`, `ROLE_ASSIGNED`, `ROLE_REMOVED`,
  `PERMISSION_GRANTED` / `PERMISSION_REVOKED` (defined but never
  actually emitted by any call site today — confirmed by grep), and
  `ORG_MEMBERSHIP_CHANGED`.
- **Existing call sites** (confirmed by grep, all inside services):
  `auth_service.py` (login success/failure), `role_service.py` (role
  create/assign/remove — 4 call sites), `org_service.py` (org
  membership created via JIT-provisioning or invite, member roles
  set/added/removed — 5 call sites).
- **Not currently audited at all**: user status changes
  (`user_admin_service.set_user_status`), API key lifecycle
  (`apikey_service.py`), OAuth client lifecycle
  (`oauth_client_service.py`), SSO configuration/enforcement
  (`org_sso_service.py`) — confirmed by grep, zero references to
  `audit_service` in any of these four files. This is exactly this
  PR's scope: fill these four gaps, not touch the eight events already
  working.

## 2. Existing audit retrieval API

**None exists.** Confirmed by grep across `app/api/*.py` — no route
file references `AuditEvent` or queries the audit ledger. (The one
`audit` grep hit outside this scope, in
`routes_platform_permissions.py`, is docstring prose listing "audit
systems" as a *future* consumer of the permission registry — unrelated.)
Per the task's own fallback instruction, this PR adds a minimal
`GET /platform/audit-events` endpoint (see §5).

## 3. Existing test coverage to mirror

**`tests/test_audit_ledger.py`** (PR9) is a real, running integration
suite — hits actual routes via `client` (FastAPI `TestClient`) against
a real sqlite test DB, then asserts on `AuditEvent` rows read back
through a second, direct `sessionmaker` session (`_DirectSession`) via
a small `_events(**filters)` helper. This PR's new tests
(`tests/test_pr11_identity_audit.py`) follow this exact convention —
real HTTP calls through real service functions, not mocks — plus its
existing fixtures/helpers (`_register_and_login`, `_platform_admin`,
`_org`, `_auth_header`) are reused directly rather than re-implemented.

## 4. Exact call sites for the required events

All four target functions already exist, confirmed unmodified by
PR11.4:

| Event(s) | Function | File | Existing params to reuse |
|---|---|---|---|
| `USER_ENABLED` / `USER_DISABLED` | `set_user_status(db, user, status, reason, actor_user_id)` | `user_admin_service.py` | `actor_user_id` already a param; no `organization_id` available here (this is a cross-tenant, global user action, not org-scoped — see §4a) |
| `API_KEY_CREATED` | `create_api_key(db, organization_id, creator_user_id, name, scopes, caller_permissions)` | `apikey_service.py` | all needed fields already params |
| `API_KEY_REVOKED` | `revoke_api_key(db, api_key, reason=None)` | `apikey_service.py` | `api_key.organization_id`/`.id`/`.name` available on the row; no actor param exists today (see §4b) |
| `OAUTH_CLIENT_CREATED` | `create_oauth_client(db, organization_id, creator_user_id, name, scopes, caller_permissions)` | `oauth_client_service.py` | same shape as API keys |
| `OAUTH_CLIENT_REVOKED` | `revoke_oauth_client(db, oauth_client, reason=None)` | `oauth_client_service.py` | same gap as API key revoke |
| `SSO_CONFIGURATION_CREATED` | `configure_sso(db, organization_id, issuer, client_id, client_secret, allowed_domains, actor_user_id)` | `org_sso_service.py` | all needed fields already params |
| `SSO_CONFIGURATION_UPDATED` | `update_sso_config(db, config, actor_user_id, issuer=None, client_id=None, client_secret=None, allowed_domains=None)` | `org_sso_service.py` | all needed fields already params |
| `SSO_ENFORCEMENT_CHANGED` | `set_enforced(db, config, enforced, actor_user_id)` | `org_sso_service.py` | before/after value is exactly `config.enforced` pre/post-assignment |

### 4a. `USER_ENABLED`/`USER_DISABLED` — status vocabulary mismatch

`ALLOWED_USER_STATUSES = {"active", "suspended"}` (`schemas/user_admin.py`)
— the codebase's actual status vocabulary is active/suspended, not
enabled/disabled. This PR maps `status == "active"` → `USER_ENABLED`
and `status == "suspended"` → `USER_DISABLED` at the event-type level
only (the task's own requested names); the stored `after_state` still
carries the real `status` string verbatim, so no information is lost
or renamed in the data itself, only in which constant is chosen.
`organization_id` is genuinely not applicable here (confirmed: this
route is `/platform/users/{id}`, a cross-tenant action with no single
org in scope — a user can belong to several orgs or none) — the event
is written with `organization_id=None`, matching the task's own
"(if applicable)" qualifier rather than fabricating one.

### 4b. Revoke functions have no actor parameter today

`revoke_api_key`/`revoke_oauth_client` currently take only `(db, row,
reason=None)` — no `actor_user_id`. Both route handlers
(`routes_apikeys.py::revoke_api_key`, `routes_oauth_clients.py::
revoke_oauth_client`) already resolve the caller via
`require_org_permission_or_platform_admin`, which returns a
`membership` object with `.user_id` — that value is simply not passed
down today. This PR adds `actor_user_id: int | None = None` as a new
keyword parameter to both revoke functions (backward compatible —
existing callers that don't pass it keep working, though there are
none besides these two routes) and updates both routes to pass
`membership.user_id`. This is the one small, necessary service-layer
signature change this PR makes; everything else only *adds* an
audit call, it doesn't change any function's contract.

## 5. Audit retrieval endpoint design

New file `app/api/routes_platform_audit.py`, new service function
`audit_service.list_events(...)`, mirroring
`user_admin_service.list_users`'s exact shape (pagination, filters,
batched N+1-avoiding lookups):

- `GET /platform/audit-events` — filters `organization_id`,
  `actor_user_id`, `event_type`, `start_date`, `end_date` (all
  optional, AND-combined, exactly like `list_users`'s filter
  convention), `page`/`page_size` pagination (`total`/`total_pages`
  response fields, same shape as `PlatformUserListOut`).
- **Permission**: reuses `MANAGE_ALL_ORGS` (`require_permission`) —
  the same permission every other `/platform/*` read endpoint in this
  codebase already uses (`routes_platform_users.py`,
  `routes_platform_permissions.py`, `routes_platform_orgs.py`). No
  dedicated "audit" permission is registered anywhere in
  `app/core/permission_names.py` today, and the task explicitly says
  not to introduce one unless required — it isn't; platform-admin is
  the correct, already-existing boundary for "see every org's audit
  trail."
- **Actor/target/organization display resolution**: `AuditEvent` only
  stores raw integer ids, no denormalized email/name. Response
  resolves `actor_email`, `target_email`, `organization_name` via the
  same *batched* lookup pattern `user_admin_service._org_counts_by_user`/
  `platform_admin_service._counts_by_org` already establish (one
  `IN (...)` query per id-set for the whole page, never one query per
  row) — not a new pattern, the existing one applied to a new field.
- **Immutability**: only a `GET` route is added. No `PATCH`/`DELETE`
  on audit events anywhere — satisfies the task's explicit "audit
  events are immutable" security requirement structurally, not by
  convention alone.

## 6. `omnibioai-control-center` — existing patterns confirmed

- **`navigation.ts`**: `{ key: 'audit-logs', label: 'Audit Logs',
  functional: false }` already exists verbatim under the Security
  section — exact label match, just needs `functional: true` + a
  `visible` gate. No nav restructuring needed.
- **No `src/pages/audit/` directory exists yet** — this PR creates it,
  per the task's explicit path (distinct from `src/pages/identity/`,
  which holds Users/Teams/Roles/SSO/Service-Accounts — Audit Logs is
  its own top-level nav destination, not nested under Identity).
- **Design system** (`components/ui/`): `Card`, `SectionHeader`,
  `LoadingState`, `ErrorState`, `EmptyState`, `ActionToolbar`,
  `DataTable`, `Button` all confirmed present and reused as-is (same
  set every PR11.x page has used).
- **No backend proxy for `/platform/audit-events` exists** — confirmed
  by grep (`backend/src/control_center/api/routes_*_proxy.py`: auth,
  org, user, role, team, org_sso, service_accounts — no audit file).
  This PR adds one route to a new `routes_audit_proxy.py`, same pure-
  relay shape as all six existing proxy files.
- **Filter-toolbar convention**: `UsersPage.tsx` already establishes
  select-dropdown filters (org/status/role) that trigger a refetch via
  state + `useEffect`, no separate "Apply" button — `AuditLogsPage`'s
  filter row (organization, actor, event type, date range) follows the
  same convention, not a new UI pattern.
- **Row-detail convention**: no page has an inline "click a table row
  to see more" interaction yet. `ServiceAccountsPage.tsx` (PR11.4)
  established a page-local `Modal` overlay (mirroring
  `ConfigPage.tsx`'s pre-existing `AddServiceModal`) for its one-time
  secret reveal — `AuditLogsPage` reuses that exact same page-local
  modal shape for its row-detail view, rather than inventing a new
  overlay primitive. (`OrganizationDetailPage.tsx`/`UserDetailPage.tsx`
  navigate to a whole separate page instead; that shape doesn't fit an
  audit *log entry*, which isn't a manageable resource with its own
  page, just a record to inspect.)

## Scope decisions this discovery settles

1. **Reuse the existing `AuditEvent`/`audit_service.log_event`
   machinery entirely as-is** — only `AuditEventType` gains 9 new
   constants and 4 service files gain `log_event` calls (plus one
   small, backward-compatible signature addition to the two revoke
   functions, per §4b).
2. **`USER_ENABLED`/`USER_DISABLED` map onto the existing
   active/suspended status vocabulary** — not a new status value, an
   event-type framing of the same field-level change already tracked.
3. **No new permission** — `GET /platform/audit-events` reuses
   `manage_all_orgs`, exactly like every other `/platform/*` read
   endpoint.
4. **Actor/target/org email resolution is batched**, mirroring
   existing N+1-avoidance patterns already in this codebase, not a new
   query-shape.
5. **Immutability is structural**: only a `GET` route exists; no
   update/delete surface is ever added.
6. **`AuditLogsPage.tsx` lives at `src/pages/audit/`**, its own nav
   destination, not folded into `src/pages/identity/`.
7. **Row detail reuses the page-local `Modal` pattern** PR11.4 already
   established — no new shared overlay component.
8. **Not in scope** (explicitly requested by the task; also — SSO
   break-glass override/clear-override
   (`set_sso_override`/`clear_sso_override` in `org_sso_service.py`)
   are **not** audited by this PR even though they're highly
   sensitive — the task's own required-events list names only
   `SSO_CONFIGURATION_CREATED`/`UPDATED`/`SSO_ENFORCEMENT_CHANGED`, not
   the override endpoints. Flagged explicitly in
   `docs/admin-console-pr11-audit-logs.md`'s limitations as a real gap
   for a follow-up PR, not silently left uncovered.
