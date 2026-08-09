import { useState, useEffect, useCallback } from 'react'
import { fetchSummary, fetchReportStatus, triggerGenerate } from '../api'
import {
  getSessionUser, hasAdminAccess, hasOrganizationsAccess, hasPlatformAdminAccess,
  UNAUTHORIZED_EVENT,
} from '../auth'
import { findNavItem } from '../navigation'
import type { PageKey } from '../navigation'
import { AppShell } from '../components/shell'
import { ComingSoon } from '../components/ui'
import DashboardPage from '../pages/DashboardPage'
import HealthPage from '../pages/HealthPage'
import DockerPage from '../pages/DockerPage'
import EcosystemPage from '../pages/EcosystemPage'
import ConfigPage from '../pages/ConfigPage'
import LlmPage from '../pages/LlmPage'
import CloudPage from '../pages/CloudPage'
import ToolExecutionPage from '../pages/operations/ToolExecutionPage'
import AIModelsPage from '../pages/operations/AIModelsPage'
import WorkflowsPage from '../pages/operations/WorkflowsPage'
import RAGPage from '../pages/operations/RAGPage'
import PlatformSettingsPage from '../pages/PlatformSettingsPage'
import OrganizationsPage from '../pages/OrganizationsPage'
import OrganizationDetailPage from '../pages/OrganizationDetailPage'
import UsersPage from '../pages/UsersPage'
import UserDetailPage from '../pages/UserDetailPage'
import TeamsPage from '../pages/identity/TeamsPage'
import RolesPage from '../pages/identity/RolesPage'
import SSOSettingsPage from '../pages/identity/SSOSettingsPage'
import ServiceAccountsPage from '../pages/identity/ServiceAccountsPage'
import BillingPage from '../pages/billing/BillingPage'
import AuditLogsPage from '../pages/audit/AuditLogsPage'
import SessionsPage from '../pages/security/SessionsPage'
import SecurityDashboardPage from '../pages/security/SecurityDashboardPage'
import OrganizationMFAPolicyPage from '../pages/security/OrganizationMFAPolicyPage'
import AuthGate from './AuthGate'

/**
 * Admin Console Phase 2 -- Enterprise Admin Console Foundation.
 *
 * AdminApp now renders inside AppShell (persistent sectioned left nav +
 * top app bar) instead of the old flat Header.tsx tab strip -- Header.tsx
 * itself is untouched and still used by ControlApp, which is out of
 * scope for this redesign.
 *
 * Every existing page (Organizations, Organization Details, Users, User
 * Details, and the 6 ops pages, now grouped under Operations >
 * Infrastructure) is reused unmodified, with the exact same permission
 * gates (hasAdminAccess/hasOrganizationsAccess/hasPlatformAdminAccess)
 * as before -- see navigation.ts, the single source of truth both
 * SidebarNav and this render switch read from. Every nav destination
 * with no existing page renders the shared <ComingSoon /> primitive,
 * per this phase's explicit "future pages appear as disabled/Coming
 * Soon, do not implement those modules" scope.
 *
 * Intentional behavior change from the pre-Phase-2 App.tsx: the default
 * landing page is now Overview (the new Dashboard), not Health -- this
 * is the point of "redesign the landing dashboard", not an oversight.
 * AdminApp.test.tsx is updated accordingly.
 */
function hasConsoleAccess(): boolean {
  return hasAdminAccess() || hasOrganizationsAccess()
}

export default function AdminApp() {
  return (
    <AuthGate hasAccess={hasConsoleAccess}>
      <AdminDashboard />
    </AuthGate>
  )
}

// Phase 3 PR2/PR3A: deep-link support for /organizations(/{id}) and
// /users(/{id}), using the browser's native History API directly --
// unchanged by Phase 2. No other page gained a distinct URL in the
// original design either, so Overview/Infrastructure/Coming-Soon pages
// don't get one now.
function orgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/organizations\/(\d+)$/)
  return m ? Number(m[1]) : null
}
function userIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/users\/(\d+)$/)
  return m ? Number(m[1]) : null
}
// PR11.3: /iam/{orgId} deep-links straight into that org's SSO settings,
// same convention as /organizations/{id} and /users/{id} above.
function ssoOrgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/iam\/(\d+)$/)
  return m ? Number(m[1]) : null
}
// PR11.4: /iam/service-accounts(/{orgId}) deep-links into
// ServiceAccountsPage -- distinct from /iam/{orgId} above (SSO) despite
// the shared /iam/ prefix; the 'api-keys' PageKey (nav item key stays
// stable) is only associated with this /iam/service-accounts/ path.
function serviceAccountsOrgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/iam\/service-accounts\/(\d+)$/)
  return m ? Number(m[1]) : null
}
// PR11.5.6: /security/mfa-policy/{orgId} deep-links straight into that
// org's MFA policy settings, same convention as /iam/{orgId}'s own SSO
// deep-link above.
function mfaPolicyOrgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/security\/mfa-policy\/(\d+)$/)
  return m ? Number(m[1]) : null
}
// PR14.5C: /billing/{orgId} deep-links straight into that org's billing
// dashboard, same convention as /iam/{orgId}'s own SSO deep-link above.
// Invoice detail (a level deeper still) is intentionally not URL-
// persisted -- same "hint only, no route of its own" precedent
// teamsOrgHint/rolesOrgHint already establish below, kept simple rather
// than adding a third path segment for one nested view.
function billingOrgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/billing\/(\d+)$/)
  return m ? Number(m[1]) : null
}

function AdminDashboard() {
  const canSeeOps = hasAdminAccess()
  const canSeeOrganizations = hasOrganizationsAccess()
  const canSeeUsers = hasPlatformAdminAccess()
  // PR11.4b: same gate as 'users' -- GET /platform/audit-events is
  // manage_all_orgs-gated, not org-scoped, so this is a flat platform-
  // wide page (no org-picker/deep-link, unlike 'iam'/'api-keys').
  const canSeeAuditLogs = hasPlatformAdminAccess()
  // PR11.5.6: same reasoning as canSeeAuditLogs -- GET /platform/users,
  // GET /platform/orgs, GET /platform/audit-events (everything the
  // Security Dashboard reads) are all manage_all_orgs-gated.
  const canSeeSecurityOverview = hasPlatformAdminAccess()

  const [active, setActive] = useState<PageKey>(() => {
    if (window.location.pathname.startsWith('/organizations')) return 'organizations'
    if (window.location.pathname.startsWith('/users')) return 'users'
    // /iam/service-accounts must be checked before the bare /iam prefix
    // below, or it would always match the SSO branch first.
    if (window.location.pathname.startsWith('/iam/service-accounts')) return 'api-keys'
    if (window.location.pathname.startsWith('/iam')) return 'iam'
    if (window.location.pathname.startsWith('/security/mfa-policy')) return 'mfa-policy'
    if (window.location.pathname.startsWith('/billing')) return 'billing'
    return 'overview'
  })
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(() => orgIdFromPath())
  const [selectedUserId, setSelectedUserId] = useState<number | null>(() => userIdFromPath())
  const [selectedSsoOrgId, setSelectedSsoOrgId] = useState<number | null>(() => ssoOrgIdFromPath())
  const [selectedServiceAccountsOrgId, setSelectedServiceAccountsOrgId] = useState<number | null>(() => serviceAccountsOrgIdFromPath())
  const [selectedMfaPolicyOrgId, setSelectedMfaPolicyOrgId] = useState<number | null>(() => mfaPolicyOrgIdFromPath())
  const [selectedBillingOrgId, setSelectedBillingOrgId] = useState<number | null>(() => billingOrgIdFromPath())
  // Not URL-persisted -- a lighter-weight UX detail than the deep-linked
  // org id itself, same "keep it simple" precedent the rest of this
  // routing already follows. Reset to the default whenever a fresh org
  // is selected via the picker (no tab preference to carry there).
  const [serviceAccountsInitialTab, setServiceAccountsInitialTab] = useState<'oauth-clients' | 'api-keys'>('oauth-clients')
  // PR11.2: "View all teams" / "View roles & permissions" on
  // OrganizationDetailPage land here pre-scoped to the org the admin was
  // already looking at -- a hint only, not a route of its own (there's no
  // /teams/{org_id} URL, unlike /organizations/{id}); TeamsPage/RolesPage
  // fall back to their own first-organization default if this is null.
  const [teamsOrgHint, setTeamsOrgHint] = useState<number | null>(null)
  const [rolesOrgHint, setRolesOrgHint] = useState<number | null>(null)
  // AuthGate has already resolved the session (and populated auth.ts's
  // module-level cache) by the time this component ever renders -- no
  // separate fetch or local "logged in as" state needed here.
  const user = getSessionUser()
  const [overallStatus, setOverallStatus] = useState<'UP' | 'WARN' | 'DOWN' | null>(null)
  const [generating, setGenerating] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    if (!canSeeOps) return
    const poll = async () => {
      try {
        const d = await fetchSummary()
        setOverallStatus(d.overall_status)
      } catch { /* status chip stays stale */ }
    }
    poll()
    const t = setInterval(poll, 15_000)
    return () => clearInterval(t)
  }, [canSeeOps])

  const pollReport = useCallback(async () => {
    if (!canSeeOps) return
    try {
      const s = await fetchReportStatus()
      if (s.status === 'running') {
        setGenerating(true)
        setTimeout(pollReport, 2000)
      } else {
        setGenerating(false)
      }
    } catch { /* ignore */ }
  }, [canSeeOps])

  useEffect(() => { pollReport() }, [pollReport])

  const handleGenerate = async () => {
    try {
      await triggerGenerate()
      setGenerating(true)
      setTimeout(pollReport, 2000)
    } catch { /* ignore */ }
  }

  // Keep the URL in sync with the Organizations/Users nav+detail state --
  // unchanged from the pre-Phase-2 behavior.
  useEffect(() => {
    const path =
      active === 'organizations' ? (selectedOrgId != null ? `/organizations/${selectedOrgId}` : '/organizations')
      : active === 'users' ? (selectedUserId != null ? `/users/${selectedUserId}` : '/users')
      : active === 'iam' ? (selectedSsoOrgId != null ? `/iam/${selectedSsoOrgId}` : '/iam')
      : active === 'api-keys' ? (selectedServiceAccountsOrgId != null ? `/iam/service-accounts/${selectedServiceAccountsOrgId}` : '/iam/service-accounts')
      : active === 'mfa-policy' ? (selectedMfaPolicyOrgId != null ? `/security/mfa-policy/${selectedMfaPolicyOrgId}` : '/security/mfa-policy')
      : active === 'billing' ? (selectedBillingOrgId != null ? `/billing/${selectedBillingOrgId}` : '/billing')
      : '/'
    if (window.location.pathname !== path) {
      window.history.pushState(null, '', path)
    }
  }, [active, selectedOrgId, selectedUserId, selectedSsoOrgId, selectedServiceAccountsOrgId, selectedMfaPolicyOrgId, selectedBillingOrgId])

  useEffect(() => {
    const onPopState = () => {
      if (window.location.pathname.startsWith('/organizations')) {
        setActive('organizations')
        setSelectedOrgId(orgIdFromPath())
      } else if (window.location.pathname.startsWith('/users')) {
        setActive('users')
        setSelectedUserId(userIdFromPath())
      } else if (window.location.pathname.startsWith('/iam/service-accounts')) {
        setActive('api-keys')
        setSelectedServiceAccountsOrgId(serviceAccountsOrgIdFromPath())
      } else if (window.location.pathname.startsWith('/iam')) {
        setActive('iam')
        setSelectedSsoOrgId(ssoOrgIdFromPath())
      } else if (window.location.pathname.startsWith('/security/mfa-policy')) {
        setActive('mfa-policy')
        setSelectedMfaPolicyOrgId(mfaPolicyOrgIdFromPath())
      } else if (window.location.pathname.startsWith('/billing')) {
        setActive('billing')
        setSelectedBillingOrgId(billingOrgIdFromPath())
      } else {
        setActive('overview')
        setSelectedOrgId(null)
        setSelectedUserId(null)
        setSelectedSsoOrgId(null)
        setSelectedServiceAccountsOrgId(null)
        setSelectedMfaPolicyOrgId(null)
        setSelectedBillingOrgId(null)
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const handleNavigate = (key: PageKey) => {
    setActive(key)
    if (key !== 'organizations') setSelectedOrgId(null)
    if (key !== 'users') setSelectedUserId(null)
    if (key !== 'iam') setSelectedSsoOrgId(null)
    if (key !== 'api-keys') setSelectedServiceAccountsOrgId(null)
    if (key !== 'mfa-policy') setSelectedMfaPolicyOrgId(null)
    if (key !== 'billing') setSelectedBillingOrgId(null)
    // A plain sidebar click (not a "View teams/roles" link) always starts
    // from TeamsPage/RolesPage's own default, not a stale hint left over
    // from a previous organization's detail page.
    if (key !== 'teams') setTeamsOrgHint(null)
    if (key !== 'roles') setRolesOrgHint(null)
  }

  const handleViewTeams = (orgId: number) => {
    setTeamsOrgHint(orgId)
    setActive('teams')
  }
  const handleViewRoles = (orgId: number) => {
    setRolesOrgHint(orgId)
    setActive('roles')
  }

  // PR11.3: cross-page navigation for OrganizationDetailPage's "Manage
  // SSO Settings" link -- unlike handleNavigate (a sidebar click, always
  // starts that destination at its list root), this jumps straight to
  // the 'iam' destination already deep-linked to one specific org, the
  // same one the link was clicked from.
  const navigateToSsoSettings = (orgId: number) => {
    setActive('iam')
    setSelectedSsoOrgId(orgId)
  }

  // PR11.4: same idea as navigateToSsoSettings, for OrganizationDetailPage's
  // "Manage Service Accounts"/"Manage API Keys" links -- also carries
  // which tab to land on.
  const navigateToServiceAccounts = (orgId: number, tab: 'oauth-clients' | 'api-keys' = 'oauth-clients') => {
    setActive('api-keys')
    setSelectedServiceAccountsOrgId(orgId)
    setServiceAccountsInitialTab(tab)
  }

  const handleSignOut = () => {
    // ProfileMenu already called auth.ts's logout() (server-side revoke)
    // before invoking this callback -- this just tells AuthGate to reset
    // to the anonymous state, the same event it already listens for.
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }

  return (
    <AppShell
      active={active}
      onNavigate={handleNavigate}
      user={user}
      onSignOut={handleSignOut}
      extraActions={canSeeOps ? (
        <StatusAndReportActions
          status={overallStatus}
          generating={generating}
          onRefresh={() => setRefreshKey(k => k + 1)}
          onGenerate={handleGenerate}
        />
      ) : undefined}
    >
      {renderPage(active, {
        canSeeOps, canSeeOrganizations, canSeeUsers, canSeeAuditLogs, canSeeSecurityOverview, refreshKey,
        selectedOrgId, setSelectedOrgId, selectedUserId, setSelectedUserId,
        teamsOrgHint, rolesOrgHint, onViewTeams: handleViewTeams, onViewRoles: handleViewRoles,
        selectedSsoOrgId, setSelectedSsoOrgId, navigateToSsoSettings,
        selectedServiceAccountsOrgId, setSelectedServiceAccountsOrgId, navigateToServiceAccounts,
        serviceAccountsInitialTab,
        selectedMfaPolicyOrgId, setSelectedMfaPolicyOrgId,
        selectedBillingOrgId, setSelectedBillingOrgId,
      })}
    </AppShell>
  )
}

interface RenderCtx {
  canSeeOps: boolean
  canSeeOrganizations: boolean
  canSeeUsers: boolean
  canSeeAuditLogs: boolean
  canSeeSecurityOverview: boolean
  refreshKey: number
  selectedOrgId: number | null
  setSelectedOrgId: (id: number | null) => void
  selectedUserId: number | null
  setSelectedUserId: (id: number | null) => void
  teamsOrgHint: number | null
  rolesOrgHint: number | null
  onViewTeams: (orgId: number) => void
  onViewRoles: (orgId: number) => void
  selectedSsoOrgId: number | null
  setSelectedSsoOrgId: (id: number | null) => void
  navigateToSsoSettings: (orgId: number) => void
  selectedServiceAccountsOrgId: number | null
  setSelectedServiceAccountsOrgId: (id: number | null) => void
  navigateToServiceAccounts: (orgId: number, tab?: 'oauth-clients' | 'api-keys') => void
  serviceAccountsInitialTab: 'oauth-clients' | 'api-keys'
  selectedMfaPolicyOrgId: number | null
  setSelectedMfaPolicyOrgId: (id: number | null) => void
  selectedBillingOrgId: number | null
  setSelectedBillingOrgId: (id: number | null) => void
}

function renderPage(active: PageKey, ctx: RenderCtx) {
  switch (active) {
    case 'overview':
      return <DashboardPage />

    case 'health':    return ctx.canSeeOps ? <HealthPage    refreshKey={ctx.refreshKey} /> : null
    case 'docker':    return ctx.canSeeOps ? <DockerPage    refreshKey={ctx.refreshKey} /> : null
    case 'ecosystem': return ctx.canSeeOps ? <EcosystemPage refreshKey={ctx.refreshKey} /> : null
    case 'config':    return ctx.canSeeOps ? <ConfigPage    refreshKey={ctx.refreshKey} /> : null
    case 'llms':      return ctx.canSeeOps ? <LlmPage       refreshKey={ctx.refreshKey} /> : null
    case 'cloud':     return ctx.canSeeOps ? <CloudPage     refreshKey={ctx.refreshKey} /> : null

    // PR A1: no org picker (unlike 'billing'/'iam' below) -- TES
    // self-scopes GET /api/runs to the caller's own organization_id
    // server-side, there is no "view another org" endpoint to pick one
    // for. Same canSeeOps gate the other Operations pages above use.
    case 'tool-execution':
      return ctx.canSeeOps ? <ToolExecutionPage /> : null

    // PR A2: no org picker, same reasoning as 'tool-execution' above --
    // model-registry has no organization concept to pick one for.
    case 'ai-models':
      return ctx.canSeeOps ? <AIModelsPage /> : null

    // PR A3: no org picker, same reasoning as 'tool-execution'/
    // 'ai-models' above -- workflow catalog isn't org-owned, and
    // GET /v1/runs isn't org-scoped upstream either (see
    // WorkflowsPage.tsx's own module comment).
    case 'workflows':
      return ctx.canSeeOps ? <WorkflowsPage /> : null

    // PR A4: 'rag' and 'pubmed' are two distinct nav entries pointing at
    // the same page -- RAG has no separate PubMed concept server-side
    // (see navigation.ts's own comment on this). No org picker: this
    // page's data isn't org-scoped, and isn't per-admin-authorized at
    // all (see RAGPage.tsx's own module comment) -- canSeeOps is the
    // only real gate here, not a visibility layer in front of a
    // separate backend check the way it is for the other Operations
    // pages above.
    case 'rag':
    case 'pubmed':
      return ctx.canSeeOps ? <RAGPage /> : null

    case 'organizations':
      if (!ctx.canSeeOrganizations) return null
      return ctx.selectedOrgId != null
        ? (
          <OrganizationDetailPage
            orgId={ctx.selectedOrgId}
            onBack={() => ctx.setSelectedOrgId(null)}
            onViewTeams={ctx.onViewTeams}
            onViewRoles={ctx.onViewRoles}
            onManageSso={ctx.navigateToSsoSettings}
            onManageServiceAccounts={ctx.navigateToServiceAccounts}
          />
        )
        : <OrganizationsPage onSelect={ctx.setSelectedOrgId} />

    case 'users':
      if (!ctx.canSeeUsers) return null
      return ctx.selectedUserId != null
        ? <UserDetailPage userId={ctx.selectedUserId} onBack={() => ctx.setSelectedUserId(null)} />
        : <UsersPage onSelect={ctx.setSelectedUserId} />

    // PR11.4b: flat platform-wide page, no org-picker/deep-link --
    // audit events span every organization, filtered in-page, not
    // reached by drilling into one org first.
    case 'audit-logs':
      if (!ctx.canSeeAuditLogs) return null
      return <AuditLogsPage />

    // PR-C: self-service, flat, no org-picker/deep-link and no gate --
    // same shape as 'overview' above (no `ctx.canSeeX` check either).
    // omnibioai-auth's GET /sessions already scopes every response to
    // the caller's own account server-side; there is no separate
    // permission this gate could usefully stand in front of.
    case 'sessions':
      return <SessionsPage />

    // PR11.2: same gate as 'organizations' -- see navigation.ts.
    case 'teams':
      if (!ctx.canSeeOrganizations) return null
      return <TeamsPage initialOrgId={ctx.teamsOrgHint} />

    case 'roles':
      if (!ctx.canSeeOrganizations) return null
      return <RolesPage initialOrgId={ctx.rolesOrgHint} />

    // PR11.3: SSO config is per-org, so this destination is a
    // "pick an org, then manage its SSO settings" flow, same list ->
    // detail shape as 'organizations' -- reusing OrganizationsPage as
    // the picker rather than building a second org-list component (see
    // docs/admin-console-pr11-sso-discovery.md). Same
    // hasOrganizationsAccess gate navigation.ts's own `visible` uses for
    // this nav item; the actual manage_sso/override_sso_enforcement
    // decisions happen entirely backend-side once a specific org is
    // open (SSOSettingsPage never assumes access just because this gate
    // passed).
    case 'iam':
      if (!ctx.canSeeOrganizations) return null
      return ctx.selectedSsoOrgId != null
        ? <SSOSettingsPage orgId={ctx.selectedSsoOrgId} onBack={() => ctx.setSelectedSsoOrgId(null)} />
        : <OrganizationsPage onSelect={ctx.setSelectedSsoOrgId} />

    // PR11.5.6: flat, no org-picker/deep-link -- same shape as
    // 'audit-logs' above, for the identical reason (every API this page
    // reads is manage_all_orgs-gated, not org-scoped).
    case 'security-overview':
      if (!ctx.canSeeSecurityOverview) return null
      return <SecurityDashboardPage />

    // PR11.5.6: MFA policy is per-org, so this destination is a "pick
    // an org, then manage its MFA policy" flow, same list -> detail
    // shape as 'iam' immediately above (and the identical
    // hasOrganizationsAccess gate) -- see
    // docs/pr11-5-6-security-ui-discovery.md SS2.
    case 'mfa-policy':
      if (!ctx.canSeeOrganizations) return null
      return ctx.selectedMfaPolicyOrgId != null
        ? <OrganizationMFAPolicyPage orgId={ctx.selectedMfaPolicyOrgId} onBack={() => ctx.setSelectedMfaPolicyOrgId(null)} />
        : <OrganizationsPage onSelect={ctx.setSelectedMfaPolicyOrgId} />

    // PR11.4: API keys/OAuth clients are per-org, so this destination is
    // a "pick an org, then manage its service accounts" flow, same
    // list -> detail shape as 'organizations' -- reusing
    // OrganizationsPage as the picker rather than building a second org-
    // list component (see docs/admin-console-pr11-service-accounts-
    // discovery.md). Same hasOrganizationsAccess gate navigation.ts's
    // own `visible` uses for this nav item; the actual
    // manage_api_keys/manage_oauth_clients decisions happen entirely
    // backend-side once a specific org is open.
    case 'api-keys':
      if (!ctx.canSeeOrganizations) return null
      return ctx.selectedServiceAccountsOrgId != null
        ? (
          <ServiceAccountsPage
            orgId={ctx.selectedServiceAccountsOrgId}
            onBack={() => ctx.setSelectedServiceAccountsOrgId(null)}
            initialTab={ctx.serviceAccountsInitialTab}
          />
        )
        : <OrganizationsPage onSelect={ctx.setSelectedServiceAccountsOrgId} />

    // PR14.5C: billing visibility/invoices are per-org, so this
    // destination is a "pick an org, then view its billing dashboard"
    // flow, same list -> detail shape as 'iam'/'api-keys' -- reusing
    // OrganizationsPage as the picker rather than building a second
    // org-list component. Same hasOrganizationsAccess gate navigation.ts's
    // own `visible` uses for this nav item; the actual authorization
    // (org member or platform admin) happens entirely backend-side once
    // a specific org is open (BillingPage never assumes access just
    // because this gate passed).
    case 'billing':
      if (!ctx.canSeeOrganizations) return null
      return ctx.selectedBillingOrgId != null
        ? <BillingPage orgId={ctx.selectedBillingOrgId} onBack={() => ctx.setSelectedBillingOrgId(null)} />
        : <OrganizationsPage onSelect={ctx.setSelectedBillingOrgId} />

    // PR E1: no org picker -- omnibioai-auth's GlobalConfig is
    // platform-wide, not org-scoped. Same canSeeOps gate the other
    // Operations-family pages above use.
    case 'settings':
      return ctx.canSeeOps ? <PlatformSettingsPage /> : null

    default: {
      const item = findNavItem(active)
      return <ComingSoon title={item?.label ?? 'Coming soon'} />
    }
  }
}

/** The pre-existing status chip + Refresh/Generate Report controls,
 * relocated unchanged in behavior (same state/handlers) from the old
 * Header.tsx into AppShell's extraActions slot -- clicking Refresh still
 * bumps the same refreshKey every ops page's own fetch effect already
 * depended on before Phase 2. */
function StatusAndReportActions({
  status, generating, onRefresh, onGenerate,
}: {
  status: 'UP' | 'WARN' | 'DOWN' | null
  generating: boolean
  onRefresh: () => void
  onGenerate: () => void
}) {
  const cfg = status === 'UP'
    ? { label: 'All systems operational', color: '#22c55e' }
    : status === 'WARN'
      ? { label: 'Services degraded', color: '#f59e0b' }
      : status === 'DOWN'
        ? { label: 'One or more systems down', color: '#ef4444' }
        : null

  return (
    <>
      {cfg && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: cfg.color }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: cfg.color }} />
          {cfg.label}
        </span>
      )}
      <button
        onClick={onRefresh}
        style={{
          fontSize: 12, fontWeight: 600, padding: '6px 12px',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          background: 'var(--bg2)', color: 'var(--text2)',
        }}
      >
        ↺ Refresh
      </button>
      <button
        onClick={onGenerate}
        disabled={generating}
        style={{
          fontSize: 12, fontWeight: 600, padding: '6px 12px',
          border: 'none', borderRadius: 'var(--radius-sm)',
          background: generating ? 'rgba(0,229,160,0.4)' : 'var(--accent)',
          color: '#000', cursor: generating ? 'not-allowed' : 'pointer',
        }}
      >
        {generating ? 'Generating…' : '⊕ Generate Report'}
      </button>
    </>
  )
}
