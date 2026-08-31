import { canSeeAnalytics, hasAdminAccess, hasOrganizationsAccess, hasPermission, hasPlatformAdminAccess } from './auth'

// DH-3: shared reference (not a fresh arrow function per item) so
// Regression Health and Deployment Health -- both gated by the exact
// same platform.manage_infra permission DH-2's own backend route
// requires -- can be asserted as literally the same gate in
// navigation.test.ts, the same "shared function reference" convention
// 'saml'/'iam' below already establish for their own shared gate.
const hasManageInfraAccess = () => hasPermission('platform.manage_infra')

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
  | 'health' | 'regression-health' | 'deployment-health' | 'integration-health' | 'docker' | 'ecosystem' | 'config' | 'llms' | 'cloud'
  | 'actions' | 'scheduled-jobs' | 'known-issues'
  | 'organizations' | 'users' | 'teams' | 'roles'
  | 'infrastructure' | 'workflows' | 'tool-execution' | 'ai-models' | 'agentic-ai'
  | 'security-overview' | 'security-posture' | 'mfa-policy' | 'iam' | 'saml' | 'audit-logs' | 'audit-explorer' | 'sessions' | 'interactions' | 'api-keys' | 'compliance-report'
  | 'hipaa-compliance'
  | 'analytics'
  | 'billing'
  | 'rag' | 'pubmed'
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
          { key: 'regression-health', label: 'Regression Health', functional: true, visible: hasManageInfraAccess },
          // DH-3: Deployment Health -- placed immediately after
          // Regression Health and before Docker, per the DH-3 task
          // brief's explicit ordering. Same platform.manage_infra gate
          // 'regression-health' immediately above uses (and DH-2's own
          // backend route requires) -- not a new permission, the
          // frontend visibility signal and the real backend
          // authorization are the same check.
          { key: 'deployment-health', label: 'Deployment Health', functional: true, visible: hasManageInfraAccess },
          { key: 'integration-health', label: 'Integration Health', functional: true, visible: hasManageInfraAccess },
          { key: 'docker', label: 'Docker', functional: true, visible: hasAdminAccess },
          { key: 'ecosystem', label: 'Ecosystem Report', functional: true, visible: hasAdminAccess },
          { key: 'config', label: 'Config', functional: true, visible: hasAdminAccess },
          { key: 'llms', label: 'LLMs', functional: true, visible: hasAdminAccess },
          { key: 'cloud', label: 'Cloud', functional: true, visible: hasAdminAccess },
          // Moved from the public Control Center's legacy static-HTML
          // ecosystem-report page (scripts/sections/misc/admin.py) --
          // that page's own "Admin" tab is gone (see
          // docs/admin-console-navigation-move.md); these three items
          // are its replacement, admin-console-only from here on. Same
          // hasAdminAccess() gate every other Infrastructure child
          // already uses -- real authorization is still each backend
          // route's own require_permission (platform.manage_content for
          // Actions/Known Issues writes, platform.manage_cron for
          // Scheduled Jobs writes; every GET in all three is open to any
          // authenticated admin-console user, same as before the move).
          { key: 'actions', label: 'Actions', functional: true, visible: hasAdminAccess },
          { key: 'scheduled-jobs', label: 'Scheduled Jobs', functional: true, visible: hasAdminAccess },
          { key: 'known-issues', label: 'Known Issues', functional: true, visible: hasAdminAccess },
        ],
      },
      // PR A3: Admin Console Capability Parity. functional: true because
      // a real page now exists (WorkflowsPage), reusing
      // omnibioai-workflow-bundles' own GET /v1/workflows,
      // GET /v1/categories (both workflow.read-gated) and GET /v1/runs
      // (workflow.execute-gated). Same hasAdminAccess() gate
      // 'tool-execution'/'ai-models'/'infrastructure' above already
      // use -- this only decides whether the nav entry renders; real
      // authorization is entirely workflow-bundles' own, per-request.
      // Note: GET /v1/runs has no organization-level filtering upstream
      // today (tracked as an upstream follow-up, not something this nav
      // gate can or should paper over) -- WorkflowsPage's Runs tab
      // surfaces that explicitly rather than hiding it.
      { key: 'workflows', label: 'Workflows', functional: true, visible: hasAdminAccess },
      // PR A1: Admin Console Capability Parity. functional: true because
      // a real page now exists (ToolExecutionPage), reusing
      // omnibioai-tes's own GET /api/runs (self-scoped to the caller's
      // organization, require_permission(WORKFLOW_EXECUTE)) and
      // unauthenticated GET /api/tools[/capabilities]. Same
      // hasAdminAccess() gate 'infrastructure' above already uses -- this
      // only decides whether the nav entry renders; the real
      // authorization is entirely omnibioai-tes's own, per-request, same
      // "backend is the real gate" convention this file already documents
      // for 'iam'/'billing'/'audit-logs'.
      { key: 'tool-execution', label: 'Tool Execution', functional: true, visible: hasAdminAccess },
      // PR A2: Admin Console Capability Parity. functional: true because
      // a real page now exists (AIModelsPage), reusing
      // omnibioai-model-registry's own GET /v1/models (grouped
      // client-side into Registered Models vs. Model Versions -- no
      // separate upstream endpoint for each) plus GET /health and
      // GET /v1/auth/status for the Runtime Status tab. Same
      // hasAdminAccess() gate 'tool-execution'/'infrastructure' above
      // already use -- this only decides whether the nav entry renders;
      // none of these three routes are gated at all on the
      // model-registry side today (confirmed by reading its source),
      // so there is no separate real authorization boundary this gate
      // could be papering over.
      { key: 'ai-models', label: 'AI Models', functional: true, visible: hasAdminAccess },
      // feature/agentic-ai-navbar. functional: true because a real page
      // now exists (AgenticAIPage), reusing omnibioai-workbench's own
      // GET /api/agent/graphs/ (agent_orchestrator service) via
      // routes_agent_orchestrator_proxy.py. Same hasAdminAccess() gate
      // 'ai-models'/'tool-execution'/'workflows'/'rag' above already
      // use -- this only decides whether the nav entry renders. Unlike
      // 'rag'/'ai-models' below, that endpoint does require a real
      // Authorization header in practice (a cross-cutting Django
      // middleware in a different, unrelated plugin gates every /api/*
      // route project-wide -- confirmed live, see
      // routes_agent_orchestrator_proxy.py's own comment), so this gate
      // and the real upstream check now line up rather than this being
      // the only real control.
      // No org picker: agent_orchestrator's graph catalog has no
      // organization concept, same reasoning 'tool-execution'/'ai-models'
      // above use.
      { key: 'agentic-ai', label: 'Agentic AI', functional: true, visible: hasAdminAccess },
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
      { key: 'security-posture', label: 'Security Posture', functional: true, visible: hasPlatformAdminAccess },
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
      // PR9: SAML Admin UI. Same "pick an org, then manage its
      // configuration" shape as 'iam'/'mfa-policy' immediately above,
      // and the identical hasOrganizationsAccess gate -- GET/POST/PATCH/
      // DELETE /orgs/{org_id}/saml is manage_sso-gated, org-scoped, same
      // permission 'iam' already reuses (PR8/auth#49 deliberately
      // reused manage_sso rather than a new manage_saml). Placed as its
      // own destination, not folded into 'iam', since SAML and OIDC are
      // two independent, separately-configured identity providers on
      // the backend (OrganizationSAMLConfig vs OrganizationSSOConfig,
      // no shared row) -- SSOSettingsPage.tsx never reads or writes
      // this data either.
      { key: 'saml', label: 'SAML Settings', functional: true, visible: hasOrganizationsAccess },
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
      { key: 'audit-explorer', label: 'Audit Explorer', functional: true, visible: hasOrganizationsAccess },
      // HIPAA Basic Compliance Report v0.8.0. Same hasPlatformAdminAccess
      // gate 'audit-logs' immediately above uses, for the identical
      // reason -- GET /compliance/hipaa-report is manage_all_orgs-gated
      // (compliance/router.py), not org-scoped; org_admin access is
      // deferred to v0.9.0 (see compliance/service.py's own module
      // docstring for why no org-scoped read path exists yet for two of
      // the report's four sections). Placed next to Audit Logs/
      // Interactions -- its closest technical precedent (platform-admin-
      // only, date-ranged, reads the same underlying audit ledger).
      { key: 'compliance-report', label: 'Compliance Report', functional: true, visible: hasPlatformAdminAccess },
      // PR-C (Control Center Sessions Integration): promoted from Coming
      // Soon to a real page (SessionsPage). Unlike 'audit-logs' above
      // (platform-admin-only backend data), this is self-service --
      // omnibioai-auth's GET /sessions (Phase 4 PR-A) scopes every
      // response to the caller's own `sub` claim server-side, there is
      // no separate permission to gate here. No `visible` at all,
      // same as 'overview' -- anyone who reached this console
      // (hasConsoleAccess in AdminApp.tsx) already has an account whose
      // own sessions are meaningfully theirs to see.
      { key: 'sessions', label: 'Sessions', functional: true },
      // PR-B5-B (Control Center Interaction Admin View). functional: true
      // because a real page now exists (InteractionsPage), reusing
      // omnibioai-auth's GET /platform/interactions (PR-B5-A) via
      // routes_platform_interactions_proxy.py. Gated by
      // hasPlatformAdminAccess, the same gate 'audit-logs' above uses and
      // for the identical reason -- the backend route this page reads is
      // gated by manage_all_orgs specifically (no dedicated interactions
      // permission exists, and this PR doesn't add one), so
      // hasPlatformAdminAccess is the one gate that actually matches who
      // can reach real data here. Placed in Security next to Audit Logs
      // (its closest technical precedent: paginated, filtered, platform-
      // admin-only, free-form JSON metadata) rather than a new section --
      // see this PR's own report for the open question of whether a
      // dedicated "Activity" section would fit better long-term.
      { key: 'interactions', label: 'Interactions', functional: true, visible: hasPlatformAdminAccess },
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
    // Admin Console HIPAA Compliance Report (V1): a new top-level
    // section, deliberately distinct from Security > "Compliance
    // Report" above (the pre-existing HIPAA Basic Compliance Report
    // v0.8.0 -- an org-scoped usage/access-log export). This section
    // tracks a completely different thing: the platform's own HIPAA
    // *engineering* remediation history (which PRs closed which control
    // gaps, with what verification evidence) -- not org data at all.
    // Placed as its own section (task brief: "Admin Console > Compliance
    // > HIPAA Compliance"), not nested under Security, so the two
    // "compliance" concepts don't visually collide as if one were a
    // subset of the other.
    key: 'compliance',
    label: 'Compliance',
    items: [
      // Same hasPlatformAdminAccess gate 'audit-logs'/'compliance-report'
      // above use, for the identical reason -- every route under
      // GET /hipaa-compliance/changes is manage_all_orgs-gated
      // (routes_hipaa_compliance.py's own _require_platform_admin),
      // reads included, not just writes.
      { key: 'hipaa-compliance', label: 'HIPAA Compliance', functional: true, visible: hasPlatformAdminAccess },
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
      // Usage Analytics v1 (PR-D). A real page (AnalyticsDashboard.tsx),
      // no org picker in front of it (unlike 'billing'/'iam'/'api-keys'
      // above) -- the backend's own require_analytics_scope resolves
      // org_id/team_id from the caller's token, and the page itself
      // offers an in-page organization filter only for a platform_admin
      // (the only role with more than one org to choose from). `visible`
      // is canSeeAnalytics -- narrower than hasOrganizationsAccess:
      // platform_admin, an org's own org_admin, or a team's own
      // team_admin only, mirroring require_analytics_scope's own
      // platform_admin/org_admin/team_admin/deny matrix exactly (a
      // regular org member is denied both here and, independently and
      // authoritatively, by the backend).
      { key: 'analytics', label: 'Usage Analytics', functional: true, visible: canSeeAnalytics },
      // PR B (Admin Console Billing/Usage consolidation): 'licenses' and
      // 'usage' removed from this section, not flipped to functional.
      // Both were Coming Soon placeholders that, on audit, turned out to
      // already be covered:
      //   - 'usage': BillingPage.tsx already had a Usage Limits tab
      //     (PR14.6D); this PR adds a plain Usage tab alongside it (raw
      //     consumption, GET /organizations/{id}/usage, previously
      //     unproxied). A standalone nav destination for this would have
      //     duplicated a page that already exists one click away.
      //   - 'licenses': the only "licenses" concept anywhere in this
      //     ecosystem is omnibioai-auth's legacy per-key desktop/
      //     Electron activation system (app/api/routes_license.py,
      //     LicenseValidateRequest.platform: web|desktop|both) --
      //     Phase 1's own license-decommission work already targeted
      //     that flow for retirement. It is not an org-seat/subscription
      //     concept and building an Admin Console UI for it would be
      //     resurrecting a superseded model, not consolidating one.
      //     Organization-level plan/subscription management is exactly
      //     what the 'billing' entry above (Subscription tab) already
      //     is. See docs/pr-b-billing-usage-consolidation.md for the
      //     full audit both of these decisions are based on.
    ],
  },
  {
    key: 'knowledge',
    label: 'Knowledge',
    items: [
      // PR A4: Admin Console Capability Parity. functional: true because
      // a real page now exists (RAGPage), reusing omnibioai-rag's own
      // GET /v1/studies and GET /v1/cache/stats (both answered via a
      // control-center-held RAGBIO_API_KEY service credential, not the
      // viewing admin's own token -- see rag.ts's module comment) plus
      // GET /health. Both 'rag' and 'pubmed' point at the same page:
      // RAG's only indexed corpus today is PubMed abstracts (confirmed
      // by reading ragbio/api/server.py directly), there is no separate
      // PubMed concept server-side to build a second page against.
      // Same hasAdminAccess() gate 'tool-execution'/'ai-models'/
      // 'workflows'/'infrastructure' above already use -- this only
      // decides whether the nav entry renders; unlike those three,
      // this page's underlying data isn't per-admin-authorized at all
      // (see rag.ts), so this gate is the only real access control this
      // page has, not a visibility layer in front of a separate backend
      // check.
      { key: 'rag', label: 'RAG', functional: true, visible: hasAdminAccess },
      { key: 'pubmed', label: 'PubMed', functional: true, visible: hasAdminAccess },
      // PR E2 (re-verified PR D §3.2's finding, unchanged): removed, not
      // flipped to functional. The only "plugin" concept anywhere in
      // this ecosystem is the GHCR omnibioai-plugin-* container-image
      // family -- confirmed again by re-reading routes_docker.py's
      // GET /docker/plugin-images directly (auto-discovers every
      // plugins/*/plugin.json manifest, resolves each to its GHCR
      // image, reports local presence) -- already fully live under
      // Operations > Infrastructure > Docker > "Plugin Docker Images".
      // A second nav entry here would duplicate that tab exactly, same
      // failure mode PR B avoided for Licenses/Usage. See
      // docs/pr-d-admin-placeholder-audit.md §3.2 for the original
      // discovery.
    ],
  },
  {
    key: 'platform',
    label: 'Platform',
    items: [
      // PR-B6: functional: true because a real page now exists
      // (IntegrationsPage, reusing control-center's own new GET
      // /integrations -- routes_integrations.py, env-var-derived
      // status for the three third-party integrations discovery found
      // actual evidence for: Sentry and the two Discord webhook
      // targets. Same hasAdminAccess() gate 'cloud'/'rag'/'settings'
      // above already use -- this only decides whether the nav entry
      // renders; GET /integrations requires no permission at all
      // upstream (same posture as GET /cloud), so this gate is the
      // only real access control this page has, not a visibility layer
      // in front of a separate backend check. Deliberately does not
      // cover GlobalConfig's LLM/cloud provider (already the Settings
      // page below) or compute backends (already the Cloud page) --
      // building either here would duplicate an existing page, the
      // same failure mode PR B avoided for Licenses/Usage.
      { key: 'integrations', label: 'Integrations', functional: true, visible: hasAdminAccess },
      // PR E1: Admin Settings integration. functional: true because a
      // real page now exists (PlatformSettingsPage), reusing
      // omnibioai-auth's own GET /auth/config (GlobalConfig -- no
      // permission required upstream, just a valid token, confirmed by
      // reading app/api/routes_config.py directly; see
      // docs/pr-d-admin-placeholder-audit.md §3.4 for the discovery
      // that found this backend). Same hasAdminAccess() gate
      // 'tool-execution'/'ai-models'/'workflows'/'rag' above already
      // use -- this only decides whether the nav entry renders, not a
      // visibility layer in front of a separate real permission (there
      // isn't one for reads). Read-only in this PR: omnibioai-auth's own
      // PUT /auth/config (manage_config-gated, can set a platform-wide
      // LLM API key / cloud credentials) is deliberately not proxied or
      // exposed yet -- see routes_platform_config_proxy.py's own module
      // comment for that scope decision.
      { key: 'settings', label: 'Settings', functional: true, visible: hasAdminAccess },
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
