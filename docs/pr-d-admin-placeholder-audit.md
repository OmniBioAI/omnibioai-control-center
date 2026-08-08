# PR D — Admin Console Placeholder Audit (Discovery Only)

Status: **discovery only. No code changed. No branch created. No commit made.**

Scope note: this audit is read-only, matching PR D's own rules — no
navigation items renamed, removed, or flipped; no code fixed. Every
finding below was verified by reading source directly in the listed
repositories, not carried over from memory of earlier sessions.

---

## 1. `navigation.ts` audit

### Current `functional: false` entries (4 remaining)

| Key | Label | Section |
|---|---|---|
| `sessions` | Sessions | Security |
| `plugins` | Plugins | Knowledge |
| `integrations` | Integrations | Platform |
| `settings` | Settings | Platform |

### Placeholders removed since the original 11-item audit (PR B)

| Key | Label | Disposition |
|---|---|---|
| `licenses` | Licenses | Removed — superseded by Billing's Subscription tab (Category D at the time; not re-litigated here) |
| `usage` | Usage | Removed — superseded by Billing's Usage/Usage Limits tabs (Category D at the time; not re-litigated here) |

### Placeholders promoted to `functional: true` (PR A1–A4)

`workflows`, `tool-execution`, `ai-models`, `rag`, `pubmed` — all real pages now, all audited and shipped in prior PRs, not re-covered here.

### Unreachable pages

None found. Cross-checked every `functional: true` `PageKey` in
`navigation.ts` against `AdminApp.tsx`'s `renderPage()` switch: every
leaf key has a matching `case`. The one key with no case
(`infrastructure`) is a group parent with its own children
(`health`/`docker`/`ecosystem`/`config`/`llms`/`cloud`, each with its
own case) — by design, not a gap (matches `findNavItem()`'s own
"group parents excluded" contract).

### Stale labels

None found in the remaining 4 items themselves. One adjacent staleness
noted in §3.2 below (not a label issue, a docstring/behavior one) —
`routes_dashboard.py`'s `_workflow_section()` still calls
workflow-bundles unauthenticated, based on the same "unauthenticated
upstream" assumption PR A3 found to be false. Flagged again here since
this audit re-touched the surrounding area; still out of scope to fix
under PR D's own discovery-only rule.

---

## 2. Repository audit summary

| Repository | Relevant to remaining placeholders? | What was found |
|---|---|---|
| `omnibioai-control-center` | Yes | `DockerPage.tsx`'s existing "Plugin Docker Images" tab (`GET /docker/plugin-images`) — resolves the `plugins` ambiguity flagged in the original audit. Discord webhook wired directly (`checks/gpu.py`, `checks/disk.py`, `core/runner.py`, `notifications/discord.py`) — no CRUD. |
| `omnibioai-auth` | Yes | `GET/PUT /auth/config` (`app/api/routes_config.py`) — a real, previously-unnoticed platform-wide settings API. No `RefreshToken`-listing route anywhere (confirmed: `RefreshToken` only referenced in `app/services/auth_service.py`, never exposed). |
| `omnibioai-billing` | No new finding | No webhook/integration receiver, no settings endpoint beyond what Billing's existing tabs already cover (PR B). |
| `omnibioai-policy-engine` | Not applicable | `POST /evaluate` only — a synchronous authorization-decision API, no browsable state. Not a candidate for any of the 4 placeholders; would only become relevant to a hypothetical future Policy Management UI (see §5 security note). |
| `omnibioai-hpc-policy-engine` | Not applicable | `POST /check`, `POST /evaluate` only — same shape as above, HPC/GPU quota decisions, no browsable state. |
| `omnibioai-rag` | Confirms existing finding | `DISCORD_WEBHOOK_URL` also wired here (`ragbio/api/server.py`) — same single hardcoded webhook, not a second integration. |
| `omnibioai-model-registry` | No new finding | — |
| `omnibioai-workflow-bundles` | Confirms existing finding | `RUNNER_IMAGE` default references `ghcr.io/omnibioai/omnibioai-plugin-workflow-runner` — same GHCR plugin-image family as `plugins`, not a second "plugins" concept. |
| `omnibioai-tes` | No new finding | — |
| `omnibioai` (base repo) | Confirms existing finding | `DISCORD_WEBHOOK_URL` also wired here (`tasks.py`, `users/signals.py`) — same single webhook, ecosystem-wide, still no management API. |

---

## 3. Per-item classification

### 3.1 `sessions` — Security section

1. **Navigation item**: `{ key: 'sessions', label: 'Sessions', functional: false }` — Security section, no `visible` gate (shows for everyone, per the file's own "Coming-soon items have no visible gate" convention).
2. **Current state**: Coming Soon, unchanged since Phase 2.
3. **Backend/API availability**: **None.** `RefreshToken` is a real DB model (`app/db/models.py`) but has zero routes exposing it anywhere in `omnibioai-auth` — confirmed by grepping every file under `app/api/` and `app/services/`; the only reference outside the model definition is internal use in `auth_service.py` (issuing/validating tokens), never a list/revoke endpoint.
4. **Existing implementation location**: None, anywhere in the audited repositories.
5. **Security model**: N/A — nothing to gate. If built, this would need a new `omnibioai-auth` endpoint (e.g. `GET /users/{id}/sessions`, `DELETE /sessions/{id}`) and a new permission decision (self-service "your own sessions" vs. admin "any user's sessions" are different access models) — a product decision, not a UI task.
6. **Recommended action**: **Category C — leave Coming Soon.** No amount of control-center-side work can populate this; it requires new `omnibioai-auth` API surface first.
7. **Future PR suggestion**: Not control-center's to schedule. If prioritized, it starts in `omnibioai-auth` as a backend PR (new endpoint + permission model decision), with a control-center admin PR only after that ships — mirrors exactly the shape PR A1–A4 followed for already-existing backends, inapplicable here since there is no backend yet.

### 3.2 `plugins` — Knowledge section

1. **Navigation item**: `{ key: 'plugins', label: 'Plugins', functional: false }` — Knowledge section, alongside `rag`/`pubmed` (both now real).
2. **Current state**: Coming Soon. The original capability-parity audit flagged this as ambiguous — "does this mean the same thing as DockerPage's Plugin Docker Images tab, or something distinct?" — and left it unresolved pending clarification.
3. **Backend/API availability**: **Yes — already implemented and live.** `GET /docker/plugin-images` (`routes_docker.py`) auto-discovers every plugin from `plugins/*/plugin.json` manifests in the base `omnibioai` repo, resolves each to its GHCR image (`ghcr.io/omnibioai/omnibioai-plugin-{slug}:latest`), and reports local presence/size. This is the **only** "plugin" concept found anywhere across all 9 audited repositories — `org_packages.txt`/`plugin_sync_report_*.txt` at the workspace root and `omnibioai-workflow-bundles`' own `RUNNER_IMAGE` default both reference the exact same GHCR `omnibioai-plugin-*` naming convention, not a second, distinct system.
4. **Existing implementation location**: `DockerPage.tsx`, "Plugin Docker Images" tab — reachable today via Operations → Infrastructure → Docker (`functional: true` since before this PR series).
5. **Security model**: `hasAdminAccess()`-gated (same as the rest of Infrastructure), enforced by `platform.manage_infra` on the backend router (`docker_router` is mounted with `dependencies=[Depends(require_permission("platform.manage_infra"))]`).
6. **Recommended action**: **Category D — superseded, do not build.** This ambiguity is now resolved: the two are the same concept. Building a second "Plugins" page under Knowledge would duplicate Docker's existing tab exactly, the same failure mode PR B avoided for Licenses/Usage.
7. **Future PR suggestion**: A relabel/link PR (not a build PR) — either remove the `plugins` nav item and note in Docker's own copy that plugin images live there, or turn `plugins` into a lightweight deep-link into Docker's Plugin Images tab (same "distinct URL into an existing page" pattern `billingOrgIdFromPath()` etc. already establish in `AdminApp.tsx`). Small enough to fold into a future navigation-cleanup PR alongside `sessions`/`integrations`/`settings` decisions, not urgent on its own.

### 3.3 `integrations` — Platform section

1. **Navigation item**: `{ key: 'integrations', label: 'Integrations', functional: false }` — Platform section.
2. **Current state**: Coming Soon.
3. **Backend/API availability**: **Partial, and not in the way the label implies.** `DISCORD_WEBHOOK_URL` is a single, hardcoded, environment-variable-configured webhook, wired directly into multiple services' notification call sites: `omnibioai-control-center` (`checks/gpu.py`, `checks/disk.py`, `core/runner.py`, `notifications/discord.py`), `omnibioai-rag` (`ragbio/api/server.py`), and the base `omnibioai` repo (`tasks.py`, `users/signals.py`). There is no CRUD API for it (no way to view, add, remove, or add a second integration target), no per-organization scoping, and no other integration type (Slack, generic webhooks, OAuth-based third-party connections) exists anywhere in the audited repositories.
4. **Existing implementation location**: Nowhere UI-facing. It's infra-level configuration, not a manageable entity.
5. **Security model**: N/A — there's no endpoint to gate. Whoever can set environment variables on the relevant deployments controls this today; no application-layer authorization exists because there's no application-layer surface at all.
6. **Recommended action**: **Category C for a general "integrations platform"; a narrow Category B exists if the ask is scoped down.** As a generic integrations page ("manage all your third-party connections"), this is Category C — nothing to build against. As a narrow "let an admin view/edit the Discord webhook URL" feature, a thin config-write endpoint could be added — but that endpoint doesn't exist yet either, so even the narrow version starts at zero backend, not partial.
7. **Future PR suggestion**: Two independent, differently-scoped options for whoever prioritizes this — (a) leave as Coming Soon indefinitely (it may never warrant more than one hardcoded webhook), or (b) a small, explicitly-scoped backend PR adding one config endpoint (e.g. extending `omnibioai-auth`'s `GlobalConfig` — §3.4 — with a `discord_webhook_url` field, reusing the exact same `manage_config` permission already seeded) followed by a UI PR. Do not scope this as "build an integrations platform" — nothing in the current ecosystem asks for one.

### 3.4 `settings` — Platform section

1. **Navigation item**: `{ key: 'settings', label: 'Settings', functional: false }` — Platform section.
2. **Current state**: Coming Soon. The original audit reported "no backend found" here — **that finding does not hold up on this re-audit.**
3. **Backend/API availability**: **Yes — a real, complete, previously-missed backend.** `omnibioai-auth`'s `app/api/routes_config.py` exposes `GET /auth/config` (any authenticated user) and `PUT /auth/config` (gated by `manage_config`, a real, pre-existing, seeded permission — confirmed in `app/core/permission_names.py` and `app/db/init_admin.py`, already granted to the admin role, not something that would need inventing). The schema (`app/schemas/config.py`) covers platform-wide LLM provider + API key (write-only, never echoed back — `has_llm_api_key` boolean only), cloud provider + credentials (same write-only pattern), and work/data directory paths.
4. **Existing implementation location**: **None.** Grepped `omnibioai-studio`, `omnibioai-launcher`, `omnibioai-control-center`, and `omnibioai-dev-hub` for any consumer of this endpoint or its response fields (`llm_provider`, `has_llm_api_key`, `cloud_provider`, etc.) — the only hit was a one-line comment in `omnibioai-studio/docker-compose.yml` about credential encryption, not a UI. This is a fully-built, fully-permissioned backend with **zero** frontend anywhere in the ecosystem.
5. **Security model**: Reads open to any authenticated user (mirrors the "read is cheap, write is gated" pattern this app already uses elsewhere, e.g. Billing); writes gated by `manage_config`, already seeded on the admin role, requiring no new permission — the exact "reuse an existing permission, add zero new ones" posture every PR A/B/C in this series has followed. Credentials are never returned in any response shape (`GlobalConfigOut` has no credential fields, "regardless of caller role" per its own docstring) — a real, already-designed-in write-only-secret pattern, not something an Admin Console PR would need to invent.
6. **Recommended action**: **Category B — reclassify from "truly missing" to "backend exists, UI/API integration missing."** This is the strongest, most concrete finding in this audit: a genuinely production-ready backend that nothing in this ecosystem has ever surfaced.
7. **Future PR suggestion**: A PR directly analogous to A1–A4's own shape — `routes_platform_config_proxy.py` (or extend an existing IAM-adjacent proxy router) forwarding to `omnibioai-auth`'s `GET/PUT /auth/config`, a `PlatformSettingsPage.tsx` with the same loading/denied/error-state conventions every prior page in this series established, `settings: functional: true` in `navigation.ts`. Note for that PR's own scope: this is a genuine **write** surface (unlike every read-only page A1–A4 built) — the PR should explicitly decide whether to include the `PUT` in its first cut or ship read-only first and defer the write form, the same "read-only first, write later" discipline A1 (Tool Execution) and A3 (Workflows) already applied to their own services' write endpoints.

---

## 4. Summary

**Remaining placeholder count: 4** — `sessions`, `plugins`, `integrations`, `settings`.

| Item | Category | One-line disposition |
|---|---|---|
| `sessions` | C | No backend anywhere; needs a new `omnibioai-auth` endpoint first |
| `plugins` | D | Superseded — identical to Docker's live Plugin Images tab |
| `integrations` | C (B if narrowly rescoped to just Discord) | No manageable backend for a general integrations platform |
| `settings` | **B** | Real, complete, permissioned backend (`omnibioai-auth`'s `GlobalConfig`) with zero UI anywhere — the one genuine "build this next" candidate |

### Recommended PR sequence after this discovery

1. **PR E-adjacent or standalone: Platform Settings (`settings`)** — the only item with a real backend ready to consume. Same proxy+page+nav pattern as A1–A4. Decide read-only-first vs. read+write scope explicitly before starting (see §3.4.7).
2. **Plugins nav cleanup (`plugins`)** — small, low-risk: relabel/deep-link into Docker's existing tab, or remove the redundant nav item. Not a build PR.
3. **Sessions and Integrations** — leave as Coming Soon. Neither has a backend to build against; both would need to start as a backend PR in a different repository (`omnibioai-auth` for sessions) before any control-center work makes sense.

### Security concerns

- **None found that require immediate action.** No placeholder in this audit conceals a security gap that's currently being papered over — each one is either genuinely backend-less (`sessions`, `integrations`) or already correctly gated where it lives (`plugins`, via Docker's existing `platform.manage_infra` check).
- **One thing worth deliberate awareness, not action**: `settings`' write path (`PUT /auth/config`) can set `cloud_credentials` and `llm_api_key` platform-wide. If PR-suggestion #1 above is picked up, that PR's own security review should confirm the proxy forwards the caller's token unmodified (no control-center-side credential handling) — the same "never touch the secret, just relay" posture `routes_billing_proxy.py` etc. already established — rather than assuming it's automatically safe because the backend already gates it.
- **`omnibioai-policy-engine`/`omnibioai-hpc-policy-engine`** exist and are real, callable authorization-decision services — but per this whole PR series' explicit rule against introducing entitlement enforcement, and since neither maps to any of the 4 current placeholders, no action is recommended here. Flagging only so a future "should Admin Console have a Policy Management surface" conversation starts from an accurate picture of what exists, not from scratch.

### Capabilities that should intentionally remain unavailable

- **`sessions`**: intentionally left alone until `omnibioai-auth` decides on and ships a session-listing/revocation API and its own access model (self-service vs. admin-initiated revocation are different security decisions, not a UI detail).
- **A general-purpose `integrations` platform**: intentionally not scoped as a build target. Nothing in the current ecosystem asks for more than the single Discord webhook that already exists; building a platform for a hypothetical second integration would be speculative scope, not consolidation of something real.
- **Any Policy Engine / HPC Policy Engine admin surface**: intentionally out of consideration here. Both are real, reachable services, but exposing their decisions/rules in Admin Console would be entitlement-enforcement-adjacent surface area — explicitly excluded from this entire PR series (A1–PR C all carried "no entitlement checks" as a hard rule) and deserving its own explicit product decision, not an incidental add-on to a Coming Soon cleanup.
