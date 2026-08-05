# PR11.3 — Enterprise SSO Management UI: Discovery

Discovery pass performed before any implementation, per this PR's own
instructions. Everything below was verified directly against the
`omnibioai-auth` and `omnibioai-control-center` source on `main`
(auth: `feature/pr11-user-management` branch, tip `585c870`, which is
current `main` plus one unrelated in-flight change — the SSO surface
itself is unchanged from `main`), not assumed or recalled from memory.

## 1. Existing SSO APIs in `omnibioai-auth`

All under `app/api/routes_org_sso.py`, `prefix="/orgs/{org_id}/sso"`:

| Method | Path | Auth dependency | Notes |
|---|---|---|---|
| `POST` | `/orgs/{org_id}/sso` | `require_org_permission_or_platform_admin(MANAGE_SSO)` | Creates the org's SSO config. 409 if one already exists (one IdP per org). Runs live OIDC discovery (`.well-known/openid-configuration`) before persisting; 400 on discovery failure, 500 if `CONFIG_ENCRYPTION_KEY` isn't set. |
| `GET` | `/orgs/{org_id}/sso` | same | 404 if no config exists yet. |
| `PATCH` | `/orgs/{org_id}/sso` | same | Partial update (`None` = unchanged). Re-runs discovery only if `issuer` actually changes. Also handles `enforced` (see below) — a 400 here is the *lockout guard*, not a validation error. |
| `DELETE` | `/orgs/{org_id}/sso` | same | 204, hard-deletes the config row. |
| `POST` | `/orgs/{org_id}/sso/override` | `require_permission(OVERRIDE_SSO_ENFORCEMENT)` — **global**, not org-scoped | Break-glass: suspends the *effect* of `enforced` without changing it. Deliberately global-admin-only so a locked-out org's own admin can't self-serve it — see `routes_org_sso.py`'s own comment. |
| `DELETE` | `/orgs/{org_id}/sso/override` | same | Clears the override. |

Response shape (`OrgSSOConfigOut`, `app/schemas/org_sso.py`) — **never
includes `client_secret` or `client_secret_encrypted`**:

```
issuer: str
client_id: str
provider_type: str            # always "oidc" today
allowed_domains: list[str]
status: str                   # "pending_verification" | "active" | "disabled"
created_at: datetime | None
updated_at: datetime | None
enforced: bool
sso_override_active: bool     # true while a break-glass override is live
```

Request shapes:

- `OrgSSOConfigCreate`: `issuer`, `client_id`, `client_secret` (all
  required), `allowed_domains: list[str] = []`.
- `OrgSSOConfigUpdate`: all of the above optional, plus `enforced:
  bool | None`.
- `SSOOverrideRequest`: `reason: str` (required — recorded, not just a
  UI nicety; `org_sso_service.set_sso_override` persists it).

### Fields the task's spec asks for that the backend does not have

Cross-checking the task's "Current Configuration" and "Configure OIDC
Provider" field lists against the actual schema above:

- **`scopes`** (listed as an optional form field) — **does not exist**
  anywhere in `OrganizationSSOConfig` (`app/db/models.py`),
  `org_sso_service.py`, or the OIDC exchange (`org_oidc_service.py`).
  There is no backend capability to send it to. Per this PR's own
  constraint ("reuse existing backend capabilities... do not
  redesign"), **this field is omitted** from the form rather than
  invented client-side. Flagged as a gap for a future backend PR, not
  silently dropped.
- **`discovery_status`** as a separate field — discovery is a
  synchronous, blocking step of create/update, not a persisted async
  status machine. A failed discovery attempt is *never persisted*
  (`configure_sso`/`update_sso_config` raise before touching the row).
  So the only "discovery status" that exists is: did the last
  create/update call succeed (in which case `status="active"` and
  `last_verified_at` was just set), or did it 400 (nothing persisted,
  the old config — if any — is untouched). The UI surfaces this as
  part of the config's `status` field plus the error surfaced inline
  on a failed submit, not a separate persisted field.
- **`Enabled/Disabled`** as a separate toggle — there is no dedicated
  enable/disable endpoint or field distinct from `status`. The model
  column comment (`app/db/models.py:356`) documents
  `status: pending_verification | active | disabled`, but nothing in
  the current API ever writes `"disabled"` — `configure_sso` always
  sets `"active"` on success, and there's no route that sets it to
  `"disabled"`. The UI displays `status` verbatim as the source of
  truth (task instruction: "Use backend response as source of truth")
  rather than inventing a client-side enable/disable action the
  backend doesn't support.

None of the above required a schema/route change — they're **display
accuracy decisions**, resolved by matching the UI to what the API
actually returns, not by adding backend capability.

## 2. Existing permissions

Both already registered in `app/core/permission_names.py`, confirmed
`legacy=True` (pre-existing, not newly added by this discovery):

- **`manage_sso`** — `resource=sso`, `action=manage`, `scope=ORG`.
  "Manage an organization's SSO/OIDC identity provider configuration."
  Enforced via `require_org_permission_or_platform_admin(MANAGE_SSO)`
  on all 4 CRUD routes — an org's own `org_admin`-role holder (or a
  platform admin via the synthetic-membership bypass) can manage it.
- **`override_sso_enforcement`** — `resource=sso_enforcement`,
  `action=override`, `scope=GLOBAL`. "Break-glass override of an
  organization's enforced SSO login." Enforced via
  `require_permission(OVERRIDE_SSO_ENFORCEMENT)` — global-admin only,
  by design (see table above).

**No new permission is introduced by this PR.** The frontend gates
purely on `hasPermission('manage_sso')` / `hasPermission
('override_sso_enforcement')` (existing `auth.ts` primitive, same one
`hasPlatformAdminAccess()` already uses for `manage_all_orgs`) — and
even where the frontend's gate is wrong or stale, the backend
dependency is what actually enforces it, same pattern as every other
page in this app (see `StatusAction`'s comment in
`OrganizationDetailPage.tsx`).

One caveat worth flagging: `permissions` on the cached `SessionUser`
(`auth.ts`) comes from the *access token's* claims. For a global
permission (`override_sso_enforcement`) that's unambiguous. For an
org-scoped permission (`manage_sso`) held via an org role, whether it
shows up in `cachedUser.permissions` depends on whether the org-aware
JWT (Phase 1 PR3) includes org-role-derived permissions in that claim
for the org currently in context — this mirrors exactly how
`MembersRolesCard` in `OrganizationDetailPage.tsx` already relies on a
403 from the backend (not a frontend permission check) to decide
whether to render, since the frontend has no reliable client-side
signal for "does this token's `manage_org` apply to *this specific*
org." SSOSettingsPage follows the same convention: it always attempts
the `GET`, and treats a 403 as "you don't have `manage_sso` for this
org" (render an explanatory empty/denied state), never as a
client-computed gate.

## 3. Existing frontend patterns (`frontend/cc-ui/src`)

All confirmed present and reused as-is — **no duplicate components
created**:

| Pattern | Location | Used for |
|---|---|---|
| `AppShell` | `components/shell/AppShell.tsx` (+`SidebarNav`, `TopAppBar`) | Already wraps every `AdminApp` page; SSOSettingsPage needs no changes here. |
| `DataTable` | `components/ui/DataTable.tsx` | **Not used** — SSO config is a single record per org, not a list. Using it here would mean fabricating rows for a non-list. Every other primitive below is used instead. |
| `Card` | `components/ui/Card.tsx` | Section containers (Current Configuration, Configure Provider, Enforcement, Break-Glass). |
| `SectionHeader` | `components/ui/SectionHeader.tsx` | Page and section titles. |
| `LoadingState` | `components/ui/LoadingState.tsx` | While `GET /orgs/{id}/sso` is in flight. |
| `ErrorState` | `components/ui/ErrorState.tsx` | Unexpected fetch failures (network/5xx), with retry. |
| `EmptyState` | `components/ui/EmptyState.tsx` | No SSO configured yet, and the 403/permission-denied case. |
| `ActionToolbar` | `components/ui/ActionToolbar.tsx` | Button row (Edit / Enable enforcement / Override actions). |
| `Button` | `components/ui/Button.tsx` | All buttons, primary/secondary/ghost variants already defined. |
| `navigation.ts` gating | `visible?: () => boolean` on `NavItem` | Existing mechanism the `iam` entry will use — see below. |

Page/API-client conventions confirmed by reading
`pages/OrganizationDetailPage.tsx`, `pages/OrganizationsPage.tsx`,
`roles.ts`, `teams.ts`, `organizations.ts`:

- A `<resource>.ts` file at `src/` root holds `apiFetch`-wrapped calls
  (relative paths, `authHeaders()`, 401 → `reportUnauthorized()`) and
  the TS interfaces for that resource — `sso.ts` follows this exactly.
- List pages take an `onSelect(id)` prop; `AdminApp.tsx` owns the
  selected-id state and switches between list/detail, exactly like
  `organizations`/`users`. `OrganizationsPage`'s `onSelect` signature
  (`(orgId: number) => void`) is generic enough to reuse directly as
  the org-picker for the new `iam` nav destination — **no new "pick an
  org" list component needed**.
- Detail pages take the resolved id (+ `onBack`) as props, fetch their
  own data, and render `LoadingState`/`ErrorState`/actual content.

### Navigation (`navigation.ts`)

Current `iam` entry:

```ts
{ key: 'iam', label: 'IAM', functional: false },
```

Task asks for label "IAM / SSO Management" and `functional: true`. No
existing `visible` gate is attached to `iam` today (it's Coming Soon,
so per the module's own convention Coming-Soon items show no gate).
Once functional, it needs one — reusing `hasOrganizationsAccess`
(already exported from `auth.ts`, already used for the `organizations`
item, and semantically correct: it is exactly "admin, platform admin,
or a member of some org" — the same audience who could plausibly reach
*some* org's SSO settings via the org-picker). The actual
authorization for any given org's SSO data is still 100% the backend's
`manage_sso`/`override_sso_enforcement` checks, per §2 above — this
`visible` gate only decides whether the nav entry (and its org-picker
landing page) appears at all, same division of responsibility every
other nav item already has.

### `OrganizationDetailPage.tsx`'s existing SSO section

`PlatformDetailView` (platform-admin path only — `MyOrgDetailView`,
the org-admin path, has no SSO section today; see its own comment
about not inventing new API calls) already renders a read-only block
fed by `PlatformOrgDetail.sso` (`organizations.ts`'s
`SSOConfigSummary`: `configured, provider_type, issuer, status,
enforced, override_active` — no `client_id`, no dates, and obviously
no secret). This PR replaces that block's *presentation* with
`OrganizationSummaryCard`-style framing plus a "Manage SSO Settings"
link into the new page — it does not add a second data fetch to
`OrganizationDetailPage.tsx` itself; the full detail (client_id,
allowed_domains, timestamps) loads inside `SSOSettingsPage` via its own
`GET /orgs/{id}/sso` call once navigated to.

### Backend proxy layer (control-center's own FastAPI backend)

`backend/src/control_center/api/routes_{org,user,role,team}_proxy.py`
all share one shape: a local `_proxy(method, path, request)` helper
that forwards the `Authorization` header and body/query params to
`omnibioai-auth` (`IAM_URL` env var) verbatim, relays the upstream
status/body (including the 204-empty-body case), and makes **zero**
authorization decisions locally. **No `/orgs/{org_id}/sso*` proxy
exists yet** (confirmed by grep — the only `sso` hits in the backend
are the unrelated session-cookie/JWT-verification comments in
`routes_auth_proxy.py`/`jwt_verify.py`). This PR adds
`routes_org_sso_proxy.py` following the exact same pattern (modeled
most closely on `routes_team_proxy.py`, since both are pure
`/orgs/{org_id}/...` CRUD-plus-subresource shapes), registered in
`main.py` alongside the other four.

## Scope decisions this discovery settles

1. **No `scopes` field** in the Configure form — backend has no
   capability for it (see §1).
2. **No client-side enable/disable action** — `status` is rendered
   read-only from the backend response; the only mutating write is
   `enforced` (via `PATCH`, existing lockout guard) and the override
   endpoints. If a future backend PR adds a real disable endpoint, the
   UI's `status` display doesn't need to change — only a new action
   would need to be added then.
3. **`iam` nav gate** reuses `hasOrganizationsAccess` — no new
   permission, no new frontend gating primitive.
4. **Org-picker reuses `OrganizationsPage`** as-is for the `iam`
   destination's list step — no new "choose an organization" list
   component.
5. **`DataTable` is not used** on `SSOSettingsPage` — the page has no
   list content; `Card`/`SectionHeader`/`ActionToolbar` cover it.
6. **One proxy file**, `routes_org_sso_proxy.py`, covering all 6
   routes (4 CRUD + 2 override) — matches `routes_org_sso.py`'s own
   choice to keep them in one router rather than splitting override
   out, and matches this repo's "one proxy file per backend concern"
   convention.
