# PR11.4 — Enterprise Service Accounts & API Keys Management UI

Adds unified machine-identity management (API keys + OAuth
client-credentials service accounts) to `admin.omnibioai.org` (the
Admin Console / `AdminApp`). This completes the Identity Management
section after PR11.1 (Users), PR11.2 (Teams/Roles), and PR11.3
(Enterprise SSO) — all merged to `main`. This is a UI-only PR: no IAM
redesign, no new permission model, no unsupported backend concepts.
Everything below reuses `omnibioai-auth`'s existing API-key and OAuth
client routes and permissions (`manage_api_keys`, `manage_oauth_clients`)
exactly as-is. See `docs/admin-console-pr11-service-accounts-discovery.md`
for the discovery pass this was built from, including every field the
task's spec asked for that the backend doesn't actually support.

## Architecture

```
 Admin Console UI (frontend/cc-ui)
   ServiceAccountsPage.tsx  ──uses──▶  serviceAccounts.ts (fetch wrapper)
        ▲
        │ reached via
   navigation.ts 'api-keys' nav item ──▶ AdminApp.tsx org-picker/detail
        │   ("API Keys / Service Accounts",  routing (reuses OrganizationsPage
        │    route /iam/service-accounts)     as the "pick an org" list step,
        │                                       same pattern PR11.3 established
        │                                       for SSO)
   OrganizationDetailPage.tsx "Manage Service Accounts" /
   "Manage API Keys" ──▶ deep-links here too, landing on the right tab
        │
        ▼
 control-center backend (backend/src/control_center)
   routes_service_accounts_proxy.py  ── pure HTTP relay, zero auth
                                         decisions ──▶
        │
        ▼
 omnibioai-auth
   routes_apikeys.py        (require_org_permission_or_platform_admin(manage_api_keys))
   routes_oauth_clients.py  (require_org_permission_or_platform_admin(manage_oauth_clients))
   routes_platform_permissions.py  (require_permission(manage_all_orgs) --
                                     scope-picker support only, see Scopes below)
        │
        ▼
   apikey_service.py / oauth_client_service.py
     (SHA-256-hashed secrets at rest, plaintext returned exactly once)
```

Three layers, each doing exactly one job:

1. **`ServiceAccountsPage.tsx`** (`frontend/cc-ui/src/pages/identity/`) —
   all presentation, client-side validation, and secret-reveal handling.
   Two tabs, **OAuth Clients** and **API Keys**, each independently
   fetched/gated (a caller may hold `manage_api_keys` without
   `manage_oauth_clients`, or vice versa — see Permissions below).
   Reached two ways, exactly mirroring PR11.3's SSO page:
   - The `API Keys / Service Accounts` nav item (`functional: true`,
     `visible: hasOrganizationsAccess`) → org-picker (`OrganizationsPage`,
     reused unmodified) → this page, deep-linked at
     `/iam/service-accounts/{orgId}`.
   - `OrganizationDetailPage.tsx`'s two "Manage Service Accounts" /
     "Manage API Keys" links, which jump straight to
     `/iam/service-accounts/{orgId}`, landing on the OAuth Clients or
     API Keys tab respectively.
2. **`routes_service_accounts_proxy.py`** (`backend/src/control_center/api/`)
   — a pure relay, following the exact shape of the other proxy files in
   this repo. Forwards `Authorization`/body/query params verbatim,
   relays status/body back unmodified (including the 204-empty-body
   revoke case). Makes **zero** authorization decisions — and never
   inspects, logs, or caches the bodies it forwards, which matters here
   specifically because `POST` responses carry a plaintext
   `key`/`client_secret` on the way back.
3. **`omnibioai-auth`'s existing routes** — unchanged by this PR.
   `routes_apikeys.py` and `routes_oauth_clients.py`'s 6 combined
   routes are the entire mutation surface; `routes_platform_permissions.py`'s
   read-only `GET /platform/permissions` is used only as an optional
   scope-picker data source (see Scopes below), also unchanged.

## Security

### Secret handling

- **Both `key` (API keys) and `client_secret` (OAuth clients) are
  write-only.** Neither `ApiKeyOut` nor `OAuthClientOut` (what every
  `GET` returns) has a secret/hash field — confirmed directly against
  `omnibioai-auth`'s schemas. There is nothing for this UI to leak on a
  list view even by accident.
- The secret is shown **exactly once**, immediately after a successful
  create, in a dedicated reveal modal with an explicit red warning
  ("The secret will only be shown once...") and a Copy button
  (`navigator.clipboard.writeText`, with a graceful no-op fallback if
  the Clipboard API isn't available).
- **Not retained longer than necessary**: the revealed secret lives in
  one `useState` slot on the section component (`ApiKeysSection`/
  `OAuthClientsSection`), is never written to `localStorage` or any
  persistent store, and is cleared (`setCreated(null)`) the moment the
  admin dismisses the reveal dialog — at that point it is gone from
  memory entirely, not just visually hidden.
- The proxy layer is a byte-for-byte relay (see Architecture above): a
  `client_secret`/`key` passes through the control-center backend
  without a second copy of it ever being held beyond the single
  in-flight request/response.

### Permissions

No new permission was introduced. Both permissions this feature uses
already existed in `omnibioai-auth` and are enforced entirely
server-side:

- **`manage_api_keys`** (org-scoped) — all 3 API-key routes.
- **`manage_oauth_clients`** (org-scoped) — all 3 OAuth-client routes.

The frontend's role is UX only, never the security boundary — each tab
independently attempts its `GET`, and a `403` (member without the
specific permission) or `404` (non-member — `omnibioai-auth`
deliberately doesn't distinguish "no such org" from "not your org" to
avoid leaking existence) both render as a permission-denied variant
driven by the backend's actual response, never a client-computed gate.
The nav item itself gates on `hasOrganizationsAccess()` (identical to
`organizations` and PR11.3's `iam` item) purely to decide whether the
destination appears at all.

One additional read-only route is used, **only as scope-picker
convenience**: `GET /platform/permissions`
(`routes_platform_permissions.py`), gated by the existing
`manage_all_orgs` (platform-admin) permission — unchanged, not
expanded, and not required for this feature's core CRUD to work. See
Scopes below.

### Lifecycle

- `status`: `active` → `revoked`. Revoking is immediate, requires an
  inline confirmation step (mirroring `OrganizationDetailPage.tsx`'s
  `StatusAction` confirm pattern), and needs no reason field — the
  backend's revoke routes don't accept one.
- `expires_at`: present in both schemas, but **no route in
  `omnibioai-auth` ever sets it today** — every key/client created
  through this UI has no expiry. Displayed as-is (would read a real
  date if the backend ever starts setting one); not a UI limitation to
  work around.
- `last_used_at`: real and live for OAuth clients (updated by
  `oauth_client_service.mark_used` on every client-credentials token
  exchange). **Effectively always "Never" for API keys** — the
  equivalent `apikey_service.verify_api_key` exists but isn't wired
  into any live authentication path yet, confirmed by discovery. The
  UI shows this accurately (`Never`) rather than implying activity that
  isn't tracked.

### Scopes

Scopes are handled without ever fabricating a permission catalog (see
discovery doc §6 for the full reasoning):

- **Platform admins** get a real, registry-backed scope picker (`GET
  /platform/permissions`, proxied read-only) — a genuine list of valid
  permission names, purely as a UX convenience.
- **Everyone else** (a regular org admin with `manage_api_keys`/
  `manage_oauth_clients` but not `manage_all_orgs`) gets free-text
  scope entry, with suggestions drawn only from scopes already present
  on that org's existing keys/clients (data already on-screen, zero
  extra calls) — never an invented list.
- Either way, the backend's own scope rejection —
  `"Cannot grant scopes you don't hold: [...]"` (both resource types) or
  `"Unknown service permission: X. Did you mean: Y?"` (OAuth clients
  only — API keys have no registry-format check, see discovery doc §1)
  — is surfaced verbatim inline on a failed submit. The client-side
  list is never the authorization boundary.

## Limitations

Per the task's own explicit scope:

- **No secret rotation.** Creating a new key/client is the only way to
  get a new secret; there is no "regenerate secret for this existing
  row" action, because `omnibioai-auth` has no such endpoint.
- **No automatic expiry.** `expires_at` is schema-only today (see
  Lifecycle above) — this UI doesn't pretend otherwise.
- **No advanced audit analytics — and no audit trail at all for these
  actions today.** Confirmed directly (not assumed): create/revoke for
  both API keys and OAuth clients emit **zero** audit events —
  `app/services/audit_service.py`'s `AuditEventType` only covers login
  and role/permission/org-membership changes, and neither
  `apikey_service.py` nor `oauth_client_service.py` (nor their routes)
  ever calls `audit_service.log_event`. **Follow-up recommendation**
  (not built in this PR, per its own instruction not to expand scope):
  add `API_KEY_CREATED` / `API_KEY_REVOKED` / `OAUTH_CLIENT_CREATED` /
  `OAUTH_CLIENT_REVOKED` event types and call `audit_service.log_event`
  from inside `apikey_service.create_api_key`/`revoke_api_key` and
  `oauth_client_service.create_oauth_client`/`revoke_oauth_client` —
  the same "log at the point of mutation, not the route handler"
  convention every other audited action in that file already follows.
- **No SCIM.** Directory sync/provisioning is unrelated to these two
  resource types entirely; not touched.
- **No "Created by" column.** The task's spec asked for one; neither
  `ApiKeyOut` nor `OAuthClientOut` exposes `created_by_user_id` (or a
  resolved email), so it's omitted rather than invented — see discovery
  doc §1/§2.
