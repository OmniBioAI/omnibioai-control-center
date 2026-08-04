# PR11.2 — Enterprise Organization Management (Teams + Roles & Permissions)

Status: **Implemented.** Branch `feature/pr11-organization-management`, not yet merged.

Builds on PR8 (dual-build architecture), PR9 (enterprise shell + design
system), PR10 (platform dashboard), and PR11.1 (user management). Promotes
Teams and Roles & Permissions from "embedded inside Organization Details,
Coming Soon as their own nav destination" to standalone enterprise admin
pages, per the navigation shape:

```
Administration
├── Organizations
├── Users
├── Teams                 ← new standalone page (was Coming Soon)
├── Roles & Permissions    ← new standalone page (was Coming Soon)
├── IAM                   (unchanged, still Coming Soon)
└── Security               (unchanged, still Coming Soon)
```

---

## Phase 0 discovery findings

Before writing any code, the existing architecture was inspected directly
(not assumed from the task description):

- **Frontend data layer already existed in full**: `src/teams.ts` and
  `src/roles.ts` (Phase 3 PR3B/PR3C) already implement every function this
  PR needed (`listTeams`, `createTeam`, `updateTeamMembers`, `deleteTeam`,
  `fetchOrgRoles`, `fetchOrgMemberRoles`, ...). Nothing new was added here.
- **Components already existed in full**: `components/teams/{TeamsCard,
  TeamRow, TeamMemberSelector}` and `components/roles/{RoleBadge,
  RoleSelector, RoleAssignmentList}` were already built, already tested
  (via `OrganizationDetailPage.test.tsx` and their own `.test.tsx` files),
  and already wired into `OrganizationDetailPage.tsx`.
- **Design system already existed**: `components/ui/{PageContainer,
  SectionHeader, ActionToolbar, Card, DataTable, EmptyState, LoadingState,
  ErrorState}` (Phase 2/PR10) were ready to use as-is.
- **`navigation.ts`** already reserved `'teams'` and `'roles'` `PageKey`s
  with `functional: false` (Coming Soon) — flipping a flag, not adding new
  entries.
- **Backend proxy layer already existed in full**: `routes_team_proxy.py`
  and `routes_role_proxy.py` (Phase 3 PR3B/PR3C) already forward every
  endpoint this PR needed to omnibioai-auth, already registered in
  `main.py`. **Phase 5 required zero backend changes** — both proxy files
  were read and confirmed to already cover `GET/POST /orgs/{id}/teams`,
  `PUT/DELETE .../teams/{id}[/members]`, `GET /orgs/{id}/roles`, and
  `GET/POST/DELETE /orgs/{id}/members/{user_id}/roles[/{role_id}]`.

Given all of that, this PR's actual surface area was small and precise:
**two new page-level components that add an organization picker in front
of already-existing, already-tested pieces**, plus navigation activation
and Organization Detail UX links. No new API client code, no new backend
route, no new authorization logic.

---

## Architecture decisions

1. **TeamsPage/RolesPage are thin wrappers, not reimplementations.**
   `TeamsPage` renders an organization selector plus the existing
   `TeamsCard` component unmodified — the exact same component
   `OrganizationDetailPage` already uses, with the exact same
   create/view/edit-members/delete behavior and the exact same graceful
   degradation (hides silently on a 403, falls back to raw user ids when
   the member roster is unavailable). `RolesPage` reads the same
   `RoleSummary[]` catalog `OrganizationDetailPage`'s `RoleSelector`
   already consumes, via `RoleBadge` for rendering — but does **not**
   reuse `RoleSelector` itself, since `RoleSelector` is the mutation UI
   (checkboxes that call `assignOrgMemberRole`/`removeOrgMemberRole`) and
   this page is explicitly read-only (see Non-goals below).

2. **Member counts on the Roles page are computed client-side**, from
   `GET /orgs/{org_id}/members` (`OrgMember.roles`), not a new backend
   aggregation endpoint. This is the same data `MembersRolesCard` already
   fetches and reads elsewhere on this page — no new authorization
   surface. A viewer with role-catalog access but not `manage_org` (bare
   org membership is enough for `GET .../roles`, per
   `get_org_membership_or_platform_admin`) sees "—" instead of a count
   rather than an error, mirroring `TeamsCard`'s own "hide, don't error"
   posture for exactly this asymmetry.

3. **Organization Detail links out instead of duplicating.** Phase 4 asked
   for "shared components over copied markup" — rather than re-rendering
   a `TeamsPage`/`RolesPage`-shaped view inside `OrganizationDetailPage`,
   two small `<button>` links ("View all teams →" / "View roles &
   permissions →") were added that navigate to the standalone pages,
   pre-scoped to the org the admin was already looking at via an
   `initialOrgId` prop (a `teamsOrgHint`/`rolesOrgHint` piece of state in
   `AdminApp.tsx`, not a URL route of its own — there is no
   `/teams/{org_id}` deep link, unlike `/organizations/{id}`). The
   embedded `TeamsCard`/`MembersRolesCard` sections stay exactly where
   they are, unmodified — this is an additive link, not a replacement.

4. **`SecuritySummaryCard` is a new, explicitly-honest placeholder.** Per
   the task's own instruction not to imply functionality that doesn't
   exist: SSO reflects real `org.sso.configured` state where available
   (platform-admin view) and says "Not available in this view" where it
   isn't (`OrganizationOut`/`MyOrg` carries no SSO field at all — nothing
   was invented to fill that gap). MFA and domain verification are
   rendered as fixed placeholder text ("Not configured" / "Pending
   verification") with an explicit disclaimer line, because neither is
   implemented anywhere in the platform (confirmed directly against
   omnibioai-auth during the PR11 discovery pass, not assumed).

---

## APIs consumed

All pre-existing, all unmodified by this PR:

| Method | Path | Proxy file | Backend authorization (omnibioai-auth, unchanged) |
|---|---|---|---|
| GET | `/platform/orgs` | `routes_org_proxy.py` | `require_permission(manage_all_orgs)` |
| GET | `/orgs` | `routes_org_proxy.py` | authenticated caller, own memberships only |
| GET | `/orgs/{org_id}/teams` | `routes_team_proxy.py` | `get_org_membership_or_platform_admin` |
| POST/PUT/DELETE | `/orgs/{org_id}/teams...` | `routes_team_proxy.py` | `require_org_permission_or_platform_admin(MANAGE_TEAMS)` |
| GET | `/orgs/{org_id}/roles` | `routes_role_proxy.py` | `get_org_membership_or_platform_admin` |
| GET | `/orgs/{org_id}/members` | `routes_org_proxy.py` | `require_org_permission_or_platform_admin(MANAGE_ORG)` |

## Permissions reused

No new permission was introduced. Both new nav items gate on
`hasOrganizationsAccess()` — the exact same client-side visibility check
`'organizations'` already uses in `navigation.ts` — because every
capability these pages expose (view teams, view roles) is already
reachable by that same audience today via `OrganizationDetailPage`; this
PR changes *where* it's reachable, not *who* can reach it. Every
individual data fetch is independently re-authorized server-side by
omnibioai-auth exactly as before ("frontend hiding is not authorization,"
the same posture every prior identity-management PR in this repo has
documented).

---

## Non-goals (explicit)

Per the task's own scope:

- **No role creation, permission editing, or permission-assignment
  changes.** `RolesPage` is read-only; it does not render `RoleSelector`
  or call `assignOrgMemberRole`/`removeOrgMemberRole`. Those stay exactly
  where they already were (`OrganizationDetailPage`'s Members & Roles
  card) — permission mutation requires a separate security review this PR
  is not that review.
- **No MFA, domain verification, SAML, or SCIM.** `SecuritySummaryCard`
  shows explicit placeholders for MFA/domain, never live status.
- **No billing, usage metering, or Audit Center.**
- **No new permissions model** — `hasOrganizationsAccess()` reused as-is.
- **No backend changes** — Phase 5's proxy layer already existed in full.

---

## Testing

```
npm test          # 156/156 passed (17 new: TeamsPage.test.tsx, RolesPage.test.tsx)
npx tsc --noEmit   # clean, no errors
```

New coverage:

- **`TeamsPage.test.tsx`** (8 tests): platform-admin vs. org-scoped
  endpoint selection ("permission visibility"), loading/empty/error
  states, organization switching re-scopes `TeamsCard`, `initialOrgId`
  pre-selection (including falling back when the hinted org isn't in the
  loaded list).
- **`RolesPage.test.tsx`** (9 tests): role/permission rendering, member
  count computed from the roster (and degrading to "—" on a 403),
  read-only assertion (no checkboxes/mutation controls ever render),
  organization switching reloads the catalog, loading/empty/error states,
  platform-admin vs. org-scoped endpoint selection.
- **`OrganizationDetailPage.test.tsx`** (+4 tests): `SecuritySummaryCard`
  renders real SSO status where available and "Not available in this
  view" where it isn't, quick links call back with the current org id,
  and render nothing when the callbacks are omitted (backward compatible
  with any caller that doesn't pass them).
- **`AdminApp.test.tsx`** (+3 tests): Teams/Roles are reachable via the
  sidebar and no longer show "Coming soon"; both are hidden for a user
  without organizational access; a "View all teams" click from an
  organization's detail page lands on `TeamsPage` pre-scoped to that org.

All pre-existing tests continue passing unmodified.

---

## Screenshots

Captured against the real built app (Vite dev server, `VITE_APP_MODE=admin`,
headless Chromium) with the session and API responses mocked at the network
boundary only — no application code touched to fake any of this, same
approach the Phase 2 findings doc used.

- `docs/images/admin-console-pr11/teams-page.png` — standalone Teams page,
  organization selector, three teams with resolved member emails.
- `docs/images/admin-console-pr11/roles-page.png` — standalone Roles &
  Permissions page, three roles with their permission lists and computed
  member counts, read-only.
- `docs/images/admin-console-pr11/organization-detail-security-links.png`
  — Organization Detail page showing the new Security summary card (real
  SSO status, explicit MFA/domain placeholders) and the "View roles &
  permissions →" / "View all teams →" quick links, above the still-intact
  embedded Members & Roles / Teams cards.
