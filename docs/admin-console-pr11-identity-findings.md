# PR11 — Enterprise Identity Management: Architecture Discovery

Status: **Discovery only — no code changed, no PR opened.** Every claim below was verified against actual source in this session (five parallel research passes over `omnibioai-auth`, `omnibioai-iam-client`, `omnibioai-api-gateway`, plus a direct read of `omnibioai-control-center/frontend/cc-ui`), not assumed from naming or prior memory. File:line citations are given throughout so every claim is independently re-checkable.

Repos covered: `omnibioai-control-center` (admin console UI + proxy backend), `omnibioai-auth` (identity service, source of truth), `omnibioai-iam-client`, `omnibioai-api-gateway`.

---

## 1. Current Architecture

**Three layers, one direction of trust:**

- **`omnibioai-auth`** is the sole source of truth for identity, orgs, roles, SSO, API keys/OAuth clients. It issues JWTs carrying a `permissions` claim baked in at login.
- **`omnibioai-control-center`** never makes its own authorization decisions about identity data — every `/platform/*`, `/orgs/*`, `/users/*`, `/roles/*`, `/teams/*` route in control-center is a byte-relaying proxy (`routes_org_proxy.py`, `routes_user_proxy.py`, `routes_role_proxy.py`, `routes_team_proxy.py`) that forwards the caller's `Authorization` header as-is and trusts omnibioai-auth's own 401/403. This is stated explicitly in each proxy file's docstring. The only routes where control-center enforces its own permission are its native ops surfaces (`platform.manage_infra`, `platform.manage_cron`, `platform.manage_content` — `main.py:104-109`) and PR10's dashboard aggregator.
- **`omnibioai-iam-client`** is a standalone library intended for *other* services to consume (README names api-gateway, security-sdk, control-center as intended consumers) but **control-center does not actually import it** — confirmed by grep, zero Python imports outside build/reporting scripts. Control-center instead re-implements its own local JWT decode + Redis jti-blacklist check (`backend/src/control_center/core/jwt_verify.py`), a deliberate choice documented in that file (`jwt_verify.py:11-19`) after evaluating iam-client and finding it unsuitable ("not imported by any live service today"). `omnibioai-api-gateway` also does not call it for API-key/OAuth-client checks — one comment referencing the concept, no actual integration.

**Two permission-checking mechanisms, both real, serving different scopes:**
- `require_permission(x)` (`app/rbac.py:49-55` in auth; near-identical reimplementation in control-center's `core/auth.py:8-51`) — flat JWT-claim membership check, for global/platform-wide permissions (`manage_all_orgs`, `manage_roles`, `platform.manage_infra`, …).
- `require_org_permission_or_platform_admin(x)` (`app/rbac.py:189-205`, built on `get_org_membership_or_platform_admin`, `rbac.py:155-186`) — a **live DB query** against `OrganizationMembership.roles[].permissions` for the specific `org_id` in the URL, with a fail-closed, **never-persisted** synthetic membership that lets a `manage_all_orgs` holder act as an org_admin on any org without ever appearing in that org's real member list. This is the tenant-isolation mechanism protecting every org-scoped route across users, teams, roles, API keys, OAuth clients, and SSO — a dedicated regression suite (`tests/test_idor_org_scoping.py`) locks this in for team/api-key/oauth-client lookups specifically.

**Frontend** (`omnibioai-control-center/frontend/cc-ui`): PR9's `AdminApp` shell (sectioned sidebar nav, top bar, design-system primitives) + PR10's dashboard widget family. Critically, **`navigation.ts` already reserves nav slots for almost every PR11 sub-scope** (`Teams`, `Roles & Permissions`, `IAM`, `Audit Logs`, `Sessions`, `API Keys` — all `functional: false` today, i.e. rendered as `<ComingSoon>`), and **User Management and Organization Management already have real, working pages** — this is not a greenfield build. See §6.

---

## 2. Existing APIs (by capability area)

### 2.1 User Management (`omnibioai-auth`)

| Capability | Endpoint | Permission | File:line |
|---|---|---|---|
| List/search users (platform-wide) | `GET /platform/users` — params: `page`, `page_size`, `search` (email substring), `sort_by` (email/created_at/status), `sort_order` | `manage_all_orgs` | `routes_platform_users.py:28-42` |
| User detail | `GET /platform/users/{id}` → id, email, status, created_at, global_roles, memberships[] (org+roles+status+joined_at), status_changed_* | `manage_all_orgs` | `routes_platform_users.py:45-54` |
| Disable/enable (single status endpoint, both directions) | `PATCH /platform/users/{id}` body `{status, reason}` | `manage_all_orgs` | `routes_platform_users.py:57-77` |
| Richer identity view (permissions, not just role names) | `GET /platform/users/{id}/identity` | `manage_all_orgs` | `routes_identity.py:111-123` |
| Org members (unfiltered) | `GET /orgs/{org_id}/members` and `GET /organizations/{organization_id}/members` (richer, `?expand_permissions=`) | `manage_org` | `routes_orgs.py:110-117`, `routes_organization_roles.py:227-266` |
| Global role assignment | `GET/POST/DELETE /platform/users/{id}/roles` | `manage_all_orgs` | `routes_platform_roles.py:148-198` |
| Org role assignment | `GET/POST/DELETE /orgs/{org_id}/members/{id}/roles` (legacy) **and** `/organizations/{org_id}/members/{id}/roles` (PR7, parallel, same permission) | `manage_org` | `routes_orgs.py:201-274`, `routes_organization_roles.py:129-219` |

**Missing** (confirmed absent by direct grep/read, not inference):
- **`last_login`** — no column on `User`, zero references anywhere in `app/`.
- **Persisted `authentication_method`** — exists only as an ephemeral JWT claim computed at login (`auth_service.py:48-115`), never written to the `users` row. Cannot be filtered/displayed independent of a live session; a user with both password and SSO has no persisted "primary method."
- **Filter by organization, status, or role** on `GET /platform/users` — the endpoint's only filter is `search` (email substring). No `org_id`/`status`/`role` query params exist in the signature.
- **"What teams is user X in"** — no such endpoint exists; only the reverse (`GET /orgs/{org_id}/teams` → `member_user_ids` per team) exists.
- **Separate disable/enable action routes** — one generic status PATCH handles both directions; fine functionally, just note there's no `/disable`/`/enable` verb-shaped route if that's expected.
- **`app/api/routes_users.py`** exists in the tree but is a 0-line empty file, not registered in `main.py` — a dead stub, not a source of any capability.

### 2.2 Organization Management (`omnibioai-auth`)

| Capability | Endpoint | Permission | File:line |
|---|---|---|---|
| Platform-wide org list/detail | `GET /platform/orgs`, `GET /platform/orgs/{id}` — detail includes member/team/api_key/oauth_client/license summaries (counts), SSO summary, recent_activity | `manage_all_orgs` | `routes_platform_admin.py:28-54` |
| Self-service org CRUD | `POST/GET/PATCH /orgs`, `/orgs/{id}` | membership / `manage_org` | `routes_orgs.py:51-107` |
| Members + roles | see §2.1 | `manage_org` | — |
| Teams | `POST/GET /orgs/{org_id}/teams`, `PUT/DELETE .../teams/{id}/members|{id}` | `manage_teams` (list only needs active membership) | `routes_teams.py:24-72` |

**Organization model fields** (`app/db/models.py:208-228`): id, slug, name, **`plan`** (free string, default `"beta"`, **never validated against an enum anywhere** — unlike `status`, which is restricted to `{active, suspended}`), status, created_at, created_by_user_id, status_changed_*.

**Missing, explicitly confirmed by grep** (zero hits for `subscription`, `billing`, `usage`, `quota`, `security_setting`, `enforce_sso` as a general concept, `session_timeout`):
- **Subscription/plan**: only the unvalidated `plan` string. `billing.read`, `billing.manage`, `subscription.manage`, `usage.read` exist **only as reserved permission-registry entries** (`permission_names.py:308-350`) — each one's own description literally says "Reserved — not yet enforced by any route." No model, no service, no route.
- **Usage summary**: does not exist. The only "usage" in the schema is `LicenseKey.usage_count` (license activation counter), unrelated to org-level usage/quota.
- **General org-level security settings** (a bundle like "require MFA," "session timeout"): does not exist. The only real, enforced org-level policy toggle is `OrganizationSSOConfig.enforced` (require-SSO-login), which is SSO-specific, not a general security-policy object.

### 2.3 Enterprise SSO (`omnibioai-auth`) — the most mature area found

Full OIDC login flow (discovery → PKCE + nonce-protected authorize → signed-state callback → JWKS-verified id_token with RS256/ES256-only allowlist → 3-way account resolution) is implemented end-to-end and is genuinely enterprise-grade:

| Capability | Endpoint/mechanism | File:line |
|---|---|---|
| Configure OIDC provider (per org) | `POST/PATCH/GET/DELETE /orgs/{org_id}/sso` | `routes_org_sso.py:46-120`, permission `manage_sso` |
| Domain-based discovery (unauthenticated) | `GET /auth/sso/discover?email=` | `routes_sso.py:23-34` |
| Login initiation / callback | `GET /auth/sso/{slug}/login`, `GET`/`POST /auth/sso/{slug}/callback` | `routes_sso.py:38-150` |
| Enforce SSO-only login for an org | `OrganizationSSOConfig.enforced`, set via SSO config PATCH; enforced in the 3-provider OAuth callback path (`routes_oauth.py:56-66`); **lockout guard** blocks turning it on until one successful SSO login has occurred | `org_sso_service.py:198-234` |
| Break-glass override (unlock a locked-out org) | `POST/DELETE /orgs/{org_id}/sso/override`, global permission `override_sso_enforcement` (deliberately distinct from `manage_sso`) | `routes_org_sso.py:126-146` |
| JIT provisioning | New user auto-created on first successful SSO login, default `org_member` role, idempotent | `org_service.py:152-179`, `oauth_service.py:133-151` |

Security posture confirmed strong: PKCE S256, per-login OIDC nonce checked against id_token claim, signing-algorithm allowlist (RS256/ES256 only — blocks `alg=none`/HS*-confusion), issuer/audience validated against the discovery document at registration time, SSRF protection on the issuer host (rejects loopback/link-local/cloud-metadata ranges, `follow_redirects=False`), secret encrypted at rest (Fernet), secret never returned by any API response, cross-tenant `sub` collisions prevented by a DB unique constraint scoped to `organization_sso_config_id`.

**Missing, explicitly confirmed absent** (zero hits):
- **SAML** — zero occurrences anywhere in the repo. `provider_type` defaults to `"oidc"` and nothing else is ever written to it.
- **Certificate/secret rotation** — no first-class rotation concept; only way to "rotate" is `PATCH .../sso` with a new `client_secret`. No IdP-cert-rotation mechanism at all.
- **SCIM provisioning** — zero occurrences.
- One gap not fully verified in this pass: whether SSO enforcement (`find_enforced_org_for_email`) is checked on the **plain password login** route (`routes_auth.py`), not just the 3-provider consumer-OAuth callback — confirmed present on the latter, unconfirmed on the former. Worth a 10-minute follow-up grep before PR11.3 ships if "enforce SSO" is presented in the UI as blocking *all* login paths.

### 2.4 Service Accounts / API Keys (`omnibioai-auth`)

Two distinct, deliberately separate mechanisms — **"service account" in this codebase means `OAuthClient`**, not `ApiKey`:

| | `ApiKey` | `OAuthClient` (= "service account") |
|---|---|---|
| Purpose | Human-facing bearer secret, org-owned | Machine identity, `client_credentials` grant (RFC 6749 §4.4) |
| Create/list/revoke | `POST/GET/DELETE /orgs/{org_id}/api-keys[/{id}]`, permission `manage_api_keys` | `POST/GET/DELETE /orgs/{org_id}/oauth-clients[/{id}]`, permission `manage_oauth_clients` |
| Rotation | **Not supported** — revoke + recreate only, zero rotation code anywhere | **Not supported** — same |
| Secret storage | SHA-256 hash only; plaintext shown once at creation | SHA-256 hash only; same |
| Scope validation | Only checks scopes ⊆ caller's own permissions — **does not** validate scopes against the permission registry | Validates against both caller's permissions **and** the permission registry (`is_known_permission`) |
| Usage tracking | `last_used_at` column exists but **is never written anywhere** in application code (only touched by tests) | `last_used_at` **is** written, on every `client_credentials` token grant |
| Audit trail | **None** — no `audit_service`/`AuditEvent` call from create/revoke/use, in either file | **None** — same |
| Consumed by iam-client / api-gateway today? | No — zero references | No (one comment in api-gateway acknowledging the concept, no actual call) |

---

## 3. Missing Capabilities — Summary Table

| PR11 spec item | Status | What's needed |
|---|---|---|
| User search/filter by org/status/role | Partial (search by email only) | Backend: add query params to `GET /platform/users` |
| User filter by auth method; last login display | **Missing entirely** | Backend: new persisted column(s) on `User`, a way to write `last_login` at token-issue time, and a way to persist "primary" auth method |
| "What teams is user X in" | **Missing** | Backend: new endpoint or field |
| Org subscription status / usage summary | **Missing entirely** (only unenforced `plan` string + reserved permissions) | Backend: real billing/usage model — large, likely out of PR11 scope entirely |
| Org general security settings (bundle) | **Missing** (only SSO-`enforced` exists) | Backend: new concept, likely coupled to MFA work below |
| SAML | **Missing entirely** | Backend: new IdP protocol implementation — large |
| Cert/secret rotation (SSO) | **Missing** | Backend: new rotation flow |
| SCIM provisioning | **Missing entirely** | Backend: new protocol implementation — large |
| API key / OAuth client rotation | **Missing** | Backend: new endpoint, revoke-old-issue-new-preserving-identity semantics |
| API key / service account audit trail | **Missing** | Backend: wire existing `audit_service` into create/revoke/use paths |
| MFA (TOTP/WebAuthn/recovery codes/enforcement) | **Missing entirely, zero stub** | Backend: net-new — schema, login-flow second-factor step, enrollment/recovery endpoints — large, security-sensitive |
| Domain verification (DNS TXT proof of ownership) | **Missing entirely** — today `allowed_domains` is self-declared with no proof | Backend: net-new — DNS TXT challenge/verify workflow |

---

## 4. Security Review

**Real strengths already in place** (don't rebuild these — reuse them):
- SSO/OIDC implementation is genuinely enterprise-grade (§2.3) — PKCE, nonce, algorithm allowlist, SSRF protection, encrypted-at-rest secrets, self-lockout guard, break-glass override with a *separate* permission from ordinary SSO management.
- Tenant isolation (`get_org_membership_or_platform_admin`) is consistently applied across every org-scoped router, backed by a dedicated IDOR regression suite.
- Self-escalation guards on role-assignment endpoints prevent a caller from widening their own effective permissions.
- Secrets (SSO client secret, API keys, OAuth client secrets) are never returned once created and are hashed/encrypted appropriately.

**Real gaps worth flagging explicitly for an enterprise console:**
1. **No MFA of any kind** — for an identity service being built out to enterprise-console maturity, password-only auth with zero second-factor scaffolding is the single biggest gap found in this discovery. Also no account-lockout/brute-force-throttle on repeated failed logins (failures are logged via `audit_service` but nothing consumes those events to throttle).
2. **No audit trail for user status changes or API-key/OAuth-client lifecycle events.** `set_user_status` never calls `audit_service.log_event`, and `AuditEventType` has no `USER_STATUS_CHANGED` constant at all — contrast with role/org-membership mutations, which *are* audited. An admin-console "disable user" or "revoke API key" action today leaves no audit row. Given PR11's whole premise is giving admins more identity-management power, this is worth closing before or alongside PR11, not after.
3. **Domain "verification" is currently just a self-declared string** — `allowed_domains` has no DNS-TXT or other ownership proof. If PR11's SSO/domain UI is not carefully worded, an admin could reasonably believe an org's claimed domain has been verified when it hasn't been.
4. **Platform-admin access to any org is intentionally traceless** — the synthetic membership bypass is never persisted, so a platform admin managing another org's members/roles/teams leaves no row in `organization_memberships`. This is correct by design, but means any admin-console audit view for "who touched org X" needs to read `AuditEvent`, not membership history, and today most identity mutations aren't even written there (see #2).
5. **Two parallel role-management API surfaces** (legacy `/orgs/...` vs PR7 `/organizations/...`) exist side by side for org roles — same permission, functionally redundant, low risk. **Two parallel global-role-management surfaces** (`/users/{id}/roles` under `manage_roles` vs `/platform/users/{id}/roles` under `manage_all_orgs`) is a slightly sharper risk since they're gated by *different* permissions — a caller could have visibility into one and not the other. PR11's UI must pick one deliberately, not both.
6. **`Organization.plan` and `ApiKey` scopes are unvalidated** — `plan` against no enum, `ApiKey` create against no permission-registry check (unlike `OAuthClient`, which does validate). Low severity today since nothing reads `plan` programmatically, but worth tightening if PR11 adds a UI that lets an admin set `plan` freely.

---

## 5. Recommended PR Breakdown

The proposed sequence (PR11.1–PR11.6) is broadly right in spirit — UI-first for mature areas, backend-first for MFA/domain — but the discovery surfaced two things that change the shape:

1. **User Management and Organization Management UI already exist and are substantially built** (`UsersPage.tsx`, `UserDetailPage.tsx`, `OrganizationsPage.tsx`, `OrganizationDetailPage.tsx` — see §6). PR11.1/11.2 are **extensions of working pages**, not new builds — smaller scope than the original framing implied, but also **not fully unblocked**: the filter/last-login/auth-method asks require backend changes first (§2.1), so a pure-UI PR11.1 can only partially satisfy the brief.
2. **SSO Management UI is further along than expected** — `OrganizationDetailPage.tsx` already renders a read-only SSO summary (provider/issuer/status/enforced/override) sourced from `PlatformOrgDetailOut.sso`. What's missing is purely the **edit/configure** surface (a form wired to `POST/PATCH /orgs/{org_id}/sso`) — no new backend needed, since that API already exists and is solid (§2.3).

**Confirmed sequence with adjustments:**

| PR | Scope | Backend needed first? | Notes |
|---|---|---|---|
| **PR11.1** | User Management UI — extend `UsersPage`/`UserDetailPage` with org/status/role filters | Yes, small: query params on `GET /platform/users` | Ship with `last_login`/auth-method columns as explicit `null`/"Preview data" (PR10's established convention) rather than blocking on the larger backend addition |
| **PR11.1b** *(new, not in original sequence)* | Backend: persist `last_login` (write on token issue) + persisted primary `auth_method` on `User` | — | Small, additive migration; unblocks PR11.1's remaining two columns as a fast follow-up rather than gating PR11.1 entirely |
| **PR11.2** | Organization Management UI — standalone Teams page, standalone Roles & Permissions page (both currently only reachable via Org Detail; `navigation.ts` already reserves both nav slots) | No | Pure UI, existing APIs (`/orgs/{id}/teams`, `/orgs/{id}/roles`) suffice |
| **PR11.3** | SSO Management UI — turn the existing read-only SSO summary into a configure/edit form; **do not** build SAML/cert-rotation/SCIM UI (none of that backend exists) | No, for OIDC config. Confirm password-login enforcement gap (§2.3) first if the UI claims to "block all login" | Reuse existing summary component, add form calling existing PATCH |
| **PR11.4** | Service Accounts UI — list/create/revoke for both `ApiKey` and `OAuthClient` (present them as one "Service Accounts / API Keys" surface, matching the existing `OrganizationSummaryCard` counts already shown) | No for create/revoke. **Rotation UI must be dropped or backend added first** — rotation doesn't exist | Also wire the audit-trail gap (§4.2) before or alongside this PR, since this is exactly the surface an admin console makes it easy to abuse silently otherwise |
| **PR11.5** | MFA Backend + UI | **Yes — large, net-new.** Schema (TOTP secret, recovery codes, enrollment state), login-flow second-factor step, enrollment/recovery endpoints, then org-level "require MFA" policy | Recommend treating this as its own multi-PR phase (like SSO's original 5-PR rollout), not one PR |
| **PR11.6** | Domain Verification Backend + UI | **Yes — net-new.** DNS TXT challenge generation + verification job, status field transition out of today's inert `pending_verification` | Smaller than MFA but still real backend design work (challenge storage, re-verification cadence, revocation on DNS change) |

---

## 6. Frontend Architecture Review

**What already exists and should be reused, not rebuilt:**

- Shell/design system (PR9): `AppShell`, `SidebarNav`, `TopAppBar`, `Breadcrumb`, plus `components/ui/`: `DataTable`, `Card`, `StatCard`, `EmptyState`, `LoadingState`, `ErrorState`, `ActionToolbar`, `ComingSoon`, `PageContainer`, `SectionHeader`, `Button`.
- Dashboard widget family (PR10): `DashboardGrid`, `MetricCard`, `HealthCard`, `TrendCard`, `AlertCard`, `StatusCard` — not directly reused by PR11's list/detail pages, but the same "compose from a shared family" discipline should extend to any new summary cards PR11 adds.
- **`navigation.ts` already models PR11's scope as reserved, `functional: false` nav entries**: `teams`, `roles`, `iam`, `audit-logs`, `sessions`, `api-keys` all exist as `<ComingSoon>` placeholders today, gated with the same `visible:` pattern as functional items. PR11 work is largely a matter of flipping these to `functional: true` and pointing them at new pages — the taxonomy decision is already made.
- **Users**: `pages/UsersPage.tsx` (search, sort, pagination, status badge, global roles, org count, row-click detail) + `pages/UserDetailPage.tsx` (general info, `UserStatusAction` enable/disable, `RoleSelector`/`RoleAssignmentList` for global roles, `UserOrgMembershipList`). Components: `components/users/{UserOrgMembershipList,UserStatusAction}.tsx`.
- **Organizations**: `pages/OrganizationsPage.tsx` + `pages/OrganizationDetailPage.tsx` — the detail page already renders member/team/API-key/OAuth-client/license **summary counts** (`OrganizationSummaryCard` ×5), a `MembersRolesCard` (role assignment per member), a `TeamsCard`, a **read-only SSO configuration section**, and a best-effort recent-activity panel. Components: `components/organizations/{OrganizationStatusBadge,OrganizationSummaryCard,OrganizationTable}.tsx`, `components/roles/{RoleAssignmentList,RoleBadge,RoleSelector}.tsx`, `components/teams/{TeamRow,TeamsCard,TeamMemberSelector}.tsx`.
- Data layer: `users.ts`, `roles.ts`, `teams.ts`, `organizations.ts` (not read in full this pass, but referenced throughout `OrganizationDetailPage.tsx`) — all follow the same `apiFetch`-with-`authHeaders` pattern as `dashboard.ts`.
- Permission gating pattern already established in `auth.ts`: `hasAdminAccess()`, `hasPlatformAdminAccess()`, `hasOrganizationsAccess()` — every new PR11 page should add its `visible:` check the same way, reusing these three (or a new one only if a genuinely new permission is added — see §5's permission-coverage findings, which found existing permissions already cover most of PR11's proposed scope except a general "security.manage").

**New pages/components actually needed** (adjusted from the brief's example list based on what's already covered above):

```
src/pages/identity/
  TeamsPage.tsx              — standalone (data + components already exist, just not a page)
  RolesPage.tsx               — standalone (same)
  ServiceAccountsPage.tsx     — new: list/create/revoke for ApiKey + OAuthClient
  SSOSettingsPage.tsx         — new: configure/edit form; can start from OrganizationDetailPage's
                                 existing read-only SSO section rather than building from scratch
  DomainVerificationPage.tsx  — new, blocked on backend (§5, PR11.6)
  SecurityPage.tsx            — new, blocked on backend (MFA, §5 PR11.5) — was "MFA" in the brief;
                                 renamed since it'll also eventually house the org-level security-
                                 settings bundle once that exists
```
`UsersPage.tsx`/`UserDetailPage.tsx`/`OrganizationsPage.tsx`/`OrganizationDetailPage.tsx` are **extended**, not replaced.

**Reuse confirmed**: `DataTable` (typed wrapper already used for list-shaped data — `ServiceAccountsPage`/`TeamsPage`/`RolesPage` should adopt it, though existing `UsersPage`/`OrganizationTable` predate it and use hand-written tables directly, per that component's own comment, "existing tables... are untouched"), `Card`/`StatCard` (for summary tiles), `EmptyState`/`LoadingState`/`ErrorState` (standard loading/empty/error patterns already used throughout), `ActionToolbar` (right-aligned button rows), and the `visible:`-based permission-guard pattern in `navigation.ts`.

---

## 7. Dependencies

- **Every new control-center UI surface needs a corresponding proxy route** before it can call omnibioai-auth — following the existing `routes_org_proxy.py`/`routes_user_proxy.py`/`routes_role_proxy.py`/`routes_team_proxy.py` pattern (forward `Authorization` header, no local authorization decision). PR11.3 (SSO) and PR11.4 (Service Accounts) need **new** proxy route files — control-center currently has no SSO or API-key/OAuth-client proxy at all.
- PR11.1's org/status/role filters and the last_login/auth_method columns both require **auth-repo backend PRs to land first** (or in parallel) — the control-center UI has nothing to call otherwise.
- PR11.5 (MFA) and PR11.6 (Domain Verification) are **backend-first by necessity** — there is no existing partial implementation to extend, unlike every other sub-scope.
- PR11.4's audit-trail gap (§4.2) is a dependency worth pulling forward: wiring `audit_service` into API-key/OAuth-client create/revoke (and user status change) is small and should land *before or alongside* PR11.4, not after, since PR11.4 is exactly the surface that makes those actions easy to trigger from a UI.
- The permission-model question (§5's brief) is **not a blocker**: this discovery found existing permissions (`manage_all_orgs`, `manage_org`, `manage_sso`, `manage_api_keys`, `manage_oauth_clients`, `manage_roles`, `manage_teams`) already cover PR11.1–PR11.4's scope exactly. Only a general **`security.manage`**-shaped permission has no existing analog, and only becomes relevant once PR11.5 (MFA)/org-security-settings exist — that decision can be deferred to PR11.5 itself.

---

## 8. Risks

1. **Scope creep via naming**: "Organization Management" in the brief lists Subscription/Usage/Security-settings — none of that exists server-side (§2.2). If PR11.2 is scoped to include real subscription/usage UI, it silently becomes a billing-system project, not an admin-console UI PR. Recommend explicit placeholders (PR10's `null`/"Preview data" convention) for these three fields specifically, same as PR10 did for its own Business section.
2. **MFA and Domain Verification are both real backend projects**, not admin-console features that happen to need a small API. Sizing PR11.5/PR11.6 like the other UI-only sub-PRs would understate the work significantly — recommend budgeting each as its own multi-PR phase (MFA especially, given it touches the core login flow and needs careful security review — enrollment, recovery-code generation/storage, rate-limiting, backup-code single-use enforcement, etc.).
3. **Two role-management API surfaces with different permission gates** (§4.5) — if PR11.1/11.2 UI accidentally calls the `manage_roles`-gated legacy global-role endpoint in one place and the `manage_all_orgs`-gated one in another, admins with only one of those two permissions will see inconsistent capability across the same conceptual feature. Pick one surface deliberately per capability and document why.
4. **Domain-verification UI risk**: since `allowed_domains` today is self-declared (§4.3), any UI copy suggesting a domain is "verified" before PR11.6's real DNS-proof workflow exists would be actively misleading to enterprise customers evaluating security posture. Worth explicit wording review even for PR11.3's SSO config UI, which touches this same field.
5. **Audit gap compounds risk across every PR11.x sub-PR**: since user-status changes and API-key/OAuth-client lifecycle events aren't audited today, *every* new admin-console action PR11 adds in these areas increases the amount of unaudited administrative power in the system. Recommend treating "wire `audit_service` into these paths" as a cross-cutting requirement for PR11.1 and PR11.4, not a separate nice-to-have.
6. **`routes_users.py` is a dead, unregistered stub** — no risk by itself, but worth a one-line note in any PR11.1 PR description so a future contributor doesn't assume it's live and build against it.
