# PR11.5.6 — Enterprise Admin Console Security UI

**Status: OPEN FOR REVIEW ONLY — DO NOT MERGE.**

Exposes the MFA/security capabilities `omnibioai-auth` built across
PR11.5.1–PR11.5.5 inside `admin.omnibioai.org`: a platform-wide Security
Dashboard, per-organization MFA policy management (with break-glass
override), a user-detail MFA status card with admin reset, and MFA-aware
audit-log filtering. See `docs/pr11-5-6-security-ui-discovery.md` for
the full discovery pass this implementation followed.

## Architecture diagram

```
                          admin.omnibioai.org (this app)
   ┌──────────────────────────────────────────────────────────────────┐
   │  pages/security/SecurityDashboardPage.tsx                        │
   │    -- walks GET /platform/users + GET /platform/orgs (paginated) │
   │       client-side, filters GET /platform/audit-events to MFA     │
   │       event types. No new backend aggregation endpoint.          │
   │                                                                    │
   │  pages/security/OrganizationMFAPolicyPage.tsx                    │
   │    -- org picker (reuses OrganizationsPage) -> policy detail,    │
   │       same "list -> detail" shape as SSOSettingsPage.tsx          │
   │                                                                    │
   │  components/users/UserMFASecurityCard.tsx                        │
   │    -- embedded in UserDetailPage.tsx, replaces PR11.1's           │
   │       method/last-login-only placeholder card                     │
   │                                                                    │
   │  audit.ts: KNOWN_EVENT_TYPES += 16 MFA event types                │
   │            MFA_EVENT_TYPES (subset, for the Dashboard tile)       │
   └───────────────────────────┬────────────────────────────────────────┘
                                │  security.ts / users.ts / organizations.ts
                                │  (relative-path fetch, Authorization header)
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  control-center backend (this repo's own FastAPI app)             │
   │    routes_org_mfa_proxy.py   (new)  -- pure relay, zero auth logic│
   │    routes_user_proxy.py      (+1 route: POST .../mfa/reset)       │
   │    routes_user_proxy.py      (existing: GET list/detail, PATCH)   │
   │    routes_org_proxy.py       (existing, unmodified)                │
   │    routes_audit_proxy.py     (existing, unmodified)                │
   └───────────────────────────┬────────────────────────────────────────┘
                                │  httpx, forwards Authorization header
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  omnibioai-auth (IAM_URL)                                          │
   │    GET/POST/PATCH  /orgs/{org_id}/mfa-policy          (PR11.5.5)  │
   │    POST/DELETE     /orgs/{org_id}/mfa-policy/override (PR11.5.5)  │
   │    POST            /platform/users/{id}/mfa/reset     (PR11.5.4)  │
   │    GET /platform/users, GET /platform/users/{id}                  │
   │         + mfa_enabled / mfa_status / mfa_primary_method /          │
   │           mfa_enabled_at / mfa_last_verified_at / mfa_devices /    │
   │           mfa_recovery_codes_remaining        (new fields, §API)  │
   │    GET /platform/orgs                                              │
   │         + mfa_policy_required / mfa_policy_configured (new fields) │
   │    GET /orgs/{org_id}/mfa-policy                                   │
   │         + enabled_by_email / override_reason  (new fields)         │
   │    require_org_permission_or_platform_admin(MANAGE_SSO)            │
   │    require_permission(MANAGE_ALL_ORGS)                              │
   │    -- every authorization decision happens HERE, never in this     │
   │       repo. See "Permission model" below.                          │
   └──────────────────────────────────────────────────────────────────┘
```

## API mapping

| UI surface | Frontend call (`security.ts`/`users.ts`/`organizations.ts`) | Proxy route (this repo) | `omnibioai-auth` route | Permission |
|---|---|---|---|---|
| Security Dashboard — MFA adoption | `fetchPlatformUsers` (paged) | `GET /platform/users` | `GET /platform/users` | `manage_all_orgs` |
| Security Dashboard — org policy counts | `fetchPlatformOrgs` (paged) | `GET /platform/orgs` | `GET /platform/orgs` | `manage_all_orgs` |
| Security Dashboard — recent events | `fetchAuditEvents` | `GET /platform/audit-events` | `GET /platform/audit-events` | `manage_all_orgs` |
| MFA Policy — view | `fetchOrgMFAPolicy` | `GET /orgs/{org_id}/mfa-policy` | same | `manage_sso` (org-scoped) |
| MFA Policy — create | `createOrgMFAPolicy` | `POST /orgs/{org_id}/mfa-policy` | same | `manage_sso` (org-scoped) |
| MFA Policy — enable/disable | `updateOrgMFAPolicy` | `PATCH /orgs/{org_id}/mfa-policy` | same | `manage_sso` (org-scoped) |
| MFA Policy — break-glass enable | `enableMFAPolicyOverride` | `POST /orgs/{org_id}/mfa-policy/override` | same | `manage_all_orgs` (global) |
| MFA Policy — break-glass clear | `clearMFAPolicyOverride` | `DELETE /orgs/{org_id}/mfa-policy/override` | same | `manage_all_orgs` (global) |
| User detail — MFA status/devices/recovery count | `fetchPlatformUserDetail` (existing call, extended response) | `GET /platform/users/{id}` | same | `manage_all_orgs` |
| User detail — Reset MFA | `resetUserMFA` | `POST /platform/users/{id}/mfa/reset` | same | `manage_all_orgs` |
| Audit Logs — MFA filter | `KNOWN_EVENT_TYPES` (extended) | `GET /platform/audit-events?event_type=...` | same, unmodified | `manage_all_orgs` |

## Permission model

**No new permission anywhere, in either repo.** Every gate reuses an
existing permission, per the task's own explicit constraint:

- **Security Dashboard** (`security-overview` nav item): `hasPlatformAdminAccess()` — same as `audit-logs`, because every API it reads (`/platform/users`, `/platform/orgs`, `/platform/audit-events`) is `manage_all_orgs`-gated.
- **MFA Policy management** (`mfa-policy` nav item, CRUD): `hasOrganizationsAccess()` — same as `iam`/`api-keys`, because the CRUD routes are `manage_sso`-gated (org-scoped).
- **Break-glass override**: gated inline by `hasPermission('manage_all_orgs')`, same pattern `SSOSettingsPage.tsx`'s own `canOverride` uses for `override_sso_enforcement` — a *different* permission than the org-scoped CRUD above, deliberately, so it works even if the org's own admin is locked out.
- **Reset MFA**: no separate frontend gate needed — `UserDetailPage.tsx` (which the card lives inside) is already platform-admin-only.

**Frontend gates are UX only.** Every one of the above is re-checked,
independently and authoritatively, by `omnibioai-auth` on every request.
A frontend gate hidden or bypassed changes nothing about what the
backend will accept.

## MFA lifecycle (as surfaced by this UI)

```
 No policy configured           Policy configured, not required        Policy required
┌──────────────────┐  create   ┌───────────────────────────┐  enable  ┌─────────────────────┐
│ "No MFA policy"   │─────────▶│ Status: Disabled, OFF      │─────────▶│ Status: Enabled, ON  │
│ empty state        │          │ (Enable MFA Requirement)   │          │ (Disable MFA Req.)   │
└──────────────────┘           └───────────────────────────┘          └──────────┬───────────┘
                                                                                    │ break-glass
                                                                          override  │ enable
                                                                                    ▼
                                                                        ┌─────────────────────────┐
                                                                        │ required=true (unchanged)│
                                                                        │ override_active=true      │
                                                                        │ enforcement suspended     │
                                                                        └─────────────────────────┘

 A user's own MFA enrollment, surfaced on UserDetailPage:
 not enrolled → enrolled (TOTP, self-service, no UI change here)
              → Reset MFA (platform-admin) → back to not enrolled
```

The confirmation copy shown before each destructive/high-impact action
matches the task's own literal wording:

- Enable MFA Requirement: *"Warning: Enabling mandatory MFA may prevent users without enrolled MFA from logging in. Continue?"*
- Break-glass enable: *"This temporarily disables MFA enforcement. All actions are audited. Continue?"*
- Reset MFA: *"This will remove all MFA devices and invalidate recovery codes. Continue?"*

## Security considerations

- **No secret ever rendered.** `OrgMFAPolicy`/`PlatformMFADeviceSummary`
  (the two new frontend types) have no `secret`/`encrypted_secret`/
  `otpauth_uri`/recovery-code field at all — not masked, structurally
  absent, because the backend responses they mirror never include one
  either (`OrgMFAPolicyOut`, `PlatformMFADeviceSummary`, both in
  `omnibioai-auth/app/schemas/`). Verified by dedicated tests in all
  three new frontend test files (`container.textContent` grepped for
  `otpauth://`/`encrypted_secret`/`challenge_token`).
- **Audit filtering reuses `maskSensitiveFields`** (existing, `audit.ts`)
  for free — every MFA event now selectable in `AuditLogsPage`'s filter
  goes through the exact same detail-modal masking every other event
  type already does; no new masking logic was written.
- **UI is not authorization.** Every gate in this PR is a `hasXAccess()`
  check that only decides what renders — the backend's own
  `require_org_permission_or_platform_admin`/`require_permission`
  (both pre-existing, unmodified) is what actually decides every
  request. Confirmed for the two new proxy files: neither makes an
  authorization decision, both are pure relay (see
  `routes_org_mfa_proxy.py`'s own docstring and its 1:1 mirror of
  `routes_org_sso_proxy.py`'s already-reviewed shape).
- **Backend read-only additions were the minimum needed**, each
  justified in `docs/pr11-5-6-security-ui-discovery.md` §6: five fields
  on `PlatformUserDetailOut`, one field on `PlatformUserSummary`, two
  fields on `PlatformOrgSummary`, two fields on `OrgMFAPolicyOut` — no
  new endpoint, no new table, no new migration, no permission change,
  in either repo.
- **Known, disclosed scaling limit** (not solved in this PR): the
  Security Dashboard's MFA-adoption and org-policy-coverage tiles walk
  every page of `/platform/users`/`/platform/orgs` client-side rather
  than calling a dedicated aggregation endpoint — correct and cheap at
  this platform's actual current scale, but would need a real
  `SELECT COUNT(*)`-shaped endpoint well before tens of thousands of
  users/orgs. See discovery doc §7 for the full reasoning; flagged here
  rather than silently accepted.

## Testing

- **Frontend**: `npm test` — 250 tests across 22 files, all passing,
  including the 3 new required files (`SecurityDashboardPage.test.tsx`:
  9, `OrganizationMFAPolicyPage.test.tsx`: 13,
  `UserMFASecurityCard.test.tsx`: 9). `npx tsc --noEmit`: zero errors.
- **Backend (`omnibioai-control-center`)**: `pytest` — 771 passed,
  99.77% coverage (98% gate), including the new
  `test_routes_org_mfa_proxy.py` and the 3 new tests added to
  `test_routes_user_proxy.py`.
- **Backend (`omnibioai-auth`)**: `pytest` — full suite green (see PR
  description for the exact count at merge time), including updated
  assertions in `test_platform_admin_api.py`/`test_platform_users_api.py`
  for the new response fields and new dedicated MFA-detail/
  MFA-policy-listing tests. No IAM logic changed — every new backend
  line is either a read-only field addition or a pure-relay proxy
  route.

## Screenshots

**Not captured in this pass.** This repo's backend/frontend are meant
to run together against a Cloudflare-Tunnel/docker-compose topology
(`IAM_URL=http://auth-service:8001`, a docker-compose service name, not
a standalone-reachable host in this session) — standing up a full live
environment (both backends, migrations, seed data, a logged-in platform
admin session) was out of scope for the time available in this pass.
Every page's rendered states (loading/denied/empty/error/populated) are
instead verified directly by the 31 tests across the three new test
files, which render each component against realistic mocked API
responses and assert on the actual rendered DOM — the same level of
confidence prior PR11.x sessions' own screenshots supplemented, not
replaced. Flagged explicitly here rather than fabricated, per this
codebase's own established practice (e.g.
`docs/pr11-mfa-org-policy-discovery.md` §8's bootstrapping-gap
disclosure in `omnibioai-auth`).
