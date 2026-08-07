# Admin Console Dual Build Architecture

Status: implemented (frontend build split only — see "Remaining deployment work" below for what this PR does *not* do).

> **2026-08-07 update:** point 3 below is now done. **PR14.7B**
> (`docker/nginx/{api-proxy.conf,control-center.conf}` + Dockerfile Stage
> 3, MERGED) wires `dist-admin`/`dist-control` into an actual nginx
> serving image, host-based by `Host` header, verified on
> `localhost:5174` — but not yet reachable externally. **PR14.7C**
> (Cloudflare Tunnel cutover — repoints `control.omnibioai.org`'s
> ingress rule at `:5174`, was `:7070` direct-to-backend, and adds a new
> `admin.omnibioai.org` rule at the same `:5174`) is the deliberate
> follow-up that makes both domains reachable externally; as of this
> note it's **prepared but not yet applied** — needs root on the
> tunnel host plus a DNS record for `admin.omnibioai.org` (none exists
> yet), both outside what a coding agent can do unattended. See
> "Deployment mapping" below for exact target state and the rollout
> report for this session for the prerequisites. `nginx-router.conf`
> (point 1 below) is correctly *not* touched by either PR:
> `control.omnibioai.org` bypasses it via a direct tunnel ingress rule,
> so this stays a `/etc/cloudflared/config.yml`-only change.

## Architecture decision

**One repository, two builds, two domains.**

`omnibioai-control-center` is not being split into a separate repository. This document supersedes any earlier framing that assumed it would (`~/omnibioai_admin_console_phase1_findings.md` has the full discovery trail for how that got resolved). The decision, re-confirmed directly against this repo's own history:

- `admin.omnibioai.org` — the enterprise administration surface. Login required. Organizations, Organization Details, Users, User Details (Roles/Permissions and Teams are components rendered inside Organization Details, not separate pages), plus every existing ops page.
- `control.omnibioai.org` — the internal operations console. Health, Docker, Ecosystem Report, Config, LLMs, Cloud. No enterprise administration UI at all — not hidden, genuinely absent from this build's JavaScript.
- **Same repository, same backend, same auth system, same permission checks.** The only thing that differs between the two domains is which frontend bundle is served. Nothing about authentication, authorization, or the API surface changes based on which build a request came from.

## How the split works

`src/main.tsx` selects one of two root components at build time, based on `VITE_APP_MODE`:

```
VITE_APP_MODE=admin   → src/apps/AdminApp.tsx   → dist-admin/
VITE_APP_MODE=control → src/apps/ControlApp.tsx → dist-control/
```

```
npm run build:admin    # tsc -b && VITE_APP_MODE=admin vite build
npm run build:control  # tsc -b && VITE_APP_MODE=control vite build
```

`AdminApp.tsx` is the pre-existing `App.tsx`'s exact behavior, relocated (not rewritten) — every page, every permission gate, unchanged. `ControlApp.tsx` imports only the six ops pages; it has no import statement anywhere referencing `OrganizationsPage`, `OrganizationDetailPage`, `UsersPage`, `UserDetailPage`, or anything under `components/organizations`, `components/roles`, `components/teams`.

Both apps share `AuthGate.tsx` (the session/login state machine, extracted unchanged from the old `App.tsx`) and `Header.tsx` — no duplicated business logic.

### Why this produces genuinely smaller bundles, not just hidden UI

`src/main.tsx` compares `import.meta.env.VITE_APP_MODE` directly, as a static top-level literal comparison — not through an intermediate function parameter or a dynamic `import()`. Vite inlines `import.meta.env.*` values as literal constants at build time; Rollup's production minifier then constant-folds the losing branch of the resulting `if`/ternary and tree-shakes its now-unreachable `AdminApp`/`ControlApp` import out of that build's dependency graph entirely.

This was verified against the real build output, not assumed:

```
$ npm run build:control && grep -c "OrganizationDetailPage\|TeamsCard\|RoleAssignmentList" dist-control/assets/*.js
0

$ npm run build:admin && grep -c "Create Team" dist-admin/assets/*.js   # a string literal from TeamsCard.tsx
1
```

`dist-control`'s bundle is ~45KB smaller than `dist-admin`'s — the actual size of the excluded enterprise-console code. The only enterprise-related trace left in `dist-control` is the tab label string `"Organizations"` from `Header.tsx`'s always-defined `ORGANIZATIONS_TAB` constant (Header is shared by both apps and never renders that tab unless told to) — inert data, not reachable code.

## Security model

**The build split is a deployment/UX optimization. It is not, and must never be treated as, an authorization boundary.**

- Every existing server-side check — `require_permission`/`require_admin` in `omnibioai-control-center`'s own routes, and every org-membership/permission check in `omnibioai-auth` — is completely unchanged by this PR. A request is authorized or denied by the backend exactly as it was before, regardless of which domain or bundle it originated from.
- No new permissions were introduced. `hasAdminAccess()` (the existing `admin` role check) and `hasOrganizationsAccess()`/`hasPlatformAdminAccess()` (the existing `manage_all_orgs`-backed checks) are reused as-is by both `AdminApp` and `ControlApp`.
- `ControlApp`'s audience is `hasAdminAccess()` alone (narrower than `AdminApp`'s `hasAdminAccess() || hasOrganizationsAccess()`) — an org-only admin with no global `admin` role has no ops pages to see in this build, so they're denied here exactly as the underlying permission model already dictates.
- **Do not, in any future change, use the served domain/hostname as a trust signal** (e.g. "this request came from control.omnibioai.org, so it must be a read-only ops request"). Nothing about which nginx location or Cloudflare Tunnel hostname served a request is authenticated or tamper-proof from the backend's point of view.

## Generated artifacts

```
frontend/cc-ui/dist-admin/    # admin.omnibioai.org
frontend/cc-ui/dist-control/  # control.omnibioai.org
```

Both are gitignored (`frontend/cc-ui/.gitignore`), generated fresh by `npm run build:admin`/`build:control` or the Dockerfile's `frontend-builder` stage. The pre-existing `frontend/cc-ui/dist/` (committed to git — an existing, unrelated repo convention, not something this PR changes) is still produced too, by the unmodified `npm run build`, so the Dockerfile's existing (currently unused in the live deployment — see below) Stage 3 keeps working exactly as before.

## Deployment mapping

End-to-end path, PR14.7B (MERGED) + PR14.7C (Cloudflare Tunnel cutover,
prepared/not yet applied — see status note above):

```
                     Cloudflare Tunnel (/etc/cloudflared/config.yml,     omnibioai-control-center
                      on the tunnel host, root-owned -- NOT in any repo)      docker/nginx/*.conf
                              │                                              (localhost:5174)
  admin.omnibioai.org ───────►│ ingress: admin.omnibioai.org → :5174 ───────► server_name admin.omnibioai.org
                              │                                                 root .../html/admin (dist-admin/)
  control.omnibioai.org ─────►│ ingress: control.omnibioai.org → :5174 ─────► server_name control.omnibioai.org
                              │            (was :7070 direct-to-backend)        root .../html/control (dist-control/)
                              │                                                        │
                              │                                                        ▼
                              │                                              both proxy API paths to
                              │                                              control-center:7070 (FastAPI) --
                              │                                              same backend, same IAM checks,
                              │                                              regardless of which domain served
```

`admin.omnibioai.org` needs a DNS record pointed at this tunnel before
the ingress rule above does anything externally — Cloudflare Tunnel
ingress rules only govern traffic the edge already knows to route into
the tunnel; they don't create the DNS side themselves. See the PR14.7C
rollout report for the exact command.

## Remaining deployment work

Done, PR14.7B (MERGED): `dist-admin`/`dist-control` are wired into an
actual nginx serving image (`docker/nginx/{api-proxy.conf,
control-center.conf}` + Dockerfile Stage 3), verified on
`localhost:5174`. `control-center`'s FastAPI process itself is
unchanged — still no `StaticFiles`/`.mount()` in `main.py`; serving is
entirely nginx's job, in a separate `control-center-web` container.

Done, PR14.7C (prepared, not yet applied — see status note above):
Cloudflare Tunnel ingress cutover, `control.omnibioai.org` → `:5174`
(was `:7070`), plus a new `admin.omnibioai.org` → `:5174` rule.
`omnibioai-studio/docker/nginx-router.conf` correctly stays untouched by
this — `control.omnibioai.org` bypasses that router via a direct tunnel
ingress rule (documented in that file's own PR7 comment), so serving
stayed entirely self-contained in `control-center`'s own image rather
than requiring host-based routing in the shared router too.

Not yet done: Cloudflare Access policy coverage for `admin.omnibioai.org`
specifically (Access policies live in the Cloudflare Zero Trust
dashboard, not in `config.yml` or any file in this repo — verify there
directly, don't assume a wildcard/existing policy already covers a new
hostname).

## Remaining gaps / non-goals of this PR (unchanged from the task's own scope)

- No billing, usage analytics, or audit-log UI (neither exists in `control-center` today).
- No new CRUD APIs — every endpoint this phase needs already exists via the proxy routers, untouched.
- No new permissions.
- No React Router migration — both apps still use the pre-existing hand-rolled `window.history.pushState`/`popstate` deep-linking for Organizations/Users (`AdminApp` only; `ControlApp` has no deep-linkable enterprise routes to support).
