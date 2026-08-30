# Deployment Health -- DH-3: Admin Console UI integration

DH-3 adds a read-only `Deployment Health` page to the Admin Console,
consuming DH-2's backend contract (`docs/DEPLOYMENT_HEALTH_DH2.md`)
as-is. It performs no health or dependency computation of its own -- the
backend remains authoritative for every status, comparison, and evidence
value this page renders.

## Route

Human-facing SPA route: `/deployment-health`, wired into `AdminApp.tsx`'s
existing History API/`PageKey`/`renderPage()` routing (the same pattern
`/regression-health` already uses -- no new routing framework). Direct
navigation and refresh/deep-link both work: the initial-state resolver,
the URL-sync effect, and the `popstate` handler each gained one branch
for `/deployment-health`, mirroring `/regression-health`'s exact shape in
all three places.

## API path and the REG-010 route-collision check

DH-3 does **not** call the backend's `GET /deployment-health` path
directly from the browser. Doing so would collide with the SPA route the
same way REG-010 did for Regression Health before that was fixed: the
API path is the distinct `/deployment-health/data`
(`api.ts::fetchDeploymentHealth`), and `docker/nginx/api-proxy.conf` adds

```
location = /deployment-health/data {
    rewrite ^/deployment-health/data$ /deployment-health break;
    proxy_pass http://$control_center_upstream;
    proxy_set_header Host $host;
}
```

-- the exact pattern already in place for `/regression-health/data`, not
a new bare `location /deployment-health { ... }` that would swallow the
SPA route. `backend/tests/test_nginx_config.py` gained one test
(`test_deployment_health_api_is_separate_from_spa_route`) asserting this
config shape directly, the same way the existing Regression Health test
does.

## Permission

`platform.manage_infra` -- the exact permission DH-2's backend route
requires, reused via `hasPermission('platform.manage_infra')` (a shared
`hasManageInfraAccess` reference in `navigation.ts`, the same function
Regression Health's nav entry now also uses) for both nav visibility and
the `AdminApp.tsx` render gate. No new permission was added anywhere.
Frontend visibility is a UX signal only; the backend's own
`require_permission` check on `GET /deployment-health` is what actually
matters and is unchanged by this work.

## Navigation

`Operations -> Infrastructure -> Deployment Health`, placed immediately
after Regression Health and before Docker (`Health -> Regression Health
-> Deployment Health -> Docker`), using the `HeartPulse` icon already
available from the `lucide-react` dependency this project already has (no
new icon package). `navigation.test.ts` asserts the full four-item
ordering directly against `NAVIGATION`, not inferred from rendered DOM.

## Intrinsic vs. effective health (hard requirement)

Every service in the table and its detail panel renders **two** separate
`StatusBadge`s, labeled `Intrinsic` and `Effective` -- never collapsed
into one value. When they differ, the reason (the first entry of DH-2's
own `effective_evidence`, e.g. `"hard dependency unhealthy: toolserver"`)
is shown directly beneath, sourced verbatim from the backend, never
inferred or reworded by this page. A service that is intrinsically
healthy but effectively degraded by a dependency is never rendered as if
its own runtime state were broken.

## Dependency visibility

The service detail panel lists every dependency edge as
`RELATIONSHIP -> to_service [target_intrinsic_health badge]` (e.g.
`HARD -> toolserver [UNHEALTHY]`), reusing DH-2's `dependencies[]` array
verbatim -- no graph library was added; a simple list is what section 9
of the DH-3 brief asked for, and this project has no existing graph
library to justify introducing one for V1.

## Evidence rendering

The detail panel's Evidence section renders DH-2's `evidence[]` array
directly -- `source` and `detail` per entry, nothing summarized,
reworded, or filtered. The same is true for `intrinsic_evidence` and
`effective_evidence` wherever they're shown.

## UNKNOWN / incomplete metadata

`unknown` is rendered with `StatusBadge`'s existing neutral/gray styling
(already the color that status got before this page existed -- not a new
color language). A service's `Metadata` cell shows `Complete` or
`Partial (<missing field names>)`, read directly from DH-2's
`completeness.missing_fields` -- never guessed, never silently upgraded
to "complete" or downgraded to an error.

## Third-party / unknown-ownership services

The Repository column and detail panel render `Unknown ownership` (a
plain, non-alarming style) whenever `repository` is `null` -- entirely
independent of the health badges next to it. A third-party infrastructure
service (MySQL, Redis, Prometheus, ...) with unknown OmniBioAI repository
ownership but a `healthy` status renders exactly that: unknown ownership,
healthy service -- the two facts are never conflated.

## Error / unavailable states

| Condition | Rendering |
|---|---|
| Loading | `LoadingState` |
| `401` | `SessionExpiredState` (a stale/invalid session is a different fact from a permission denial -- reuses the same distinction `BillingPage.tsx`'s `classify()` already established via `format.ts::classifyAuthError`) |
| `403` | "You are not authorized to view deployment health." |
| `503` (`STATUS_UNAVAILABLE`, DH-2's own Compose-unavailable response) | "Deployment health data is unavailable." -- no summary cards, no service table |
| Network error / invalid response shape | "Deployment health unavailable." with a Retry action |
| Empty `services: []` | The summary cards still render (all zero) plus an explicit `No services reported` empty state -- not treated as an error |

None of these ever renders a default-green summary or implies health from
missing data.

## Read-only verification

No mutating control exists anywhere on this page -- no restart/stop/
start/kill/delete/recreate/deploy/rollback/scale/cancel button, no
Docker/Slurm control, no credential or certification-override action.
`DeploymentHealthPage.test.tsx` asserts this directly (`no destructive or
mutating controls` test, scanning rendered text for the full forbidden
list) rather than relying on code review alone.

## Security

The page never reads Studio Compose or any filesystem directly -- every
field comes through `fetchDeploymentHealth()` (DH-2's own contract).
Nothing rendered here can contain a credential, token, JWT, password,
environment value, absolute developer path, container ID, backend
handle, Slurm job ID, or tenant-private identifier, because DH-2 itself
never returns any of those (see `DEPLOYMENT_HEALTH_DH2.md`'s own Security
section) -- this page has no separate redaction responsibility of its
own beyond not inventing a new field that reads something DH-2 doesn't
expose, which it doesn't.

## DH-4 boundary

DH-3 is UI-only. Wiring the real deployed `DEPLOYMENT_HEALTH_COMPOSE_PATH`
in production, any credentialed live certification run, and Studio
deployment changes all remain out of scope here, same as they were for
DH-2.
