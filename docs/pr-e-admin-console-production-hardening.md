# PR E — Admin Console Production Hardening

Status: implemented, not yet committed (review gate — see final report).

## Scope

A production-readiness audit of the Admin Console as it stands after
A1-A4/B/C/E1/E2 -- navigation integrity, proxy-route hygiene, frontend
auth-state handling, loading/error/empty consistency, and production
configuration (CORS, API URLs, security headers, environment handling)
-- followed by targeted fixes only. No redesign, no new APIs beyond
what already existed, no IAM/permission changes, Sessions/Integrations
left untouched (still `functional: false`, still documented).

## 1. `navigation.ts` audit -- clean, no changes

Every `functional: true` `PageKey` was checked against `AdminApp.tsx`'s
`renderPage()` switch: all 25 map to a real, imported component (no
`default: <ComingSoon/>` fallthrough for anything claiming to be
functional). The two `functional: false` items (`sessions`,
`integrations`) both carry an inline comment naming the real reason
(no backend endpoint / no CRUD entity, per PR D's original discovery,
re-confirmed current in PR E2). No fake pages, no undocumented
placeholders found.

## 2. Proxy route audit -- one real bug found and fixed (see §5)

All 15 `routes_*_proxy.py` files were read and diffed against each
other. Auth forwarding, timeout (10s, uniform), error mapping
(`httpx.RequestError` → 503, non-JSON upstream body → same status +
`{"error": ...}`), and secret handling (`RAGBIO_API_KEY`,
`RAGBIO_API_KEY`-only-when-`use_service_key`) are all consistent and
correctly scoped -- confirmed line-by-line, not sampled. No secret is
ever echoed into a response or error message; every `_API_KEY`/
`_SECRET` reference is either an env var name or a value injected only
into the outbound `Authorization` header, never logged or returned.

The proxy *routers* themselves were correct. The bug was one layer
out: nothing in front of them (nginx, Vite dev proxy) knew these four
routers existed. See §5.

## 3. Frontend authentication states

Audited every page's `LoadState`/`classify()` machinery. PR E2 already
fixed the misleading "401 shown as Permission denied" bug on
`ToolExecutionPage`/`AIModelsPage`/`WorkflowsPage`/`BillingPage`/
`SubscriptionPage`, and flagged four more pages as a known,
deliberately-deferred follow-up:

- `OrganizationMFAPolicyPage`, `SecurityDashboardPage`,
  `SSOSettingsPage`, `ServiceAccountsPage` (both its API Keys and
  OAuth Clients tabs) all correctly distinguished 403/404 from a
  generic error, but had no 401 branch at all -- a stale/invalid
  session fell into the same generic `ErrorState` as a real backend
  failure. **Fixed**, all five state machines, using the same shared
  `classifyAuthError`/`SessionExpiredState` pattern already
  established elsewhere (`ServiceAccountsPage` keeps its own local
  `classify()` since it already had bespoke 404-vs-403 copy per
  organization-membership-vs-permission distinction -- extended with a
  `'session'` branch rather than replaced, to avoid disturbing that
  existing, deliberate behavior).
- No raw `"<path> <status>"` string is shown for a 401 anywhere in the
  app after this fix. The four pages explicitly out of scope for a
  redesign (`OrganizationsPage`, `OrganizationDetailPage`, `UsersPage`,
  `UserDetailPage`) still have no `classify()` at all and still show
  raw status strings on any failure -- unchanged, per this PR's own
  "do not redesign Organizations/User pages" instruction; this was
  PR E2's documented boundary and remains one here.
- `AccessDenied` (the component the brief's "403 → AccessDenied"
  phrasing evokes) already exists and is correctly scoped:
  `AuthGate`/`AccessDenied` is the whole-app "you have no console
  access at all" gate, entirely separate from a page-level 403 on one
  organization's data, which correctly stays the existing
  `EmptyState(ShieldAlert, "Permission denied")` convention. No new
  component needed or added.

## 4. Loading/error/empty state consistency

No new inconsistency found beyond the 401 gap fixed in §3.
`LoadingState`/`ErrorState`/`EmptyState` usage is uniform across every
page audited; `TeamsPage`/`RolesPage`'s missing-retry bug was already
fixed in PR E2. Not revisiting the four legacy pages' full state
machine, per the same redesign boundary as §3.

## 5. Production configuration -- the real finding

### 5a. Missing nginx routes for A1-A4 (production-breaking, fixed)

`docker/nginx/api-proxy.conf`'s own module comment already documents
the rule: "every route registered bare/unprefixed... each top-level
path segment needs its own location here... or it's unreachable
through this nginx." PR A1-A4 added four new top-level routers
(`/tes`, `/model-registry`, `/workflow-bundles`, `/rag`) and never
added the matching `location` blocks this file's own comment warned
about. Confirmed by reading every frontend API client's actual fetch
path (`tes.ts`, `model_registry.ts`, `workflows.ts`, `rag.ts`) against
this file -- none of the four prefixes existed here.

**Concrete impact**: in the deployed topology
(`docker/nginx/control-center.conf`, host-routed on `:5174`), every
fetch from `ToolExecutionPage`, `AIModelsPage`, `WorkflowsPage`, and
`RAGPage` fell through to `location /`'s SPA fallback
(`try_files $uri $uri/ /index.html`) and received the bundle's own
`index.html` back instead of JSON. All four pages were completely
non-functional in production -- confirmed as the actual shipping
behavior, not a hypothetical, by tracing the exact request path nginx
would take. This is the most significant finding in this audit.
**Fixed**: added `location /tes`, `/model-registry`,
`/workflow-bundles`, `/rag` (plain prefix, not regex -- confirmed none
of the four pages call `window.history.pushState`, unlike
`/organizations`/`/billing`, so there's no SPA-route collision to
guard against).

### 5b. Matching gap in the Vite dev proxy (dev-only, fixed)

The identical gap existed one layer earlier: `vite.config.ts`'s dev
server proxy also never got entries for these four prefixes, so
`npm run dev` couldn't reach any of the four pages' APIs either --
the same class of gap `vite.config.ts`'s own PR13 comment already
flagged ("Missing here meant `npm run dev` 404'd... caught while
setting up a local run"). **Fixed**, same four prefixes added.

### 5c. CORS wildcard (hardening, fixed)

`backend/src/control_center/main.py` mounted `CORSMiddleware` with
`allow_origins=["*"]`. Every other backend in this ecosystem that
mounts CORS (`omnibioai-auth`'s `CORS_ALLOWED_ORIGINS`,
`omnibioai-rag`'s `_CORS_ORIGINS`) uses an explicit, env-driven
allowlist -- control-center was the one outlier, confirmed by reading
all three directly, not assumed. In the deployed topology the browser
only ever reaches this backend same-origin through nginx, so this
wasn't blocking anything functional; it's a real hardening gap (any
website could read a response from this API in a browser that reached
it directly, e.g. bypassing nginx to `:7070`). **Fixed**: replaced the
wildcard with a `CORS_ALLOWED_ORIGINS` env var, same name and
comma-separated format as `omnibioai-auth`'s, defaulting to the two
production domains (`admin.omnibioai.org`, `control.omnibioai.org`)
plus this app's own local dev ports (5173 `npm run dev`, 5174 the
nginx-fronted local build). `allow_credentials` was not touched
(stays unset/default `False`) -- nothing in this app relies on
cross-origin cookies; the login flow's `omnibioai_session` cookie is
same-origin only.

### 5d. API URLs / environment handling -- clean

Every proxy router's own `*_URL = os.environ.get(...)` default was
cross-checked against `routes_dashboard.py`'s pre-existing defaults
for the same services (`TES_URL`, `MODEL_REGISTRY_URL`,
`WORKFLOW_BUNDLES_URL`) -- all consistent, no drift, no hardcoded
production hostnames outside an env var default.

### 5e. Security headers -- not touched

No `X-Frame-Options`/`Content-Security-Policy`/`Strict-Transport-
Security` headers are set anywhere (FastAPI app or nginx config) for
either bundle. Flagged, not fixed -- adding response headers
platform-wide is a real, legitimate hardening item, but touches every
response this app serves and deserves its own reviewed change with
explicit header values decided (CSP in particular needs enumerating
every legitimate script/style/connect source, which is a product
decision, not a mechanical fix), not folded into this pass.

## 6. Bundle isolation -- verified, unaffected

Both builds still succeed after all fixes above (no frontend routing
or component changes, only two API URL prefixes added to a dev-only
config file):

```
npm run build:admin   → dist-admin/assets/index-*.js   831.45 kB
npm run build:control → dist-control/assets/index-*.js 620.52 kB
```

Re-ran `docs/admin-console-build.md`'s own verification method:

```
$ grep -c "OrganizationDetailPage\|TeamsCard\|RoleAssignmentList" dist-control/assets/*.js
0
$ grep -c "Create Team" dist-admin/assets/*.js
1
```

`dist-control` still contains zero trace of enterprise-only page code;
`dist-admin` still contains it. Isolation intact.

## Explicitly not done (flagged, not implemented)

- Security response headers (CSP/HSTS/X-Frame-Options) -- see §5e.
- Redesigning `OrganizationsPage`/`OrganizationDetailPage`/
  `UsersPage`/`UserDetailPage` onto the shared `classify()`/
  `SessionExpiredState` pattern -- explicitly out of scope per this
  PR's own instructions, same boundary PR E2 already drew.
- Implementing `sessions` or `integrations` -- explicitly out of scope
  per this PR's own instructions; both remain `functional: false`
  with their existing, re-confirmed-current documented reasons.
- Any new backend API, IAM permission, or entitlement logic -- none
  was needed; every fix in this PR is either a routing/config
  correction or a frontend classification addition using APIs that
  already existed.

## Files changed

- `docker/nginx/api-proxy.conf` -- 4 missing `location` blocks (§5a)
- `frontend/cc-ui/vite.config.ts` -- 4 missing dev-proxy entries (§5b)
- `backend/src/control_center/main.py` -- CORS wildcard → env-driven
  allowlist (§5c)
- `frontend/cc-ui/src/pages/security/SecurityDashboardPage.tsx` (+test)
- `frontend/cc-ui/src/pages/security/OrganizationMFAPolicyPage.tsx` (+test)
- `frontend/cc-ui/src/pages/identity/SSOSettingsPage.tsx` (+test)
- `frontend/cc-ui/src/pages/identity/ServiceAccountsPage.tsx` (+test)

## Test results

- Backend: `ruff check .` -- 341 pre-existing errors repo-wide, none in
  the diff's own added lines (confirmed by isolating `main.py`'s
  changed range); `pytest --tb=short -q` -- 886 passed, 99.79% coverage
  (`main.py` itself 100%), `--cov-fail-under=98` satisfied.
- Frontend: `npm run test` -- 360 passed (356 pre-existing + 4 new
  session-expired tests), 0 failed.
- Both builds (`build:admin`, `build:control`) succeed; bundle
  isolation re-verified (§6).

## Security impact assessment

- **Fixes a real production outage-class bug**: four Admin Console
  pages (Tool Execution, AI Models, Workflows, RAG/PubMed) were
  completely non-functional in the deployed environment. Not a
  security regression, but a correctness/availability one significant
  enough to note here.
- **Reduces attack surface**: CORS narrowed from any origin to an
  explicit allowlist. No functional behavior change for the real
  deployed flow (same-origin via nginx); removes the ability for an
  arbitrary third-party site to read this API's responses from a
  browser that reaches the backend directly.
- **No new attack surface added**: no new API routes, no new
  permissions, no new data exposed. The four 401-handling fixes only
  change which UI state renders for an already-401 response --
  `reportUnauthorized()` (the actual session-invalidation behavior)
  was already firing on every 401 before this change, unaffected.
- No secrets, credentials, or PII touched or newly exposed in any file
  in this diff.
