# PR11.4 — Enterprise Service Accounts & API Keys Management UI: Discovery

Discovery pass performed before any implementation, per this PR's own
instructions. Everything below was verified directly against the
`omnibioai-auth` and `omnibioai-control-center` source (both on
`main`), not assumed or recalled from a prior PR.

## 1. API Keys (`omnibioai-auth`)

Routes, all under `app/api/routes_apikeys.py`,
`prefix="/orgs/{org_id}/api-keys"` — match the task's expected routes
exactly:

| Method | Path | Auth dependency |
|---|---|---|
| `POST` | `/orgs/{org_id}/api-keys` | `require_org_permission_or_platform_admin(manage_api_keys)` |
| `GET` | `/orgs/{org_id}/api-keys` | same |
| `DELETE` | `/orgs/{org_id}/api-keys/{key_id}` | same (`{key_id}` is the row's numeric `id`, not `key_prefix`) |

**Request/response schemas** (`app/schemas/apikeys.py`):

```
ApiKeyCreate:   { name: str, scopes: list[str] = [] }
ApiKeyCreated:  { id, name, key_prefix, scopes, key }   # key = full plaintext, once
ApiKeyOut:      { id, name, key_prefix, scopes, status, created_at, expires_at, last_used_at }
```

**Secret handling** (`app/services/apikey_service.py`): a random
40-char secret (`omni_sk_...` prefix) is generated, only its SHA-256
hash (`key_hash`) is persisted, and the plaintext is returned exactly
once, in the `POST` response body only. `ApiKeyOut` (what `GET`
returns) has no `key`/`key_hash` field at all — there's nothing to
leak even by accident on subsequent list calls.

**Scopes behavior**: `create_api_key` validates `scopes` against
`caller_permissions` (the *creating user's own effective permissions in
this org*, from `org_service.permissions_for_membership`) — `set(scopes)
- caller_permissions` non-empty → `400 "Cannot grant scopes you don't
hold: [...]"`. **No registry-format check** here (unlike OAuth clients,
below) — any string the caller happens to hold as a real permission in
this org is accepted, nothing else is validated for "is this a real
permission name" shape. Since every permission a caller can actually
hold is by construction a registered name already, this doesn't allow
garbage scopes in practice, but the API key path itself doesn't enforce
that independently.

**Lifecycle fields**: `status` (`active`/`revoked`), `created_at`,
`expires_at` (schema supports it; **no route ever sets it** — every key
created today has `expires_at = null`, i.e. no expiry, confirmed by
`create_api_key` never passing it), `last_used_at` (column exists;
`verify_api_key` would update usage but **is not called from any route**
yet — confirmed by grep, it exists only for a future gateway/iam-client
integration per its own docstring). **In practice, `last_used_at` is
always `null` today.** `revoked_at`/`revoked_reason` exist on the model
but the route never sends a reason (`revoke_api_key(db, key)`, no
`reason` argument) — this UI does not need a reason field for revoke
either.

**Gap vs. the task's requested column list**: the task asks for a
"Created by" column. `ApiKeyOut` has no `created_by_user_id` (or
resolved email) field — the DB row has `created_by_user_id`, but it is
never serialized into the response, and there is no join/lookup
anywhere that would let this UI resolve it to an email without a new
backend field. **This UI omits "Created by"** rather than inventing a
resolution path the backend doesn't support (same treatment PR11.3 gave
SSO's non-existent `scopes` field).

## 2. OAuth Clients / Service Accounts (`omnibioai-auth`)

Routes, `app/api/routes_oauth_clients.py`,
`prefix="/orgs/{org_id}/oauth-clients"` — match the task's expected
routes exactly:

| Method | Path | Auth dependency |
|---|---|---|
| `POST` | `/orgs/{org_id}/oauth-clients` | `require_org_permission_or_platform_admin(manage_oauth_clients)` |
| `GET` | `/orgs/{org_id}/oauth-clients` | same |
| `DELETE` | `/orgs/{org_id}/oauth-clients/{client_id}` | same (`{client_id}` here is the row's numeric `id`, **not** the OAuth `client_id` string — same naming collision as API keys' `{key_id}`; the frontend must revoke by numeric `id`, never by the public `client_id` string) |

**Schemas** (`app/schemas/oauth_client.py`):

```
OAuthClientCreate:  { name: str, scopes: list[str] = [] }
OAuthClientCreated: { id, name, client_id, scopes, client_secret }   # secret = plaintext, once
OAuthClientOut:     { id, name, client_id, scopes, status, created_at, expires_at, last_used_at }
```

Plus `ClientCredentialsTokenResponse` — the actual token-exchange
response shape for the (separate, unauthenticated)
`client_credentials` grant flow. Not part of this UI (that's the
service caller's job, not an admin's), noted for completeness only.

**Client credentials flow**: `verify_client_credentials` (in
`oauth_client_service.py`) looks up by the public `client_id`, then
compares the presented secret's SHA-256 hash to the stored
`client_secret_hash`. Not reachable from this admin UI at all — it's
what a *service* does to obtain a token, wired into
`routes_oauth.py`'s token endpoint separately. `mark_used()` sets
`last_used_at = now()` — **and, unlike API keys' `verify_api_key`, this
function is real and reachable via the actual token-exchange path**, so
`last_used_at` for OAuth clients is a real, live-updating field once a
client is actually used to mint a token. (Confirmed the call site exists
in the token-exchange route, not just defined-but-orphaned like the API
key equivalent.)

**Client secret handling**: identical pattern to API keys —
SHA-256-hashed at rest, plaintext returned exactly once in the `POST`
response, `OAuthClientOut` (what `GET` returns) has no secret field.

**Scopes behavior — the important difference from API keys**:
`create_oauth_client` (`oauth_client_service.py`) validates scopes in
**two** steps:
1. Every scope must be `is_known_permission(scope)` — a real, registered
   name in `app.core.permission_names.REGISTRY` — else `400 "Unknown
   service permission: {scope}. Did you mean: ...?"` (nearest-match
   suggestion via `difflib`, same UX `role_service` already uses for
   role permission names).
2. Then, same as API keys: `set(scopes) - caller_permissions` → `400
   "Cannot grant scopes you don't hold: [...]"`.

So OAuth client scopes **are** backed by a real, queryable permission
registry — API key scopes are not independently registry-checked (see
§1). This directly answers the task's "verify backend behavior" scope
question, and the two creation forms are built differently as a result
(see §6 below).

**Lifecycle fields**: same shape as API keys — `expires_at` schema
support, never set by any route today (always `null`); `revoked_at`/
`revoked_reason` exist, no reason ever sent by the route.

**Same "Created by" gap** as API keys — `OAuthClientOut` has no
`created_by_user_id`; omitted from this UI for the same reason.

## 3. Existing permissions

Both already registered (`app/core/permission_names.py`), confirmed
pre-existing, `legacy=True`:

- **`manage_api_keys`** — org-scoped. Gates all 3 API key routes via
  `require_org_permission_or_platform_admin`.
- **`manage_oauth_clients`** — org-scoped. Gates all 3 OAuth client
  routes the same way.

**No new permission is introduced.** No `service_accounts.manage`,
`iam.manage`, or `security.manage` — discovery found no gap that would
require one; the two existing permissions cover 100% of this PR's
surface, exactly as the task expected.

One nuance worth flagging precisely (it changes how this UI reads
errors): `require_org_permission_or_platform_admin`'s dependency chain
is two steps —
`get_org_membership_or_platform_admin` (raises **404** if the caller
isn't a member of the org and isn't a platform admin — org existence
and membership are not distinguished, by design, to avoid leaking
which org IDs exist) → then a permission check (raises **403** if the
caller *is* a member but lacks `manage_api_keys`/`manage_oauth_clients`
specifically). Confirmed against
`tests/test_apikeys.py::test_non_member_cannot_list_or_revoke_api_keys`
and the OAuth client tests' identical counterpart. Unlike SSO's `GET`
(PR11.3), **list endpoints here never 404 for "nothing configured yet"**
— an authorized caller with zero keys/clients simply gets `200 []`. So
this UI's error-state handling treats 404 as "no access to this org"
and 403 as "you're a member but lack the specific permission" — both
render as permission-denied variants (see §7); an empty `200` list is
an ordinary, non-error empty state.

## 4. Audit trail (task's explicit discovery item)

Checked `app/services/audit_service.py`'s `AuditEventType` and grepped
both `apikey_service.py` and `oauth_client_service.py` (and their
routes) for any call to `audit_service.log_event`.

**Result: none of create/revoke API key, create/revoke OAuth client are
audited today.** `AuditEventType` only defines login and
role/permission/org-membership event types; zero references to
`audit_service` exist in either service or route file for this PR's
surface. This is a real, pre-existing gap — documented explicitly in
`docs/admin-console-pr11-service-accounts.md` as a follow-up
recommendation, per the task's own instruction not to expand this PR
into building an audit system.

## 5. Existing frontend patterns

Confirmed present, reused as-is, same conventions PR11.3 already
established:

- `Card`, `SectionHeader`, `LoadingState`, `ErrorState`, `EmptyState`,
  `ActionToolbar`, `Button`, `DataTable` — all in `components/ui/`,
  unchanged since PR11.3's own discovery. **`DataTable` is used this
  time** — both API keys and OAuth clients are genuine lists, unlike
  SSO's single-record-per-org shape.
- `OrgSelector` (`components/shell/OrgSelector.tsx`) is a **static,
  non-interactive** header indicator (shows the session's own org
  context in `TopAppBar`) — not an org-picker. The task's "reuse
  OrgSelector" is satisfied by leaving it untouched, not by building an
  org-picker out of it.
- The actual org-picker reused is **`OrganizationsPage`** (its
  `onSelect(orgId: number) => void` signature), exactly the pattern
  PR11.3 established for the `iam` (SSO) nav destination — no second
  "choose an org" component is built here either.
- `PlatformOrgDetail.api_key_summary` / `.oauth_client_summary`
  (`organizations.ts`, populated by
  `platform_admin_service.py::api_key_counts`/`oauth_client_counts` —
  real, accurate `status == "active"` counts) already exist and are
  already rendered via `OrganizationSummaryCard` on
  `OrganizationDetailPage.tsx`. The task asks for "count + active"
  summary cards — **that data and that rendering already exist**; the
  actual gap is only the missing "Manage Service Accounts"/"Manage API
  Keys" links, which this PR adds without rebuilding the cards
  themselves (not available on the org-admin/`MyOrg` view, same
  pre-existing limitation `sso` had in PR11.3 — that schema has no
  summary fields at all).
- `<resource>.ts` API-client convention (`roles.ts`, `teams.ts`,
  and PR11.3's `sso.ts`, none of which are on `main` except `roles.ts`/
  `teams.ts` — PR11.2/PR11.3 are still open, unmerged PRs, so this PR
  branches from `main` and does not depend on either).
- **Permission registry**: `GET /platform/permissions`
  (`routes_platform_permissions.py`) exposes the full
  `app.core.permission_names.REGISTRY` read-only — but it's gated by
  `require_permission(manage_all_orgs)`, i.e. **platform-admin only**.
  A regular org admin with `manage_oauth_clients` but not
  `manage_all_orgs` gets 403 from it. See §6 for how the scope picker
  handles this split audience without fabricating a fallback catalog.

## 6. Scope handling design (resolves the task's explicit discovery item)

Given §1/§2/§5 above, scopes are handled differently depending on what
the backend can actually tell this UI, never a hardcoded/fake catalog:

- **If the caller is a platform admin** (`hasPlatformAdminAccess()`):
  fetch the real registry via `GET /platform/permissions` (newly
  proxied by this PR — see §8) and offer it as a searchable multi-select
  of real, registered permission names. This is still just a UX
  convenience; the backend's own checks (§1/§2) are what actually
  enforce it.
- **Otherwise** (a regular org admin holding `manage_api_keys`/
  `manage_oauth_clients` without platform-admin scope): `/platform/
  permissions` is a 403 for them, so this UI falls back to **free-text
  entry** for scopes, plus a suggestions list built from `Set(scopes)`
  already present across that org's own existing keys/clients (data
  already on-screen from the `GET` list response — zero extra calls,
  literally "display existing scope values only," per the task's own
  fallback instruction). No permission name is ever invented
  client-side.
- Either way, the backend's own rejection (`400` "Cannot grant scopes
  you don't hold" / "Unknown service permission... did you mean?") is
  surfaced verbatim inline on a failed submit — the client-side list is
  a convenience, never the authorization boundary.

## 7. Backend proxy layer

`backend/src/control_center/api/routes_{org,user,role,team,org_sso}_proxy.py`
(the last one from PR11.3, unmerged, not present on this branch) all
share one shape: a local `_proxy(method, path, request)` helper
forwarding `Authorization`/body/query params verbatim, relaying the
upstream status/body (including 204-empty-body) unmodified, zero local
authorization decisions. **No `/orgs/{org_id}/api-keys*` or
`/orgs/{org_id}/oauth-clients*` proxy exists on `main`** (confirmed by
grep — the only `api_key`/`oauth_client` hits in the backend are
unrelated: `routes_llm.py`'s LLM-provider config keys and
`routes_dashboard.py`'s aggregation of that same LLM config, not org API
keys). This PR adds one new file, `routes_service_accounts_proxy.py`,
covering both resource families (API keys and OAuth clients are the
same "machine identity" concern this PR's own page unifies) plus the
one `GET /platform/permissions` route the scope picker needs — matching
`routes_org_sso.py`'s own precedent of keeping closely-related routes in
one proxy file rather than splitting further.

## Scope decisions this discovery settles

1. **No "Created by" column** in either table — `ApiKeyOut`/
   `OAuthClientOut` have no such field, and there's no email-resolution
   path available to this UI without a new backend field.
2. **No expiry/rotation UI** — `expires_at` is schema-only, never set by
   any route; documented as a limitation, not built around.
3. **`last_used_at` is meaningful for OAuth clients, effectively always
   `null` for API keys today** — both columns are still shown (matching
   the task's requested column list and the schema's real shape), but
   the API keys table's "Last used" will read "Never" for every row
   until a future PR wires `verify_api_key` into the gateway/iam-client
   path (out of scope here).
4. **Revoke needs no reason field** — the route never accepts one.
5. **`DataTable` is used** for both sections (unlike PR11.3's SSO page)
   — these are genuine per-org lists.
6. **Org-picker reuses `OrganizationsPage`** as-is, same as PR11.3 — no
   second list component.
7. **Scope picker is two-tier** (registry-backed for platform admins,
   free-text + "seen before" suggestions otherwise) — never a fabricated
   static permission catalog.
8. **One proxy file**, `routes_service_accounts_proxy.py`, covering API
   keys, OAuth clients, and the read-only permission registry passthrough.
9. **No audit logging exists for these actions** — documented as an
   explicit, named follow-up recommendation, not built in this PR.
10. This PR branches from `main`, independent of PR11.2/PR11.3 (both
    still open, unmerged) — no dependency on either.
