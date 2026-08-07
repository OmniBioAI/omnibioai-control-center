# PR E1 — Admin Settings Integration

Status: implemented, read-only.

## What this PR does

Implements `docs/pr-d-admin-placeholder-audit.md §3.4`'s Category B
finding: `omnibioai-auth` already has a complete, permissioned
platform-config backend (`GET/PUT /auth/config`, `GlobalConfig`) that
nothing in the ecosystem — not Admin Console, not either Electron
desktop app — had ever surfaced. This PR proxies the read side and adds
a page for it, exactly the pattern PR A1–A4 already established for
other already-existing-but-unsurfaced backends.

## Scope decision: read-only

`omnibioai-auth`'s `PUT /auth/config` (gated by `manage_config`, a real
pre-existing seeded permission) can set a platform-wide LLM API key and
cloud credentials. Per explicit direction before implementation began,
this PR ships **read-only only** — the proxy has no `PUT` route, the
page has no edit form. This follows the same "read-only first" discipline
PR A1 (Tool Execution) and PR A3 (Workflows) already applied to their
own services' write endpoints, deliberately, not as an oversight. A
credential-input UI (masked fields, confirm-before-submit, etc.) is real
additional design surface that deserves its own PR and its own review,
not a rider on the read side.

## Backend

`routes_platform_config_proxy.py` (new file): `GET /auth/config` →
`omnibioai-auth`'s own `GET /auth/config`. Deliberately **not** added to
the existing `routes_auth_proxy.py`, for the same reason
`routes_org_proxy.py`'s own module comment already documents for the
identical situation: `routes_auth_proxy.py`'s scope is session-flow
routes (login/validate/refresh/logout) that forward the
`omnibioai_session` cookie, never the caller's bearer token — this route
needs the opposite (forward the token, no cookie involved), so it gets
its own small file with the standard `_proxy(path, request)` shape every
other proxy router in this codebase already uses (`IAM_URL` env var,
same default every IAM-facing proxy already shares).

No authorization decision is made here — `GET /auth/config` requires
only a valid token upstream, no permission (confirmed by reading
`omnibioai-auth/app/api/routes_config.py` directly). `GlobalConfigOut`
never echoes credential values regardless of caller role (`has_llm_api_key`/
`has_cloud_credentials` booleans only) — this proxy relays that shape
unmodified, it doesn't add or strip anything.

## Frontend

- `platform_config.ts`: `PlatformConfig` type mirroring `GlobalConfigOut`
  field-for-field, `fetchPlatformConfig()`. No update function — no write
  path exists to call yet.
- `PlatformSettingsPage.tsx`: flat page (no org picker — the config is
  genuinely platform-wide; no tabs — few enough fields for one view),
  four cards (AI/LLM, Cloud, Storage Paths, Last Updated), all rendering
  real fields only. A 401 renders a distinct "Session expired" state
  (not the "Permission denied" copy every org-scoped page in this app
  uses) — this endpoint has no permission to be denied, a failure here
  means the caller's own session went stale, not a missing grant.
- `navigation.ts`: `settings` flipped to `functional: true`, gated by
  `hasAdminAccess()` (same audience as the rest of the Operations-family
  pages — Infrastructure/Workflows/Tool Execution/AI Models/RAG).
- `AdminApp.tsx`: wired flat, same `canSeeOps`-gated shape as
  `tool-execution`/`ai-models`/`workflows`/`rag`, no new `RenderCtx`
  field needed.
- `AdminApp.test.tsx`: the recurring "renders Coming Soon for an
  unimplemented module" test used `Settings` as its stand-in example
  since PR B (when `Licenses`/`Usage` were removed) — updated to
  `Sessions`, the next genuinely-still-Coming-Soon item per PR D's own
  Category C finding.

## Testing

**Backend** (`test_routes_platform_config_proxy.py`, 7 tests): success
forwarding, Authorization forwarding, the unset-config case (every field
null/false — a valid, common state, not an error), 401 propagation,
upstream unreachable → 503, non-JSON upstream response, and one test
that pins down the credential-shape invariant directly (`llm_api_key`/
`cloud_credentials` never appear in the response body, because upstream
never sends them — nothing for this proxy to redact).

**Frontend** (`PlatformSettingsPage.test.tsx`, 6 tests): loading, the
all-"Not configured" empty state, real-value rendering (plus an explicit
assertion that no credential-shaped string ever renders), the
session-expired state on 401, generic error + retry, and one test
confirming there is no edit control anywhere on the page — pinning down
this PR's read-only scope so a future PR can't silently regress it back
to read-only by accident either.

## Verified

- `pytest`: 886 passed, 99.79% coverage (≥98% required).
- `ruff check`: clean except the same pre-existing `RUF013` convention
  every proxy test file in this repo already has.
- `npm test`: 349 passed / 30 files.
- `npm run build:admin` / `build:control`: both succeed; `dist-control`
  byte-identical to PR C's build — `PlatformSettingsPage.tsx` isn't
  reachable from `ControlApp.tsx` at all.
- No `omnibioai-auth` changes. No unrelated files.
