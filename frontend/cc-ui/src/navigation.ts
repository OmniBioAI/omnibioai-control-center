import { hasAdminAccess, hasOrganizationsAccess, hasPlatformAdminAccess } from './auth'

/**
 * Admin Console Phase 2: the single source of truth for the sectioned
 * navigation tree -- SidebarNav, the dashboard's stat cards, and
 * AdminApp's page-key union all derive from this file rather than each
 * keeping their own copy of "what pages exist."
 *
 * `functional: true` means a real, working page exists and is reused
 * as-is (its own permission gate, if any, is `visible` below, copied
 * verbatim from auth.ts -- never a new permission). `functional: false`
 * means Phase 2 explicitly does not implement that module: the item
 * still appears in the nav (per the task's own instruction that future
 * pages "should appear as disabled or Coming Soon", not be hidden) and
 * navigating to it renders the shared <ComingSoon /> primitive.
 *
 * Coming-soon items have no `visible` gate -- they show no data, so
 * there's nothing to protect; every item that says PLATFORM_ADMIN or
 * requires an existing permission is exactly the same real gate this
 * app already enforced before Phase 2, none of them are new.
 */

export type PageKey =
  | 'overview'
  | 'health' | 'docker' | 'ecosystem' | 'config' | 'llms' | 'cloud'
  | 'organizations' | 'users' | 'teams' | 'roles'
  | 'infrastructure' | 'workflows' | 'tool-execution' | 'ai-models'
  | 'security-overview' | 'mfa-policy' | 'iam' | 'audit-logs' | 'sessions' | 'api-keys'
  | 'billing' | 'licenses' | 'usage'
  | 'rag' | 'pubmed' | 'plugins'
  | 'integrations' | 'settings'

export interface NavItem {
  key: PageKey
  label: string
  functional: boolean
  /** Reused verbatim from auth.ts -- never a new permission check. */
  visible?: () => boolean
  children?: NavItem[]
}

export interface NavSection {
  key: string
  /** Empty for the un-headed top section (Overview alone). */
  label: string
  items: NavItem[]
}

export const NAVIGATION: NavSection[] = [
  {
    key: 'top',
    label: '',
    items: [
      { key: 'overview', label: 'Overview', functional: true },
    ],
  },
  {
    key: 'administration',
    label: 'Administration',
    items: [
      { key: 'organizations', label: 'Organizations', functional: true, visible: hasOrganizationsAccess },
      { key: 'users', label: 'Users', functional: true, visible: hasPlatformAdminAccess },
      // PR11.2: promoted from Coming Soon to standalone pages
      // (src/pages/identity/TeamsPage.tsx, RolesPage.tsx). Both reuse the
      // exact same components and endpoints OrganizationDetailPage's
      // embedded Teams/Members & Roles sections already used -- this PR
      // adds an organization picker in front of them, nothing else -- so
      // the visibility gate is unchanged from 'organizations' above:
      // anyone who can see an org's detail page can see its teams/roles.
      { key: 'teams', label: 'Teams', functional: true, visible: hasOrganizationsAccess },
      { key: 'roles', label: 'Roles & Permissions', functional: true, visible: hasOrganizationsAccess },
    ],
  },
  {
    key: 'operations',
    label: 'Operations',
    items: [
      // Infrastructure isn't in the task's example leaf list verbatim,
      // but is where the 6 pre-existing ops pages (all real, all
      // required to keep working) map onto this taxonomy -- grouped
      // under one expandable parent rather than 6 new top-level items,
      // to keep the requested section shape intact. Same single
      // hasAdminAccess() gate every one of these pages already used
      // before Phase 2, applied once to the group.
      {
        key: 'infrastructure', label: 'Infrastructure', functional: true, visible: hasAdminAccess,
        children: [
          { key: 'health', label: 'Health', functional: true, visible: hasAdminAccess },
          { key: 'docker', label: 'Docker', functional: true, visible: hasAdminAccess },
          { key: 'ecosystem', label: 'Ecosystem Report', functional: true, visible: hasAdminAccess },
          { key: 'config', label: 'Config', functional: true, visible: hasAdminAccess },
          { key: 'llms', label: 'LLMs', functional: true, visible: hasAdminAccess },
          { key: 'cloud', label: 'Cloud', functional: true, visible: hasAdminAccess },
        ],
      },
      { key: 'workflows', label: 'Workflows', functional: false },
      { key: 'tool-execution', label: 'Tool Execution', functional: false },
      { key: 'ai-models', label: 'AI Models', functional: false },
    ],
  },
  {
    key: 'security',
    label: 'Security',
    items: [
      // PR11.5.6: Enterprise Admin Console Security UI. Neither of these
      // two claims the pre-existing 'sessions' reservation below --
      // that slot is for a future session-list/revoke feature (see
      // docs/pr11-security-foundation-discovery.md §1.8), unrelated to
      // MFA. Placed first: a dashboard overview is the natural entry
      // point into this section, same reasoning 'overview' is first in
      // the top-level nav. See
      // docs/pr11-5-6-security-ui-discovery.md §1 for the full decision
      // (the task's own "enable the reserved Security item" framing
      // didn't match this file's actual current shape -- 'security' was
      // already a section, not a leaf item).
      //
      // security-overview: cross-organization aggregate (MFA adoption,
      // org policy counts, recent MFA/audit events) -- same
      // hasPlatformAdminAccess gate 'audit-logs' below already uses,
      // for the identical reason (GET /platform/users, GET /platform/
      // orgs, GET /platform/audit-events are all manage_all_orgs-gated,
      // not org-scoped).
      { key: 'security-overview', label: 'Security Overview', functional: true, visible: hasPlatformAdminAccess },
      // mfa-policy: per-organization MFA requirement management -- same
      // hasOrganizationsAccess gate 'iam'/'api-keys' below already use,
      // for the identical reason (GET/POST/PATCH /orgs/{org_id}/
      // mfa-policy is manage_sso-gated, org-scoped, same permission
      // 'iam' already reuses for SSO config).
      { key: 'mfa-policy', label: 'MFA Policy', functional: true, visible: hasOrganizationsAccess },
      // PR11.3: Enterprise SSO Management UI. functional: true because a
      // real page now exists (SSOSettingsPage, reached via an
      // organization picker -- SSO config is per-org, so this
      // destination lands on an org-selection step before the settings
      // page itself, the same "list -> detail" shape 'organizations'
      // already uses). No new permission: `visible` reuses
      // hasOrganizationsAccess, the same gate 'organizations' already
      // has -- this only decides whether the nav entry (and the org
      // picker) renders at all; the actual manage_sso /
      // override_sso_enforcement checks happen entirely backend-side,
      // per-org, once a specific org's SSO settings are opened (see
      // docs/admin-console-pr11-sso-discovery.md).
      { key: 'iam', label: 'IAM / SSO Management', functional: true, visible: hasOrganizationsAccess },
      // PR11.4b: Enterprise Identity Audit Trail Foundation.
      // functional: true because a real page now exists
      // (AuditLogsPage). Gated by hasPlatformAdminAccess, not
      // hasOrganizationsAccess like 'iam'/'api-keys' -- the backend
      // route this page reads (GET /platform/audit-events) is gated by
      // manage_all_orgs specifically (no dedicated audit permission
      // exists, and this PR doesn't add one -- see
      // docs/pr11-identity-audit-discovery.md §5), so
      // hasPlatformAdminAccess is the one gate that actually matches
      // who can reach real data here. The backend check is still the
      // only thing that matters for security; this only decides
      // whether the nav entry renders.
      { key: 'audit-logs', label: 'Audit Logs', functional: true, visible: hasPlatformAdminAccess },
      { key: 'sessions', label: 'Sessions', functional: false },
      // PR11.4: Service Accounts & API Keys Management UI. functional:
      // true because a real page now exists (ServiceAccountsPage,
      // reached via an organization picker -- API keys/OAuth clients
      // are per-org, so this destination lands on an org-selection step
      // first, same "list -> detail" shape 'organizations' and PR11.3's
      // 'iam' (SSO) destination already use). No new permission:
      // `visible` reuses hasOrganizationsAccess, the same gate
      // 'organizations' already has -- this only decides whether the
      // nav entry (and the org picker) renders at all; the actual
      // manage_api_keys / manage_oauth_clients checks happen entirely
      // backend-side, per-org, once a specific org's service accounts
      // are opened (see docs/admin-console-pr11-service-accounts-
      // discovery.md).
      { key: 'api-keys', label: 'API Keys / Service Accounts', functional: true, visible: hasOrganizationsAccess },
    ],
  },
  {
    key: 'business',
    label: 'Business',
    items: [
      // PR14.5C: billing visibility and invoice management are per-org,
      // so this destination lands on an org-selection step first, same
      // "list -> detail" shape 'iam'/'api-keys' already use. No new
      // permission: `visible` reuses hasOrganizationsAccess, the same
      // gate every other org-scoped nav entry has -- this only decides
      // whether the nav entry (and the org picker) renders at all; the
      // actual authorization (an org member or a platform admin) happens
      // entirely backend-side, per-org, via omnibioai-billing's own
      // app.core.iam.get_authorized_organization_id/get_authorized_invoice.
      { key: 'billing', label: 'Billing', functional: true, visible: hasOrganizationsAccess },
      { key: 'licenses', label: 'Licenses', functional: false },
      { key: 'usage', label: 'Usage', functional: false },
    ],
  },
  {
    key: 'knowledge',
    label: 'Knowledge',
    items: [
      { key: 'rag', label: 'RAG', functional: false },
      { key: 'pubmed', label: 'PubMed', functional: false },
      { key: 'plugins', label: 'Plugins', functional: false },
    ],
  },
  {
    key: 'platform',
    label: 'Platform',
    items: [
      { key: 'integrations', label: 'Integrations', functional: false },
      { key: 'settings', label: 'Settings', functional: false },
    ],
  },
]

/** True if `item` (or, for a group, any of its children) should render
 * at all for the current session. Coming-soon items with no `visible`
 * are always shown -- see module docstring for why. */
export function isNavItemVisible(item: NavItem): boolean {
  if (item.visible && !item.visible()) return false
  return true
}

/** Flat lookup of every leaf item (children included, group parents
 * excluded) -- used to resolve breadcrumbs and page titles from a
 * PageKey without a second copy of the label list. */
export function findNavItem(key: PageKey): NavItem | undefined {
  for (const section of NAVIGATION) {
    for (const item of section.items) {
      if (item.key === key) return item
      const child = item.children?.find(c => c.key === key)
      if (child) return child
    }
  }
  return undefined
}
