# Public Read-Only Control Center

`control.omnibioai.org` (the `VITE_APP_MODE=control` build, `ControlApp.tsx`)
is now a genuinely anonymous, read-only dashboard. `admin.omnibioai.org`
(`AdminApp.tsx`) is unchanged and remains the authenticated administrative
surface.

## What changed

- **`ControlApp.tsx`**: no longer wraps its page set in `AuthGate`. There
  is no login screen in this build at all -- it renders immediately, with
  no token required, and unconditionally clears any token already sitting
  in this origin's storage before making its first request (`clearToken()`
  on mount), so it can never forward a bearer token merely because one
  happens to exist.
- **Docker and Config** were removed from `ControlApp`'s page set. Both
  call backend routes gated behind `platform.manage_infra`
  (`docker_router`/`config_router` in `main.py`), and this build has no
  way to satisfy that gate. They remain fully available, unchanged,
  through `AdminApp`'s own Infrastructure section.
- **Integrations** was added to `ControlApp`'s page set. `routes_integrations.py`
  has never required auth (booleans/labels only -- see that module's own
  comment) -- it just wasn't wired into this build's tab set before.
- **Health**: the pre-existing `HealthPage.tsx` calls `GET /summary`,
  which is deliberately `platform.manage_infra`-gated (it returns
  per-service connection targets -- internal topology). Rather than
  weakening that gate, `ControlApp` uses a new, deliberately minimal
  `PublicHealthPage.tsx` that calls only `GET /health`
  (`{"status": "ok"}`, no permission requirement, no per-service detail).
  `HealthPage.tsx` itself is unchanged and still used by `AdminApp`'s
  authenticated Infrastructure > Health page.
- **`Header.tsx`** (this build's only consumer): `OPS_TABS` updated to
  match (Docker/Config removed, Integrations added); the "Generate
  Report" button (`POST /report/generate`, `platform.manage_content`
  -gated) was removed -- no mutation control belongs in an always-
  anonymous surface, and this build has no way to satisfy that gate
  either. The "View Report" link stays -- it's a plain `GET` to
  already-public report content.
- **Backend** (`routes_infra.py`): `GET /audit-trail` and `GET /license`
  are now gated behind `platform.manage_infra`, the same permission
  `summary_router`/`docker_router`/`config_router`/`services_router`
  already use. Both were previously unauthenticated despite returning
  real per-user data -- `/audit-trail` a raw, individually-listed
  audit-event feed including `user_id` per event
  (`checks/audit_trail.py`), `/license` real customer/user email
  addresses (`checks/license_status.py`'s own `SELECT email ...` query).
  This was a pre-existing gap, found and closed as part of this work, not
  something newly introduced by making the dashboard public. Every other
  route in `routes_infra.py` (`/gpu`, `/celery`, `/database`,
  `/image-freshness`, `/usage`, `/gateway-traffic`, `/activity`,
  `/integrity`) stays exactly as it was: aggregate-only telemetry, no
  hostnames/LAN IPs/container inventory/mount paths/per-user identifiers.

## What did not change

- Every proxy router (org/user/role/team/billing/TES/model-registry/
  workflow-bundles/RAG/sessions/service-accounts/SSO/MFA/SAML/platform-
  interactions), `dashboard_router`, `analytics_router`, and
  `compliance_router` -- unchanged. None of them were touched by this
  work; each already does its own real, per-request authorization,
  either locally or by forwarding the caller's token to the upstream
  service that owns the decision.
- `require_permission()`, `verify_token()`, JWT verification, HIPAA
  compliance authorization, audit-event signing
  (`compliance/audit_log.py`), and the `security-audit-worker` pipeline
  -- untouched. `GET /compliance/hipaa-report[/pdf|/csv]` still require
  `manage_all_orgs` exactly as before; see `test_compliance_router.py`'s
  existing `test_missing_token_returns_401` coverage for all three
  routes (unmodified by this work -- already sufficient).
- `AdminApp.tsx` and its own `AuthGate` -- unchanged. Nothing about the
  authenticated administrative surface was weakened.
- This repo's own `docker/nginx/*.conf` (`control-center-web`'s reverse
  proxy) -- inspected, not modified. It's a path-based proxy layer with
  no authorization logic of its own (every `location` block just
  forwards to the FastAPI backend); the actual auth boundary for these
  routes is the backend's own `require_permission`, unaffected by this
  file either way.

## Known, deliberately out-of-scope follow-up (different repo)

`omnibioai-studio/docker/nginx-router.conf` fronts a *second* access path
to this same backend (`/_svc/control/*`, the webstudio-embedded-iframe
case) with its own `auth_request` gate and its own public-path allowlist
(`health|summary|services|report|report/data`). That allowlist was not
updated to include the endpoints this PR made public in `ControlApp`
(`llms`, `cloud`, `integrations`, `gpu`, `celery`, `database`,
`image-freshness`, `usage`, `gateway-traffic`, `activity`, `integrity`) --
doing so is out of scope for this PR (a different repository), so an
anonymous visitor reaching this backend through that specific iframe path
will still hit a login wall on those routes even though `control.omnibioai.org`
itself (which bypasses that gate entirely, per that config's own
comments) does not. This is a functionality inconsistency between the two
access paths, not a security gap either way -- flagged as a follow-up for
whoever owns that repo.

## Deliberately left as-is (shared component, not a security gap)

`EcosystemPage.tsx` is shared by both `AdminApp` and `ControlApp`. Its
`ArchTab` and internal `HealthTab` sub-tab both call `fetchSummary()`
(`GET /summary`, `platform.manage_infra`-gated); its `GenerateCta` empty
-state button calls `triggerGenerate()` (`POST /report/generate`,
`platform.manage_content`-gated). For an anonymous `ControlApp` visitor
these already fail closed and degrade gracefully (existing
`try/catch` -> `null`/error-state handling, no data leak, matching this
codebase's established "log it, never silently pretend it isn't
different" degradation pattern) -- the backend gate is what actually
stops them, exactly as intended ("backend authorization must remain
authoritative, not a frontend-only boundary"). Adding a second,
build-aware conditional inside this already-shared component to hide
those specific affordances for anonymous visitors was deliberately not
done, to avoid exactly the "complicated per-page anonymous authentication
logic" this task's own brief said to prefer avoiding in favor of the
build-mode/domain split. Net effect for an anonymous visitor: the
Architecture and Health sub-tabs show their existing empty/error state,
and the Generate button in the empty-report state is inert (a no-op
click) rather than hidden -- a UX rough edge, not a security exposure.

## 2026-09-25: operator detail trimmed from the remaining public routes

A review of `control.omnibioai.org` as a public showcase found that several
routes described above as "aggregate-only" returned more than aggregates to
anonymous callers:

| Route | Leaked to anonymous callers |
|---|---|
| `/cloud` | Slurm/HPC hostname, AWS Batch queue, Azure Batch account, GCP project and region, Kubernetes context (rendered by `CloudPage.tsx`) |
| `/integrity` | Filesystem paths and symlink targets; the settings path in the 500 error |
| `/activity` | Per-container names with CPU/memory/network figures |
| `/database` | MySQL schema names and sizes |
| `/celery` | Worker names (typically `celery@<hostname>`), recent task names, exception text |
| `/image-freshness` | Service and image names |
| `/gateway-traffic` | Top routes by request count |
| `/gpu` | Free-text messages, including exception text |
| `/reference` | Absolute `ref_root` path |
| `/report/data` | `gitStatus[]`: branch names and uncommitted/unpushed counts (accepted on 2026-09-03; reversed here) |

These routes stay reachable without a login, but now return their full
output only to a caller whose token carries `platform.manage_infra`
(`core.auth.infra_viewer`). Everyone else gets the allowlisted,
counts-only shape built by `core/public_view.py`; a field added to a check
later stays private until it is deliberately added there. The admin
surfaces keep full detail: `CloudPage.tsx` and the generated report's
`/gpu`, `/activity`, `/integrity` and `/audit-trail` calls now send the
signed-in operator's token. The public Ecosystem Report no longer shows
the Ecosystem Status (git) tab, and the public header says "Control center
online" instead of "All systems operational", since it is derived from
the control center's own `/health` only.
