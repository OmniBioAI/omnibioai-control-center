# PR E2 — Admin Console Enterprise UX Hardening

Status: implemented, not yet committed (review gate — see final report).

## Scope decision

Audited all 14 listed pages against 11 consistency dimensions (loading/
empty/error states, permission-denied messaging, table layout, headers,
breadcrumbs, filters, pagination, accessibility, responsive behavior).
Found real, concrete inconsistencies across nearly every dimension —
full findings below.

**Deliberately not attempted**: a full redesign of `OrganizationsPage`,
`OrganizationDetailPage`, `UsersPage`, `UserDetailPage` onto the shared
design system (`SectionHeader`/`DataTable`/`EmptyState`/`classify()`).
These are the four oldest, highest-traffic, most complex pages in the
app, predating the Phase 2 design system entirely. Bringing them fully
into line would be a near-total rewrite of core CRUD surfaces — real
redesign risk, not hardening, and squarely inside this PR's own "STOP
if existing behavior would change unexpectedly" rule. Recommended as
its own future PR, not attempted here.

## What was fixed

### 1. Shared utilities extracted (new files)

- **`src/format.ts`**: `formatDate` (full timestamp), `formatDateOnly`
  (date-only), `formatDateTime` (explicit Intl options + "Not
  available" fallback), `classifyAuthError` (401/403/404/other).
  Replaces **17 independent, near-identical implementations** found
  across the codebase (confirmed identical by direct comparison before
  extraction, not assumed) — every call site now imports one of these
  instead of reimplementing it. Two of the seventeen were genuinely
  different on purpose (Billing's date-only vs. everyone else's
  timestamp) and were *not* forced to match — see the file's own
  comments.
- **`src/components/ui/Pagination.tsx`**: replaces **4 byte-for-byte
  identical copies** (`OrganizationsPage`, `UsersPage`,
  `AuditLogsPage`, `BillingPage`).
- **`src/components/ui/BackLink.tsx`**: replaces **6 near-identical
  copies** (`BillingPage` — already had the right shape, moved as-is;
  `OrganizationDetailPage`, `UserDetailPage`, `OrganizationMFAPolicyPage`,
  `SSOSettingsPage`, `ServiceAccountsPage`). Three of the six previously
  hardcoded a generic "← Back" instead of a destination-specific label
  — upgraded to match the "← Back to Organizations" convention
  `OrganizationDetailPage` already established for the identical
  interaction. A real, small, unambiguously-better label change, not a
  new behavior.
- **`src/components/ui/SessionExpiredState.tsx`**: the rendering half of
  the 401 fix below, shared across every page that needed it.

### 2. 401 vs. 403 vs. 503 — the core "standardize permission UX" fix

Audited every page's error-classification logic directly. Found:
- **4 pages (my own A1–A4 work) actively conflated 401 into the same
  "Permission denied" copy as 403** — `ToolExecutionPage`,
  `AIModelsPage`, `WorkflowsPage`. This is exactly the misleading
  pattern this PR's brief warns against (a session issue mislabeled as
  a permissions problem). **Fixed** — all three now render a distinct
  "Session expired" state on 401.
- **`RAGPage` also conflates 401/403** — audited and **deliberately left
  unchanged**. `/rag/studies`/`/rag/cache-stats` are answered via a
  control-center-held service credential, not the viewing admin's own
  token (see `rag.ts`'s own module comment) — a 401/403 there reflects
  the *service credential's* state, not the admin's session, so
  distinguishing them the way every other page does would be
  incorrect, not an improvement. Not touched.
- **`BillingPage`/`SubscriptionPage`**: previously had no 401 handling
  at all — a 401 fell into the generic error bucket, showing a raw
  `"... 401"` string. **Fixed** — extended `LoadState<T>` with a
  `'session'` variant across all 6 state machines (4 in `BillingPage`,
  2 in `SubscriptionPage`).
- **`OrganizationMFAPolicyPage`, `SecurityDashboardPage`,
  `SSOSettingsPage`, `ServiceAccountsPage`**: already correctly
  distinguish 403/404 from generic errors (no misleading label found),
  but likewise had no dedicated 401 treatment. **Not extended in this
  PR** — flagged as a smaller follow-up, deprioritized in favor of
  completing the higher-value items above given this PR's already-large
  surface area. Not a "misleading" bug like the A1–A4 conflation was,
  just a missed nicety.
- **4 pages with no `classify()` at all** (`OrganizationsPage`,
  `OrganizationDetailPage`, `UsersPage`, `UserDetailPage`) still show
  raw `"<path> <status>"` strings on any failure. **Not fixed** — same
  reasoning as the "deliberately not redesigned" decision above; adding
  real classification to these pages means touching their core
  data-loading logic, which is exactly the higher-risk territory this
  PR is avoiding for these four.

### 3. Missing retry actions

`TeamsPage` and `RolesPage` (2 sites) rendered `<ErrorState message=.../>` without `onRetry`, unlike every other page in this app that classifies/reports an error. Both were using an *inline* `useEffect` callback that couldn't be re-invoked — extracted into named `load`/`loadOrgs` functions (same convention every other page already follows) so `onRetry` has something to call. No change to the fetch/state logic itself.

### 4. Accessibility

- `UsersPage`'s and `OrganizationTable`'s clickable `<tr onClick>` rows had no `role`, `tabIndex`, or key handler — mouse-only. Added `role="button"`, `tabIndex={0}`, `onKeyDown` (Enter/Space), and `aria-label` to both — additive only, existing `onClick` unchanged. (`OrganizationTable` already had a keyboard-reachable equivalent via its Actions-column button; this makes the whole row equally accessible rather than relying on a caller discovering that button.)
- No other icon-only-button-without-`aria-label` or input-without-`label` issues found — the newer PR11.x pages (`SSOSettingsPage`, `ServiceAccountsPage`) already have thorough field-level a11y wiring.

### 5. Responsive

`OrganizationsPage`'s platform-admin search form was missing `flexWrap: 'wrap'`, unlike the identical-purpose form on `UsersPage` (which already had it) — real overflow risk on a narrow viewport. Fixed with a one-line style addition.

### 6. Placeholder cleanup (separate mid-turn request, folded in here since it touches the same files)

Re-verified PR D's `sessions`/`plugins`/`integrations` findings against current source (not assumed carried-over):
- **`sessions`**: still no backend anywhere in `omnibioai-auth` — confirmed, left Coming Soon.
- **`integrations`**: still just the hardcoded Discord webhook, no CRUD — confirmed, left Coming Soon.
- **`plugins`**: still the exact same GHCR `omnibioai-plugin-*` concept, still fully covered by `DockerPage`'s live "Plugin Docker Images" tab — confirmed. **Removed** the redundant nav item (not flipped to functional, not relabeled-in-place) — same precedent as PR B's `licenses`/`usage` removal. Cleaned up the now-dead `PageKey` union member and `SidebarNav`'s orphaned `Puzzle` icon entry (same "excess property" `tsc` requirement PR B already established).

### Explicitly not done (flagged, not implemented)

- Search/filter UI for `AIModelsPage`'s already-supported `task`/`model_name` query params (`model_registry.ts`'s `ModelListFilters` is wired end-to-end but never called with arguments). Real opportunity, deprioritized given this PR's already-large scope.
- Consolidating the 4 independent "plain colored text status" implementations (`BoolText` ×2, `StatusText`, the inline SSO-enabled text in `OrganizationTable`) into one shared badge-style component. A real duplication finding, but a visual-design decision (pill vs. plain text) beyond what a pure hardening pass should decide unilaterally.
- Adding 401-specific handling to `OrganizationMFAPolicyPage`/`SecurityDashboardPage`/`SSOSettingsPage`/`ServiceAccountsPage` (see §2).
- `OrganizationDetailPage`'s `MembersRolesCard` silently rendering nothing on any fetch failure (including a 403) — a real inconsistency (identical permission gaps are silent here, explicit everywhere else), but fixing it requires a product decision about what that silent state should say, not a mechanical fix.
