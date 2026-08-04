# Admin Console Phase 2 — Architecture Findings

Status: review complete, informed a shell already under construction on `feature/admin-console-shell`. See [Implementation](#implementation) for what changed after this review and why.

This is the pre-code architecture review requested for Phase 2 ("Enterprise Admin Console Foundation"). It documents the state of `omnibioai-control-center`'s frontend (`frontend/cc-ui`) as of the Admin Console Dual Build merge (PR #8), across the areas the phase brief asked for, then records the gaps this phase needed to close.

## 1. Layout (before)

`AdminApp.tsx` rendered a single flat column: `<Header>` (tab strip) at the top, the active page's content directly beneath it, full width, no persistent chrome. There was no shell abstraction — each of `ControlApp.tsx` and `AdminApp.tsx` built its own top-to-bottom layout inline in the app component itself. Nothing was reusable across a hypothetical third surface.

## 2. Navigation (before)

`components/Header.tsx` rendered a single-row, unsectioned tab strip — a flat list of `<button>`s, one per page (`Health`, `Docker`, `Ecosystem Report`, `Config`, `LLMs`, `Cloud`, plus `Organizations`/`Users` for `AdminApp` only). Tab visibility was gated ad hoc with boolean props (`showOrganizationsTab`, `showUsersTab`) passed down from `AdminApp.tsx`'s own permission checks — there was no single source of truth for "what pages exist and who can see them." Adding a page meant adding a prop, a case in the tab union, and a case in the render switch, in three separate files. There was no capacity to represent a page that doesn't exist yet ("Coming Soon") or to group related pages under a section — the flat list was the ceiling of what this structure could express, and the task's 7-section taxonomy (Administration/Operations/Security/Business/Knowledge/Platform) had no home.

`ControlApp.tsx` shared the same `Header.tsx`, with the enterprise tabs compiled out (see `docs/admin-console-build.md`).

## 3. Header (before)

`Header.tsx` combined the tab strip, a live status pill, and Refresh/Generate Report controls into one component with no separation between "navigation" and "page-contextual actions." There was no breadcrumb (a flat tab strip doesn't need one), no global search, no notifications, no org-context indicator, no profile menu — sign-out was a bare button. None of the top-bar affordances the task's shell spec asks for existed.

## 4. Sidebar (before)

None, functionally. Two dead components — `components/Sidebar.tsx` and `components/StatsBar.tsx` — existed in the tree with zero import sites anywhere in `src/` (confirmed by `git grep`, not assumed): leftover scaffolding from an earlier design that `Header.tsx`'s tab-strip approach superseded without ever being deleted. `components/TopBar.tsx` was similarly orphaned. All three were dead weight, not a working alternative layout.

## 5. Dashboard (before)

No landing dashboard existed. `AdminApp.tsx`'s default tab was `health` for an ops-capable user (or `organizations`/`users` as a fallback) — i.e., the "Overview" experience was literally the Health ops page. There was no aggregate view of organizations, users, or platform status in one place.

## 6. Shared components (before)

No design-system layer. Every page (`OrganizationsPage.tsx`, `UsersPage.tsx`, the six ops pages) hand-rolled its own page wrapper, its own `<table className="data-table">` markup, its own empty/loading/error states inline. `index.css` supplied CSS custom properties (`--bg`, `--accent`, `--border`, …) and a `.data-table` class that every page applied by hand, but there was no typed component wrapping any of it — copy-paste was the reuse mechanism.

## 7. Authentication flow (existing, reused unchanged)

`auth.ts` + `AuthGate.tsx` already implement a complete, well-hardened session model: access token in `localStorage`, refresh token as a server-set `HttpOnly` cookie (never JS-reachable — see `auth.ts`'s own PR13 note), silent refresh scheduled off the token's decoded `exp` claim, and a `UNAUTHORIZED_EVENT` that any 401 response anywhere in the app can dispatch to drop back to the login screen without each call site knowing about auth. This is solid infrastructure and Phase 2 correctly treats it as a boundary not to touch.

## 8. Permission model (existing, reused unchanged)

Four checks, all in `auth.ts`, all reading directly off the validated session — no new permission ever introduced:
- `hasAdminAccess()` — the `admin` role, gates the six ops pages.
- `hasPlatformAdminAccess()` — the `manage_all_orgs` permission.
- `hasOrganizationsAccess()` — admin OR platform-admin OR a non-null `orgId` (Phase 3 PR2's deliberate widening).
- `hasPlatformAdminAccess()` again for Users (platform admin only).

Before this phase, these were consumed as three boolean props threaded into `Header.tsx`. The gap wasn't the permission model itself (it's correct and already tested — `auth.test.ts`) but the fact that nothing else in the app had a structured way to ask "is this nav destination visible" without re-deriving the boolean inline.

## 9. Theme support (before)

Dark-only. `:root` in `index.css` defined one fixed palette; no `data-theme` mechanism, no toggle, no light tokens.

## 10. Responsive behavior (before)

None. `git grep -c '@media' src/index.css` on the pre-Phase-2 stylesheet returns zero matches — every layout in the app assumed a desktop viewport (fixed pixel widths, no breakpoints anywhere).

## 11. Existing design system (before)

Tokens only (`index.css` custom properties), no components. See §6.

---

## Implementation

The findings above shaped a shell already in progress on `feature/admin-console-shell` (uncommitted at review time): `components/shell/*` (`AppShell`, `SidebarNav`, `TopAppBar`, `Breadcrumb`, `GlobalSearch`, `NotificationsMenu`, `OrgSelector`, `ProfileMenu`, `ThemeToggle`, `Footer`) and `components/ui/*` (`PageContainer`, `SectionHeader`, `Card`, `StatCard`, `DataTable`, `Button`, `EmptyState`, `ComingSoon`, `LoadingState`, `ErrorState`, `ActionToolbar`), plus `navigation.ts` as the single source of truth for the 7-section nav tree and a redesigned `DashboardPage.tsx`. This review verified that work against the brief and against the actual running app, and closed three gaps found in the process:

1. **Topbar overflow below the 768px breakpoint.** `extraActions` (the status pill + Refresh/Generate Report controls) and the `GlobalSearch` box both had inline `style={{ display: 'flex' }}` — which always wins over a stylesheet rule of equal-or-lower specificity, so the `display: none` meant to hide them on narrow viewports silently never applied. The fixed-width right-hand icon cluster (`flexShrink: 0`) then forced the breadcrumb/menu-toggle side to zero width instead, and the whole bar overflowed the viewport. Fixed by adding `!important` to both rules, matching the pattern `index.css` already used for `.shell-menu-toggle` for the same reason.
2. **`.shell-org-selector-label` was dead CSS.** The rule hiding it was scoped under `.shell-sidebar`, but `OrgSelector` (and its `.shell-org-selector-label` span) only ever renders inside `TopAppBar` — the selector could never match. Added a correctly-scoped rule.
3. **Profile email squeezed out the breadcrumb entirely on mobile**, once (1) and (2) freed enough width to reveal it as the next-worst offender. Same fix pattern: labeled the email `<span>` and hid it at the same breakpoint, leaving avatar + chevron.

All three were verified by rendering the actual app (Playwright against the Vite dev server, session mocked at the network boundary — no component code touched to fake it) at a 390×844 viewport before and after.

### Design decisions carried through unchanged from the in-progress work

- **`ControlApp`/`Header.tsx` are untouched** (`git diff` confirms zero changes to either file). This phase is scoped to `AdminApp` only, per the dual-build architecture — `control.omnibioai.org` keeps its flat tab strip.
- **Every functional nav destination reuses an existing page and its existing permission gate** — `navigation.ts` is the single new source of truth `SidebarNav`, the breadcrumb, and `AdminApp`'s render switch all read from, but it introduces no new permission logic, only structures the four checks in §8.
- **Non-functional destinations render the shared `<ComingSoon>`**, never a fabricated page — per the phase's explicit scope boundary.
- **Placeholder dashboard data (AI Models, Workflows, TES Jobs, Knowledge Base, Billing, Audit) is visibly tagged** ("Preview data" on the `StatCard`) rather than presented as live.
- **Theme is opt-in** (`data-theme="light"` via a click, persisted to `localStorage`) — deliberately not `prefers-color-scheme`, so an existing user's OS setting can't silently change their view of an app that has only ever shipped dark.

### Verification

- `npx tsc --noEmit -p tsconfig.app.json` — clean.
- `npx vitest run` — 106/106 tests passing across 12 files, including 15 `AdminApp.test.tsx` cases covering auth gating, sidebar-driven navigation, deep-linking, permission-based nav visibility, Coming Soon rendering, and sign-out.
- No backend files changed (`git diff --stat` against every non-frontend path is empty) — this phase is frontend-only, as scoped.
- Manually rendered: Overview dashboard (dark + light), a Coming Soon destination (Billing), and mobile viewport (closed + open nav) — see PR description for screenshots.

### Reusable components delivered

| Component | Purpose |
|---|---|
| `AppShell` | Persistent shell every future module's pages mount into |
| `SidebarNav` | Sectioned, permission-aware left nav driven by `navigation.ts` |
| `TopAppBar` | Breadcrumb, search, org context, theme, notifications, profile |
| `PageContainer` / `SectionHeader` | Standard page wrapper + heading pattern |
| `StatCard` | Dashboard/summary tiles, with a `placeholder` flag for non-live data |
| `DataTable` | Typed wrapper around the existing `.data-table` CSS |
| `EmptyState` / `LoadingState` / `ErrorState` / `ComingSoon` | The four states every data-bearing page needs |
| `ActionToolbar` / `Button` / `Card` | Layout/action primitives |

### Explicitly not done (out of scope, per the brief)

No Billing, Audit, Workflows, AI Models, or Infrastructure module logic; no backend, IAM, or database changes; no new permissions. Every such nav destination is a `<ComingSoon>` placeholder.
