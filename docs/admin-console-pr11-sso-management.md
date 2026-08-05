# PR11.3 — Enterprise SSO Management UI

Adds the Enterprise SSO Management page to `admin.omnibioai.org`
(the Admin Console / `AdminApp`), letting a platform administrator or
an org's own `manage_sso` holder configure, enforce, and (for
platform admins) break-glass override that organization's OIDC single
sign-on. This is a UI-only PR: no authentication, IAM, or permission
system was redesigned — everything below reuses `omnibioai-auth`'s
existing SSO API and permission model exactly as-is. See
`docs/admin-console-pr11-sso-discovery.md` for the discovery pass this
PR was built from, including the specific fields the backend does and
does not support.

## Architecture

```
 Admin Console UI (frontend/cc-ui)
   SSOSettingsPage.tsx  ──uses──▶  sso.ts (fetch wrapper)
        ▲
        │ reached via
   navigation.ts 'iam' nav item ──▶ AdminApp.tsx org-picker/detail routing
        │                              (reuses OrganizationsPage as the
        │                               "pick an org" list step)
        │
   OrganizationDetailPage.tsx "Manage SSO Settings" ──▶ deep-links here too
        │
        ▼
 control-center backend (backend/src/control_center)
   routes_org_sso_proxy.py  ── pure HTTP relay, zero auth decisions ──▶
        │
        ▼
 omnibioai-auth
   routes_org_sso.py  (require_org_permission_or_platform_admin(manage_sso),
                        require_permission(override_sso_enforcement))
        │
        ▼
   org_sso_service.py  (OIDC discovery, encryption, lockout guard)
        │
        ▼
   organization_sso_configs table (client_secret stored Fernet-encrypted)
```

Three new/changed layers, each doing exactly one job:

1. **`SSOSettingsPage.tsx`** (`frontend/cc-ui/src/pages/identity/`) —
   all presentation and client-side validation. Reached two ways:
   - The `IAM / SSO Management` nav item (now `functional: true`,
     `visible: hasOrganizationsAccess`) → since SSO config is per-org,
     this lands on an org-picker step first (`OrganizationsPage`,
     reused unmodified) → then this page, deep-linked at `/iam/{orgId}`.
   - `OrganizationDetailPage.tsx`'s SSO summary card's "Manage SSO
     Settings" button, which jumps straight to `/iam/{orgId}` for the
     org already being viewed.
2. **`routes_org_sso_proxy.py`** (`backend/src/control_center/api/`) —
   a pure relay, following the exact shape of the other four proxy
   files in this repo (`routes_{org,user,role,team}_proxy.py`).
   Forwards the `Authorization` header and request body verbatim to
   `omnibioai-auth`, relays its status/body back unmodified. Makes
   **zero** authorization decisions — it doesn't know what `manage_sso`
   is, and never needs to.
3. **`omnibioai-auth`'s existing `routes_org_sso.py`** — unchanged by
   this PR. The 6 routes it already exposed (`GET/POST/PATCH/DELETE
   /orgs/{org_id}/sso`, `POST/DELETE /orgs/{org_id}/sso/override`) are
   the entire capability surface this UI has. No new backend route, no
   new service function, no new database column.

## Security

### Secrets handling

- **`client_secret` is write-only.** The backend's `OrgSSOConfigOut`
  response never includes `client_secret` or
  `client_secret_encrypted` (verified in `app/schemas/org_sso.py` and
  `routes_org_sso.py::_to_out`) — there is nothing for this UI to
  accidentally render even if it tried. `sso.ts`'s `OrgSSOConfig`
  interface mirrors that response shape exactly and has no secret
  field either.
- The **Configure OIDC Provider** form's secret input is
  `type="password"`, `autoComplete="new-password"`, and is never
  pre-filled from a `GET` response (there's nothing to pre-fill it
  with). On an update, leaving it blank omits the `client_secret` key
  from the request entirely rather than sending an empty string —
  sending an empty string would have the backend encrypt and persist
  `""` as the new secret, silently breaking the IdP integration.
- The proxy layer (`routes_org_sso_proxy.py`) is a byte-for-byte relay:
  it never logs, caches, or otherwise inspects the request/response
  bodies it forwards, so a `client_secret` in a `POST`/`PATCH` body
  passes through without this repo's own backend ever holding a
  second copy of it beyond the single in-flight request.
- No secret is ever stored client-side — not in `localStorage`, not in
  component state beyond the controlled `<input>` the admin is
  actively typing into, and that state is cleared immediately after a
  successful submit.

### Permissions

No new permission was introduced. Both permissions this feature uses
already existed in `omnibioai-auth` and are enforced entirely
server-side:

- **`manage_sso`** (org-scoped) — every CRUD route on
  `/orgs/{org_id}/sso`. Held by an org's `org_admin` role, or bypassed
  by a platform admin's synthetic membership.
- **`override_sso_enforcement`** (global-scoped, deliberately not
  org-scoped) — the two `/orgs/{org_id}/sso/override` routes. Global on
  purpose: it's a platform-operator break-glass tool that must still
  work if the org's *own* admin is the one locked out.

The frontend's role in this is UX only, never the security boundary:

- `navigation.ts`'s `iam` entry gates on `hasOrganizationsAccess()` —
  the same existing gate `organizations` already uses — to decide
  whether the nav item (and the org-picker landing page) appears at
  all.
- `SSOSettingsPage` calls `hasPermission('override_sso_enforcement')`
  only to decide whether to render the Break Glass card — a user
  without it simply doesn't see the section; the backend's
  `require_permission` would reject the calls regardless.
- For `manage_sso` specifically, the page has no reliable client-side
  signal at all (an org-scoped permission from an org role may or may
  not be reflected in the current JWT's claims depending on org
  context — see the discovery doc). So `SSOSettingsPage` always
  attempts the `GET`, and a `403` renders a "Permission denied" state
  driven entirely by the backend's actual response — exactly the same
  pattern `OrganizationDetailPage.tsx`'s `MembersRolesCard` already
  uses for `manage_org`.

### Enforcement model

`SSO enforced` and the break-glass override are two independent
fields the backend already defines and this UI never reimplements:

- Turning enforcement **on** is rejected by the backend (`400`) unless
  the organization already has at least one completed SSO login on
  record (`org_sso_service.set_enforced`'s lockout guard) — this UI
  shows that rule as explanatory text before the confirm step, and
  surfaces the backend's own rejection message verbatim if the guard
  fails; it does not re-implement or pre-validate the check itself.
- The break-glass override **suspends the effect** of `enforced`
  without changing the stored value — clearing the override
  automatically resumes whatever `enforced` was already set to. This
  UI reflects `sso_override_active` from the backend response as the
  sole source of truth for whether an override is currently live.

## Limitations

- **OIDC only.** `provider_type` is always `"oidc"` in the backend
  today; there is no SAML support anywhere in this stack, and this PR
  does not add any.
- **No SCIM.** Directory sync / user provisioning is out of scope —
  this UI only configures the identity provider used at login time.
- **No MFA policy.** SSO here means "delegate authentication to an
  external IdP," not a platform-side MFA requirement; that's a
  separate, unbuilt feature.
- **No `scopes` field.** The task's spec listed an optional `scopes`
  form field; the backend (`OrgSSOConfigCreate`/`OrgSSOConfigUpdate`,
  `OrganizationSSOConfig` model) has no such field to send it to, so
  it was omitted rather than invented client-side. See the discovery
  doc for the full list of spec fields resolved this way
  (`discovery_status`, `Enabled/Disabled` are both derived display
  labels over the existing `status` field, not separate data).
- **No delete-configuration UI.** The backend's `DELETE
  /orgs/{org_id}/sso` is proxied (for completeness and future use) but
  this page has no "remove SSO configuration" action — out of the
  task's listed scope (Current Configuration / Configure / Enforcement
  / Break Glass only).
- **No certificate rotation UI** — there's no certificate-based
  concept in an OIDC client-secret flow to rotate in the first place;
  noted here only because the task's own scope list explicitly
  excludes it for a future SAML phase.
- **"Manage SSO Settings" from Organization Details doesn't preserve a
  return path.** Clicking it always lands on `/iam/{orgId}`; using the
  page's own "← Back" button returns to the org-picker root
  (`/iam`), not back to that organization's detail page. This mirrors
  the app's existing per-destination (not cross-destination) back-nav
  convention — no page in this app currently remembers "which other
  page linked me here."
