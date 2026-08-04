# Admin Console Dual Build Architecture

Status: implemented (frontend build split only — see "Remaining deployment work" below for what this PR does *not* do).

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

## Deployment mapping (target — not yet wired, see Remaining deployment work)

```
admin.omnibioai.org
        |
        v
  dist-admin/

control.omnibioai.org
        |
        v
  dist-control/
```

## Remaining deployment work (explicitly out of scope for this PR)

This PR produces the two build artifacts. It does **not** modify `nginx-router.conf`, Cloudflare Tunnel configuration, or anything in `omnibioai-studio` — those changes are cross-repo and need their own coordinated PR. For that follow-up work, two things discovered during this phase's architecture review are worth carrying forward:

1. **`nginx-router.conf` has no host-based routing today** — a single `server_name _` catch-all serves every path-based route. Serving `dist-admin`/`dist-control` at two distinct domains requires either two `server_name` blocks keyed off the incoming `Host` header, or a path-based split, as a deliberate decision in that follow-up PR.
2. **More importantly: in the live deployment, `cc-ui`'s built frontend is not served at all today**, dual-build or not. `control-center`'s container runs only `uvicorn control_center.main:app` — no `StaticFiles`/`.mount()` call exists in the backend (confirmed by direct inspection) — and `main.py`'s `root()` serves a completely different, self-contained static page, not `cc-ui`'s bundle. `nginx-router.conf` has its own "KNOWN DRIFT" comment confirming this is deliberate/known, not an oversight. **This means the actual, most critical next step for either domain to work at all is wiring `dist-admin`/`dist-control` into serving — the domain split is the correct shape to serve them in, but by itself doesn't make either one reachable.**
3. The Dockerfile's existing Stage 3 (`nginx:alpine`, serves `dist/` on port 5174) appears to have been built for exactly this kind of static-serving need and was never wired into `docker-compose-release.yml`. Worth adapting rather than designing serving from scratch, once that follow-up work starts.

## Remaining gaps / non-goals of this PR (unchanged from the task's own scope)

- No billing, usage analytics, or audit-log UI (neither exists in `control-center` today).
- No new CRUD APIs — every endpoint this phase needs already exists via the proxy routers, untouched.
- No new permissions.
- No React Router migration — both apps still use the pre-existing hand-rolled `window.history.pushState`/`popstate` deep-linking for Organizations/Users (`AdminApp` only; `ControlApp` has no deep-linkable enterprise routes to support).
