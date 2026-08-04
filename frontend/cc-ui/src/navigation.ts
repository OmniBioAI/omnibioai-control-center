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
  | 'iam' | 'audit-logs' | 'sessions' | 'api-keys'
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
      // Team and role/permission management both already work today,
      // but only reached via Organization Details -- there's no
      // standalone page for either yet, so per "only existing PAGES are
      // functional" these are Coming Soon as their own nav destination.
      { key: 'teams', label: 'Teams', functional: false },
      { key: 'roles', label: 'Roles & Permissions', functional: false },
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
      { key: 'iam', label: 'IAM', functional: false },
      { key: 'audit-logs', label: 'Audit Logs', functional: false },
      { key: 'sessions', label: 'Sessions', functional: false },
      { key: 'api-keys', label: 'API Keys', functional: false },
    ],
  },
  {
    key: 'business',
    label: 'Business',
    items: [
      { key: 'billing', label: 'Billing', functional: false },
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
