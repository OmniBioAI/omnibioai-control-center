# PR11.5 — Enterprise Security Foundation: Architecture Discovery

**Status: discovery only. No code changed, no migrations, no endpoints
added.** Every claim below was verified directly against source in
this session — file paths and function names are given throughout so
each claim is independently re-checkable; nothing here is inferred
from naming or carried over from memory without re-confirming it
against current code. This PR supersedes (and updates) the earlier,
uncommitted `docs/admin-console-pr11-identity-findings.md` discovery
pass on the points that have since changed (PR11.1–PR11.4c all shipped
between that pass and this one) — see §9.

Repositories covered: `omnibioai-auth` (primary — the sole identity
source of truth), `omnibioai-control-center` (Admin Console), and a
verification pass over `omnibioai-iam-client` and
`omnibioai-api-gateway` to confirm neither is a blocker or an
alternative enforcement point.

---

## Executive Summary

- **MFA does not exist in any form.** Zero database columns, zero
  service functions, zero routes, zero reserved/stubbed fields — a
  full-text grep for `mfa|totp|webauthn|fido|2fa|otp_secret|backup_code|
  recovery_code` across every `.py` file in `omnibioai-auth` returns no
  matches. This is a green-field build, not an extension of partial
  work.
- **There is exactly one converging choke point for token issuance**
  across every human-login flow: `auth_service.generate_tokens()`.
  Seven call sites, across four route files, all funnel through it.
  This is the single best insertion point for an MFA gate (§1.7).
- **Organization-level security policy is limited to one field**:
  `OrganizationSSOConfig.enforced` (require SSO login). There is no
  general security-policy object, no `require_mfa`, no session
  timeout, no password policy, no IP/domain restriction beyond SSO's
  own self-declared `allowed_domains`.
- **No brute-force protection, no rate limiting, no account lockout**
  anywhere in the service — confirmed by grep, not assumed.
- **The Admin Console is unusually ready for this work**: its own
  `SecuritySummaryCard.tsx` already renders explicit "MFA: Not
  configured" / "Domain: Pending verification" placeholder text (PR11.2),
  written specifically because this exact gap was already confirmed
  once before. The design system, nav taxonomy, and permission-gating
  pattern PR11.1–11.4c already established are directly reusable.
- **`omnibioai-iam-client` and `omnibioai-api-gateway` are not
  blockers and should not be where MFA is enforced.** Both are pure
  downstream consumers of the JWT claims `omnibioai-auth` issues —
  neither has any MFA/session concept, and neither needs one: enforcing
  MFA at token-issuance time in `omnibioai-auth` makes every downstream
  consumer automatically correct without any changes on their part.
- **One concrete, newly-discovered enforcement gap** (not in the prior
  discovery pass): the license/desktop-client login flow
  (`POST /license/validate`) never checks SSO enforcement at all — an
  org that requires SSO login can still be logged into via a valid
  license key. See §6, risk R3.

---

## 1. Authentication Flow Mapping

### 1.1 The convergence point

Every flow that authenticates a **human** and issues a real user
session ends at the same function:

```
app/services/auth_service.py :: generate_tokens(db, user, auth_method, idp_org_id=None)
  -> build_user_claims(db, user, auth_method, idp_org_id)   # assembles the JWT payload
  -> create_access_token(payload)                           # app/core/jwt.py
  -> create_refresh_token(payload)                           # app/core/jwt.py
  -> writes RefreshToken row (family_id, expires_at)
  -> writes user.last_login_at, user.authentication_method   # PR11.1
```

Confirmed call sites (`grep -rn "generate_tokens("`):

| # | File | Line context | `auth_method` |
|---|---|---|---|
| 1 | `app/api/routes_auth.py:159` | password login | `"password"` |
| 2 | `app/api/routes_oauth.py:70` | 3rd-party OAuth, existing linked user | `"oauth"` |
| 3 | `app/api/routes_oauth.py:81` | 3rd-party OAuth, new user | `"oauth"` |
| 4 | `app/api/routes_oauth.py:163` | OAuth account-link confirmation | `"oauth"` or `"sso"` |
| 5 | `app/api/routes_sso.py:111` | Enterprise SSO/OIDC, existing linked user | `"sso"` |
| 6 | `app/api/routes_sso.py:128` | Enterprise SSO/OIDC, new user (JIT) | `"sso"` |
| 7 | `app/api/routes_license.py:42` | License-key (desktop client) login | `"license"` |

**This is the single best insertion point for MFA enforcement.** A
gate placed between "identity resolved" and `generate_tokens()` in
each of these seven call sites — or, more centrally, a single check
added at the top of `generate_tokens()` itself, given a way to signal
"an MFA challenge is still pending" back to each caller — covers every
human login path in one place, by construction, the same way PR11.1's
`last_login_at`/`authentication_method` writes already do (that PR's
own docstring: "hooking here keeps every flow in sync by construction
rather than repeating the write at each of the seven call sites").

**Not covered by this choke point, deliberately:**
- `/auth/refresh` (`routes_auth.py:170` → `auth_service.rotate_refresh_token`)
  calls `build_user_claims` **directly**, not `generate_tokens` — a
  token refresh continues an existing session and correctly does not
  re-trigger MFA (an already-completed second factor shouldn't be
  re-asked every 15 minutes as the access token rotates).
- `POST /oauth/token` (`routes_oauth_token.py:19`, client_credentials
  grant for service accounts) never touches `generate_tokens` or
  `build_user_claims` at all — it calls
  `create_service_access_token` directly, a deliberately separate,
  smaller code path (per that function's own docstring) because a
  service token must never carry `sub`/`email`. **MFA correctly does
  not apply here** — there is no human to challenge.

### 1.2 Password login

`POST /auth/login` (`routes_auth.py:134-166`):

1. `sso_discovery_service.find_enforced_org_for_email(db, email)` — if
   the email's domain belongs to an org with `enforced=True` SSO, the
   request is rejected with `403 {"reason": "sso_required", ...}`
   **before any password is checked at all**.
2. `auth_service.authenticate_user(db, email, password)` — looks up
   the user, checks `status == "active"`, checks a password hash
   exists (rejects OAuth-only accounts), verifies via
   `passlib`/bcrypt. Emits `LOGIN_SUCCESS`/`LOGIN_FAILURE` audit events
   on every path (PR9).
3. `generate_tokens(db, user, auth_method="password")`.

### 1.3 OAuth login (Google/GitHub/Microsoft — 3 built-in providers)

`GET/POST /auth/{provider}/callback` → shared
`_complete_oauth_flow()` (`routes_oauth.py:40-82`):

1. Exchange the authorization code for the provider's userinfo
   (`oauth_service.exchange_code_for_userinfo`).
2. Same SSO-enforcement check as password login, applied to the
   **email the provider vouches for** — checked explicitly so a member
   of an SSO-enforcing org can't bypass enforcement by using Google
   instead of password login, even with an already-linked identity
   (`routes_oauth.py:50-66`).
3. Three-way resolution: already-linked identity → log in; email
   matches an unlinked account → require password confirmation via
   `POST /auth/link/confirm` (never silently linked); neither → create
   a new account.
4. `generate_tokens(..., auth_method="oauth")`.

### 1.4 Enterprise SSO login (per-org OIDC)

`GET /auth/sso/{org_slug}/login` → `GET/POST /auth/sso/{org_slug}/callback`
→ shared `_complete_sso_flow()` (`routes_sso.py:83-129`):

1. `/login` builds a PKCE (S256) + nonce-protected authorize URL
   against that org's registered OIDC provider
   (`OrganizationSSOConfig`), signs a short-lived `sso_state` JWT
   carrying `organization_id`/`organization_sso_config_id`/
   `code_verifier`/`nonce`.
2. `/callback` validates the state token, exchanges the code for an
   id_token, verifies it against the config's cached JWKS
   (`org_oidc_service.exchange_code_for_id_token_claims`).
3. Same three-way resolution as OAuth, scoped by
   `organization_sso_config_id` (prevents a `sub` collision across two
   different orgs' IdPs resolving to the wrong account) — plus JIT
   membership provisioning (`org_service.jit_provision_membership`) on
   both the linked-user and new-user paths.
4. `generate_tokens(..., auth_method="sso", idp_org_id=org.id)`.

This is the most mature auth path in the codebase — PKCE, per-login
nonce, RS256/ES256-only signing-algorithm allowlist, SSRF protection
on the issuer host (rejects loopback/link-local/cloud-metadata
ranges), secret encrypted at rest (Fernet), secret never returned by
any API response. See §4 for what it does *not* have (SAML, cert
rotation, SCIM — all confirmed absent).

### 1.5 License / API authentication (desktop client)

`POST /license/validate` (`routes_license.py:29-65`):

1. `license_service.validate_and_consume(db, key, email, platform)` —
   key lookup + usage/expiry check. **No SSO-enforcement check at
   all** — see §6, risk R3.
2. `license_service.get_or_create_user_for_email` — creates a
   password-less user if none exists yet for that email
   (`license_service.py:55-65`).
3. `generate_tokens(..., auth_method="license")`.

### 1.6 Service account authentication (machine identity)

`POST /oauth/token` (`routes_oauth_token.py`, RFC 6749 §4.4
client_credentials grant):

1. `client_id`/`client_secret` via HTTP Basic or form body.
2. `oauth_client_service.verify_client_credentials` — SHA-256 hash
   comparison, `status == "active"`, expiry check.
3. `create_service_access_token({org_id, client_id, scopes,
   auth_method: "client_credentials"}, ...)` — a structurally distinct
   token shape with no `sub`/`email`, explicitly rejected by
   `get_current_user` if presented against any user-identity route
   (`app/rbac.py:34-36`).

**MFA is out of scope for this flow by design** — there is no human
in this exchange to challenge.

### 1.7 Token refresh

`POST /auth/refresh` (`routes_auth.py:170-196`) →
`auth_service.rotate_refresh_token` (`auth_service.py:194-263`):

1. Presented refresh token (request body, falling back to the
   `omnibioai_session` HttpOnly cookie) is looked up by exact string
   match in `RefreshToken`.
2. **Reuse detection**: if the presented token was already rotated
   once (`rotated_at is not None`), the entire token *family*
   (`family_id`) is revoked — treats replay as compromise, forces the
   whole session tree back to login.
3. Fresh claims are rebuilt from the **current** database state via
   `build_user_claims` (not replayed from the old token's stale
   payload) — so a role/permission change takes effect on next
   refresh, not just next login.
4. A new access + refresh token pair is issued, the old refresh row
   marked `revoked=True, rotated_at=now()`.

**Where identity is loaded / claims assembled / permissions attached**
(`auth_service.py:47-106`, `build_user_claims`) — the single source of
truth for JWT payload shape, shared by every login flow above *and*
by refresh:

```python
{
  "sub": str(user.id), "email": user.email,
  "roles": [...], "permissions": sorted({...}),   # baked in at issuance, not re-fetched per-request
  "org_id": ..., "org_role": [...],                # resolved primary membership
  "auth_method": ..., "idp_org_id": ...,
  "token_version": 2,
}
```

Every downstream permission check (`app/rbac.py::get_current_user` →
`require_permission`/`require_org_permission_or_platform_admin`)
reads these claims directly off the decoded token — **no per-request
database re-fetch of permissions**. This matters for MFA design: an
`mfa_verified` claim added to this payload would be honored
automatically by every existing permission check without any changes
to `rbac.py` itself.

### 1.8 Where sessions are tracked

There is **no dedicated `sessions` table**. The closest equivalent is:

- **`refresh_tokens`** (`app/db/models.py:8-26`) — one row per issued
  refresh token, with `family_id` (all tokens descended from one login
  share it) and `rotated_at` (reuse-detection). This is the closest
  thing to a session record, but has no device/IP/user-agent metadata,
  and **no route anywhere in the codebase queries it directly** (grep
  confirms zero `RefreshToken` references outside `auth_service.py`
  and its own model file) — there is no "list my active sessions" or
  "revoke this device" endpoint today. This matches
  `navigation.ts`'s `sessions` nav item still being `functional: false`
  in the Admin Console.
- **Redis blacklist** (`app/core/token_revocation.py`) — access-token
  `jti` blacklist, written on logout, checked by every
  `get_current_user` call via `assert_token_usable`. Fails open if
  Redis is unreachable (deliberate, documented tradeoff — a Redis
  outage must not 500 every authenticated request).
- **`revoked_tokens` table** (`RevokedToken`, `token_jti` unique) — a
  persistent backing store for the same blacklist concept, also
  checked by `assert_token_usable`.

### 1.9 Architecture diagram

```
                     ┌─────────────────────────────────────────┐
                     │         Identity resolution              │
                     │  (per-flow: password / OAuth / SSO /     │
                     │   license — see §1.2–§1.5)                │
                     └───────────────────┬───────────────────────┘
                                         │  user (or 403 sso_required)
                                         ▼
                     ┌─────────────────────────────────────────┐
                     │   ★ generate_tokens(db, user, auth_method) ★
                     │   auth_service.py:126  -- THE ONE CHOKE   │
                     │   POINT for every human login             │
                     │                                             │
                     │   <-- MFA gate belongs here -->            │
                     └───────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                     ▼
        build_user_claims()      user.last_login_at /   RefreshToken row
        (JWT payload: roles,     .authentication_method  (family_id,
         permissions, org_id,     written (PR11.1)         rotated_at)
         auth_method baked in)
                    │
                    ▼
        create_access_token() / create_refresh_token()
        (app/core/jwt.py -- RS256 or HS256, 15min / 7day TTL)
                    │
                    ▼
        ──────────────────────────────────────────────
         Every downstream request:
         rbac.py::get_current_user
           -> decode_token()               (signature + exp)
           -> assert_token_usable()        (blacklist / revoked_tokens / user.status)
           -> require_permission(x) / require_org_permission_or_platform_admin(x)
              reads roles/permissions straight off the decoded claims,
              no per-request DB re-fetch
        ──────────────────────────────────────────────
                    │
                    ▼
        omnibioai-iam-client / omnibioai-api-gateway
        (pure downstream consumers of the same JWT --
         no MFA/session concept, none needed: an mfa_verified
         claim added above is honored automatically, everywhere,
         with zero changes to either)
```

---

## 2. Current User Security Model

Verified directly against `app/db/models.py:43-77` (`User`) and a
full-text grep — **do not assume from naming, verify from source**,
per this PR's own instruction:

| Capability | Exists? | Evidence |
|---|---|---|
| MFA enabled flag | **No** | Zero columns on `User`; zero grep hits for `mfa` anywhere in `app/` |
| MFA method | **No** | Same |
| TOTP secret storage | **No** | Same; zero hits for `totp` |
| WebAuthn credentials | **No** | Zero hits for `webauthn`/`fido` |
| Recovery codes | **No** | Zero hits for `recovery_code` |
| Backup codes | **No** | Zero hits for `backup_code` |
| Login history | **Partial** | `AuditEvent` rows (`LOGIN_SUCCESS`/`LOGIN_FAILURE`, PR9) exist per-attempt, but there is no dedicated `login_history` table and no UI reads them per-user today (`GET /platform/audit-events`, PR11.4b, is the only retrieval path, filterable by `actor_user_id`) |
| Failed login tracking | **Partial, write-only** | `LOGIN_FAILURE` events are logged (`auth_service.py:12-18`) but **nothing counts or consumes them** — no threshold, no counter column on `User` |
| Account lockout | **No** | No `locked_until`/`failed_login_count` column; no lockout logic anywhere |
| Password policy | **No** | `LoginRequest.password: str` (`schemas/auth.py`) has no `min_length`/complexity validator; `hash_password` (`core/security.py`) is a bare bcrypt wrapper with zero policy enforcement above it |
| Session management (list/revoke) | **No** | See §1.8 — `refresh_tokens` exists as data but has no query surface |

`User`'s actual columns, exhaustively (`app/db/models.py:43-77`):
`id, email, hashed_password, status, created_at, status_changed_at,
status_changed_reason, status_changed_by_user_id, last_login_at,
authentication_method` (the last two, PR11.1) — plus the
`roles` relationship. Nothing else.

---

## 3. Organization Security Policy Model

Checked `Organization` (`app/db/models.py:220-240`),
`OrganizationConfig` (`app/db/models.py:289-301`), and a targeted
grep for `require_mfa|enforce_mfa|session_timeout|password_polic|
ip_restrict|domain_restrict`:

| Capability | Exists? | Evidence |
|---|---|---|
| `require_mfa` / `enforce_mfa` | **No** | Zero hits, no column on any org-related model |
| Session timeout | **No** | Zero hits for `session_timeout`; access tokens are a fixed 15-minute TTL platform-wide (`app/core/jwt.py:25`), refresh tokens a fixed 7-day TTL (`auth_service.py:9`) — neither is configurable per org |
| Password requirements | **No** | See §2 — no policy exists at any level, org or global |
| Allowed authentication methods | **Partial, SSO-only** | `OrganizationSSOConfig.enforced` (bool) is the **only** real, enforced org-level security toggle in the entire codebase — "require SSO login," nothing broader. Guarded by a self-lockout check (`org_sso_service.set_enforced`'s lockout guard: can't turn on until the org has ≥1 completed SSO login) and a global-admin break-glass override (`set_sso_override`/`clear_sso_override`, PR11.4c-audited) |
| IP restrictions | **No** | Zero hits; only middleware in `app/main.py` is `CORSMiddleware` — no IP allow-listing, no request throttling of any kind |
| Domain restrictions | **Self-declared only, unverified** | `OrganizationSSOConfig.allowed_domains` (JSON list) exists and is used for SSO-discovery domain routing (`sso_discovery_service.py`), but it is **admin-typed, with no DNS-TXT or other ownership proof** — an org admin can claim any domain string with no verification step. This is a distinct, already-known gap (domain verification), not part of PR11.5's MFA scope, but adjacent enough to note here since any future "organization security policy" UI will likely surface both together. |

**Existing routes/permissions for this one policy field**
(`app/api/routes_org_sso.py`, all pre-existing, unmodified by this
discovery): `POST/GET/PATCH/DELETE /orgs/{org_id}/sso` (permission
`manage_sso`, org-scoped), `POST/DELETE /orgs/{org_id}/sso/override`
(permission `override_sso_enforcement`, global-scoped, deliberately
separate so it works even if the org's own admin is locked out).

**No general "organization security settings" object exists.** If
PR11.5 adds `require_mfa` as an organization-level policy, it needs a
net-new field — there is nothing to extend. The natural home, by
precedent, would be either a new column on `Organization` directly
(mirroring how `status`/`status_changed_*` already live there) or a
new small table mirroring `OrganizationSSOConfig`'s own shape
(`enforced`-style boolean + audit columns) — see §7, PR11.5.5.

---

## 4. Admin Console Readiness (`omnibioai-control-center`)

### 4.1 Already reusable, confirmed present

- **Design system** (`frontend/cc-ui/src/components/ui/`): `Card`,
  `SectionHeader`, `LoadingState`, `ErrorState`, `EmptyState`,
  `ActionToolbar`, `DataTable`, `Button`, `PageContainer` — the exact
  same set every PR11.x page (`SSOSettingsPage`, `ServiceAccountsPage`,
  `AuditLogsPage`) has already used. No new primitives needed for a
  first MFA/security-settings UI pass.
- **Navigation taxonomy already anticipates this work**
  (`frontend/cc-ui/src/navigation.ts`): the `security` section already
  exists with `iam` (SSO, functional), `audit-logs` (functional),
  `api-keys` (functional), and **`sessions` still `functional: false`**
  — a reserved, unclaimed nav slot. There is currently **no dedicated
  "Security" or "MFA" nav entry at all** — one would need to be added
  (not yet reserved, unlike `sessions`).
- **`SecuritySummaryCard.tsx`** (`components/organizations/`, PR11.2)
  already renders, verbatim: `"MFA: Not configured"` and a footer note
  — *"MFA enforcement and domain verification are not implemented in
  this platform yet — these are explicit placeholders, not live
  status."* This was written and verified in an earlier discovery pass
  specifically because this exact gap was already confirmed once. It
  is the natural place to wire real data into once MFA/domain-policy
  fields exist, requiring no new component, just live data instead of
  the hardcoded string.
- **Permission-gating pattern** (`auth.ts`): `hasAdminAccess()`,
  `hasPlatformAdminAccess()`, `hasOrganizationsAccess()`,
  `hasPermission(name)` (generic, claim-based) — every PR11.x nav item
  gates through one of these, reused verbatim rather than inventing a
  new mechanism each time. An MFA/security-settings page would follow
  the same pattern; no new gating primitive needed, only a decision
  about *which* existing permission (or a new one — see §5) governs
  it.
- **Backend proxy pattern**
  (`backend/src/control_center/api/routes_*_proxy.py`, six existing
  files: auth, org, user, role, team, org_sso, service_accounts,
  audit) — pure relay, forward `Authorization` header, zero local
  authorization decisions. Any new MFA-related endpoint in
  `omnibioai-auth` would need exactly one new proxy file following
  this identical shape.

### 4.2 What does not exist yet

- No MFA enrollment/challenge UI (nothing to build against yet — see
  §5/§7).
- No `SecurityPage.tsx` or equivalent — `SecuritySummaryCard` is a
  read-only summary tile embedded in `OrganizationDetailPage`, not a
  standalone page.
- No `sessions` page (nav slot reserved, unbuilt).
- No user-detail security section on `UserDetailPage.tsx` beyond the
  existing enable/disable status action (`UserStatusAction.tsx`) — no
  "reset MFA" admin action exists because there is nothing to reset.

---

## 5. Enterprise MFA Requirements Gap Analysis

### User MFA

| Requirement | Status |
|---|---|
| TOTP enrollment | Missing — no service, no schema |
| QR provisioning | Missing |
| Recovery codes | Missing |
| MFA challenge during login | Missing — no insertion point exists in any of the 7 `generate_tokens` call sites today |
| Disable/reset MFA (self-service) | Missing |
| Admin reset capability | Missing — no analog exists even for password reset today (confirmed: no `POST /platform/users/{id}/reset-password` or similar; the only admin action on a user is the status PATCH, PR11.1) |

### Enterprise MFA

| Requirement | Status |
|---|---|
| Organization requires MFA | Missing — no field, see §3 |
| Admin cannot disable enforced MFA | N/A yet — depends on the above; the SSO-enforcement precedent (`enforced` field + lockout guard + separate break-glass permission) is the direct template to follow |
| Break-glass recovery | Missing, but a **direct, already-audited template exists**: `org_sso_service.set_sso_override`/`clear_sso_override`, gated by the global `override_sso_enforcement` permission (deliberately distinct from `manage_sso`) and audited (`SSO_OVERRIDE_CREATED`/`SSO_OVERRIDE_REMOVED`, PR11.4c). An MFA break-glass mechanism should copy this shape, not invent a new one. |
| Audit logging | The framework is ready (`audit_service.log_event`, `AuditEventType`, `GET /platform/audit-events`) but has **zero MFA-related event types** today — new constants would be needed (e.g. `MFA_ENROLLED`, `MFA_CHALLENGE_FAILED`, `MFA_RESET_BY_ADMIN`), following the exact pattern every PR11.4x event type already established |

### Advanced (future, explicitly out of scope for PR11.5)

WebAuthn/FIDO2, hardware keys, SAML MFA claims, conditional access —
all confirmed absent (§4 of the prior `identity-findings` pass;
re-confirmed here by the same grep sweep that found zero MFA hits of
any kind). Not addressed by this discovery's recommended roadmap
(§7); noted only so a future phase has a named target.

---

## 6. Security Risk Assessment

| # | Risk | Rank | Evidence |
|---|---|---|---|
| R1 | **Password-only authentication, zero second factor, for every non-SSO login path.** For a platform positioning itself for enterprise customers, this is the single largest gap found. | **Critical** | §2, §5 — confirmed by exhaustive grep, not inferred |
| R2 | **No brute-force protection anywhere** — no rate limiting (no `slowapi`/throttle middleware found, `app/main.py`'s only middleware is CORS), no account lockout, no failed-login threshold. `LOGIN_FAILURE` events are logged but never consumed. An attacker can attempt unlimited password guesses against `/auth/login` today, bounded only by bcrypt's inherent per-attempt cost. | **Critical** | §2, `app/main.py` middleware list, `auth_service.py:12-18` |
| R3 | **License-key login (`/license/validate`) never checks SSO enforcement.** A member of an org with `enforced=True` SSO can still obtain a real access/refresh token via a valid license key — the same enforcement check present in both the password (`routes_auth.py:142`) and OAuth (`routes_oauth.py:56`) flows is simply absent from `routes_license.py`. Newly discovered in this pass, not previously flagged. | **High** | `routes_license.py:29-65` (no `find_enforced_org_for_email` call anywhere in the file, confirmed by grep) |
| R4 | **No session visibility or revocation for end users.** A user who suspects their account is compromised has no way to see "which devices/sessions are logged in" or revoke one selectively — only a full logout (which only revokes the one presented refresh token) or an admin-initiated account suspend. | **High** | §1.8 |
| R5 | **No account lockout after repeated failed logins** (see R2) means a compromised/guessed password is immediately usable with no friction, and there is no automatic signal to the account owner or an admin. | **High** | Same evidence as R2 |
| R6 | **No password policy** — any non-empty string is accepted, including single-character passwords, at both registration and any future password-change surface. | **Medium** | `schemas/auth.py`, `core/security.py` |
| R7 | **Domain "verification" is self-declared** — `allowed_domains` has no DNS-TXT or other ownership proof, so SSO-discovery domain routing trusts an admin-typed string. Adjacent to, not part of, MFA scope. | **Medium** | §3 |
| R8 | **No MFA-specific audit events** (moot until MFA exists, but worth designing in from the start rather than retrofitting — every other PR11.4x capability added its audit coverage in the same PR or a fast-follow, and this pattern should continue). | **Medium** (becomes **High** once MFA ships without it) | §5 |
| R9 | **Fixed, non-configurable token TTLs** (15min access / 7day refresh, platform-wide) — an enterprise customer may reasonably expect a configurable session/token lifetime as part of "security settings," which doesn't exist as a concept anywhere yet. | **Low** | `app/core/jwt.py:25,36`, `auth_service.py:9` |

---

## 7. Recommended PR Breakdown

Sized against what actually exists today (§1–§4), not the brief's
example list verbatim — adjusted where discovery changes the shape.

**PR11.5.1 — MFA database foundation**
- New columns on `User`: `mfa_enabled` (bool), `mfa_method`
  (nullable string, e.g. `"totp"`), `totp_secret_encrypted` (reuse the
  existing Fernet `crypto.encrypt`/`decrypt` helpers already used for
  `OrganizationSSOConfig.client_secret_encrypted` and
  `OrganizationConfig.llm_api_key_encrypted` — do not invent a second
  encryption scheme).
- New table for recovery/backup codes (hashed, single-use, mirroring
  `ApiKey`/`OAuthClient`'s existing "store a hash, never the plaintext
  after issuance" convention).
- Migration only — no route changes, no login-flow changes. Smallest
  possible first PR, matching how PR11.1b (persisted `last_login_at`)
  was deliberately kept small and separate from its UI-facing sibling.

**PR11.5.2 — TOTP enrollment**
- QR code generation (standard `otpauth://` URI), secret storage
  (write path for PR11.5.1's columns), verification endpoint
  (`POST /users/me/mfa/enroll`-shaped — exact path TBD at
  implementation time).
- New `AuditEventType.MFA_ENROLLED` (and a failed-verification
  counterpart), following the PR11.4b/PR11.4c pattern exactly: audit
  call inside the service function, never the route handler.

**PR11.5.3 — MFA login challenge**
- The core change: a gate at the `generate_tokens()` choke point
  (§1.1) — likely a new intermediate state ("credentials verified,
  MFA pending") rather than a token, since issuing any token before
  the second factor is confirmed would defeat the purpose.
- Must be threaded through **all seven call sites** (§1.1's table),
  not just password login — OAuth/SSO/license logins for an
  MFA-enabled user need the same challenge, unless a deliberate
  decision is made to scope MFA to password-login only for a first
  release (a real design choice to make explicitly, not default into
  silently).
- Token issuance changes: whatever new token/session-state shape
  represents "awaiting second factor" needs its own short TTL and its
  own revocation story, mirroring the existing `oauth_state`/`sso_state`
  short-lived signed-token pattern (`app/core/jwt.py`) rather than a
  new mechanism.

**PR11.5.4 — Recovery and admin reset**
- Recovery-code consumption flow (single-use, invalidate-after-use,
  same convention as API-key/OAuth-client secrets: shown once, hashed
  at rest).
- Admin-reset-a-user's-MFA capability — the direct analog to
  `set_user_status`'s existing `manage_all_orgs`-gated pattern
  (`routes_platform_users.py`), reusing that same permission rather
  than inventing a narrower one, consistent with how every other
  PR11.x area reused an existing permission instead of adding one
  (§5's own finding: zero new permissions needed anywhere so far).

**PR11.5.5 — Organization MFA Policy**
- New `require_mfa`/`enforced`-shaped field, most naturally on
  `Organization` directly or a small sibling table — copy
  `OrganizationSSOConfig`'s exact shape: a boolean, a lockout guard
  (can't require MFA org-wide until enrollment is actually possible/
  verified for members — same reasoning as SSO's "can't enforce until
  one completed SSO login" guard), and a break-glass override reusing
  the **existing** `override_sso_enforcement`-style pattern (a new,
  analogous global permission, e.g. `override_mfa_enforcement`, kept
  deliberately separate from org-scoped `manage_*` permissions for the
  same reason SSO's override is separate today).
- Audit coverage from day one:
  `MFA_POLICY_CHANGED`/`MFA_OVERRIDE_CREATED`/`MFA_OVERRIDE_REMOVED`,
  not retrofitted later (see R8).

**PR11.5.6 — Admin Console Security UI**
- New `SecurityPage.tsx` (or extend `SecuritySummaryCard.tsx`'s
  existing home) — reuses the existing design system and permission-
  gating pattern entirely (§4.1); no new frontend primitives needed.
- New backend proxy file (`routes_mfa_proxy.py` or folded into an
  existing one, TBD at implementation time) following the six existing
  proxy files' identical pure-relay shape.
- Surfaces: user MFA status (self-service enrollment entry point),
  organization MFA policy toggle (mirroring `SSOSettingsPage.tsx`'s
  enforcement-toggle UX and its "explain the backend guard before
  letting the admin flip it on" convention), admin reset action
  (mirroring `UserStatusAction.tsx`'s confirm-before-destructive-action
  shape).

**Explicitly not in this roadmap** (§5 "Advanced" / out of scope):
WebAuthn/FIDO2, hardware keys, SAML MFA claims, conditional access,
domain-verification DNS-TXT workflow (R7 — a separate, adjacent
project, already named in the prior discovery pass as PR11.6).

---

## 8. Verification Method

Every finding above was produced by direct source inspection in this
session:

- Full-text `grep -rniE` sweeps across `omnibioai-auth/app/` for MFA/
  session/lockout/rate-limit terminology (all returned zero hits
  unless explicitly noted otherwise above).
- Direct reads of every route file touching authentication
  (`routes_auth.py`, `routes_oauth.py`, `routes_sso.py`,
  `routes_license.py`, `routes_oauth_token.py`), `auth_service.py`
  in full, `app/core/jwt.py` in full, `app/core/token_revocation.py`
  in full, `app/rbac.py` (permission-attachment mechanics).
- Direct read of `app/db/models.py`'s `User`, `RefreshToken`,
  `RevokedToken`, `Organization`, `OrganizationConfig`,
  `OrganizationMembership` definitions in full.
- Direct read of `app/core/security.py` (password hashing) and
  `app/schemas/auth.py` (request validation).
- `omnibioai-control-center/frontend/cc-ui/src/navigation.ts`,
  `components/organizations/SecuritySummaryCard.tsx`, and the
  `components/ui/` design-system index, read directly.
- `omnibioai-iam-client`'s `iam_client/*.py` and
  `omnibioai-api-gateway`'s `app/services/iam_client.py`/
  `app/middleware/auth.py`, grepped for any MFA/session concept
  (zero hits in either) — confirming both are pure JWT-claim
  consumers with no role in enforcement placement.

No code was changed, no migration was written, and no endpoint was
added in the course of this discovery, per this PR's own instructions.

---

## 9. Relationship to the prior discovery pass

An earlier, uncommitted discovery document
(`docs/admin-console-pr11-identity-findings.md`, written before
PR11.1–PR11.4c shipped) covered adjacent ground and reached
compatible conclusions on the points that haven't changed (SSO
maturity, iam-client/api-gateway non-integration into enforcement,
zero MFA scaffolding, no org-level security-policy bundle). Several of
its "missing" findings are **now resolved** by work that has since
merged, and this document reflects the current state rather than
repeating stale claims:

| Prior finding | Current state |
|---|---|
| "No audit trail for user status changes or API-key/OAuth-client lifecycle" | **Resolved** — PR11.4b added `USER_ENABLED`/`USER_DISABLED`/`API_KEY_CREATED`/`API_KEY_REVOKED`/`OAUTH_CLIENT_CREATED`/`OAUTH_CLIENT_REVOKED`; PR11.4c added SSO break-glass override auditing |
| "`last_login`/persisted `authentication_method` missing" | **Resolved** — PR11.1, both columns now exist and are written at every `generate_tokens` call (§1.1, §2) |
| "User filter by org/status/role missing" | **Resolved** — PR11.1 |
| "SSO Management UI missing (configure/edit form)" | **Resolved** — PR11.3 |
| "Service Accounts UI missing" | **Resolved** — PR11.4 |
| "No audit retrieval API" | **Resolved** — PR11.4b, `GET /platform/audit-events` |
| "SSO-enforcement-on-password-login unconfirmed" | **Resolved/confirmed** — checked directly this pass, `routes_auth.py:142`; also confirmed present on OAuth (`routes_oauth.py:56`) and confirmed **absent** on license login (new finding, R3) |
| MFA, org security-policy bundle, domain verification | **Unchanged — still entirely missing**, re-confirmed by an independent grep sweep in this pass |
