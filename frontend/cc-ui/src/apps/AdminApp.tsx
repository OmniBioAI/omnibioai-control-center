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
import OrganizationsPage from '../pages/OrganizationsPage'
import OrganizationDetailPage from '../pages/OrganizationDetailPage'
import UsersPage from '../pages/UsersPage'
import UserDetailPage from '../pages/UserDetailPage'
import ServiceAccountsPage from '../pages/identity/ServiceAccountsPage'
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
// PR11.4: /iam/service-accounts(/{orgId}) deep-links into
// ServiceAccountsPage, same convention as /organizations/{id} and
// /users/{id} above -- the task's own required route, distinct from the
// 'api-keys' PageKey (nav item key stays stable; only the URL groups it
// under /iam/).
function serviceAccountsOrgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/iam\/service-accounts\/(\d+)$/)
  return m ? Number(m[1]) : null
}

function AdminDashboard() {
  const canSeeOps = hasAdminAccess()
  const canSeeOrganizations = hasOrganizationsAccess()
  const canSeeUsers = hasPlatformAdminAccess()

  const [active, setActive] = useState<PageKey>(() => {
    if (window.location.pathname.startsWith('/organizations')) return 'organizations'
    if (window.location.pathname.startsWith('/users')) return 'users'
    if (window.location.pathname.startsWith('/iam/service-accounts')) return 'api-keys'
    return 'overview'
  })
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(() => orgIdFromPath())
  const [selectedUserId, setSelectedUserId] = useState<number | null>(() => userIdFromPath())
  const [selectedServiceAccountsOrgId, setSelectedServiceAccountsOrgId] = useState<number | null>(() => serviceAccountsOrgIdFromPath())
  // Not URL-persisted -- a lighter-weight UX detail than the deep-linked
  // org id itself, same "keep it simple" precedent the rest of this
  // routing already follows. Reset to the default whenever a fresh org
  // is selected via the picker (no tab preference to carry there).
  const [serviceAccountsInitialTab, setServiceAccountsInitialTab] = useState<'oauth-clients' | 'api-keys'>('oauth-clients')
  // AuthGate has already resolved the session (and populated auth.ts's
  // module-level cache) by the time this component ever renders -- no
  // separate fetch or local "logged in as" state needed here.
  const user = getSessionUser()
  const [overallStatus, setOverallStatus] = useState<'UP' | 'WARN' | 'DOWN' | null>(null)
  const [reportExists, setReportExists] = useState(false)
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
      setReportExists(s.report_exists)
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
      : active === 'api-keys' ? (selectedServiceAccountsOrgId != null ? `/iam/service-accounts/${selectedServiceAccountsOrgId}` : '/iam/service-accounts')
      : '/'
    if (window.location.pathname !== path) {
      window.history.pushState(null, '', path)
    }
  }, [active, selectedOrgId, selectedUserId, selectedServiceAccountsOrgId])

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
      } else {
        setActive('overview')
        setSelectedOrgId(null)
        setSelectedUserId(null)
        setSelectedServiceAccountsOrgId(null)
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const handleNavigate = (key: PageKey) => {
    setActive(key)
    if (key !== 'organizations') setSelectedOrgId(null)
    if (key !== 'users') setSelectedUserId(null)
    if (key !== 'api-keys') setSelectedServiceAccountsOrgId(null)
  }

  // PR11.4: cross-page navigation for OrganizationDetailPage's "Manage
  // Service Accounts"/"Manage API Keys" links -- unlike handleNavigate
  // (a sidebar click, always starts that destination at its list root),
  // this jumps straight to the 'api-keys' destination already
  // deep-linked to one specific org, the same one the link was clicked
  // from.
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
          reportExists={reportExists}
          onRefresh={() => setRefreshKey(k => k + 1)}
          onGenerate={handleGenerate}
        />
      ) : undefined}
    >
      {renderPage(active, {
        canSeeOps, canSeeOrganizations, canSeeUsers, refreshKey,
        selectedOrgId, setSelectedOrgId, selectedUserId, setSelectedUserId,
        selectedServiceAccountsOrgId, setSelectedServiceAccountsOrgId, navigateToServiceAccounts,
        serviceAccountsInitialTab,
      })}
    </AppShell>
  )
}

interface RenderCtx {
  canSeeOps: boolean
  canSeeOrganizations: boolean
  canSeeUsers: boolean
  refreshKey: number
  selectedOrgId: number | null
  setSelectedOrgId: (id: number | null) => void
  selectedUserId: number | null
  setSelectedUserId: (id: number | null) => void
  selectedServiceAccountsOrgId: number | null
  setSelectedServiceAccountsOrgId: (id: number | null) => void
  navigateToServiceAccounts: (orgId: number, tab?: 'oauth-clients' | 'api-keys') => void
  serviceAccountsInitialTab: 'oauth-clients' | 'api-keys'
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

    case 'organizations':
      if (!ctx.canSeeOrganizations) return null
      return ctx.selectedOrgId != null
        ? (
          <OrganizationDetailPage
            orgId={ctx.selectedOrgId}
            onBack={() => ctx.setSelectedOrgId(null)}
            onManageServiceAccounts={(orgId, tab) => ctx.navigateToServiceAccounts(orgId, tab)}
          />
        )
        : <OrganizationsPage onSelect={ctx.setSelectedOrgId} />

    case 'users':
      if (!ctx.canSeeUsers) return null
      return ctx.selectedUserId != null
        ? <UserDetailPage userId={ctx.selectedUserId} onBack={() => ctx.setSelectedUserId(null)} />
        : <UsersPage onSelect={ctx.setSelectedUserId} />

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
  status, generating, reportExists, onRefresh, onGenerate,
}: {
  status: 'UP' | 'WARN' | 'DOWN' | null
  generating: boolean
  reportExists: boolean
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
      {reportExists && (
        <a
          href="/"
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}
        >
          View Report ↗
        </a>
      )}
    </>
  )
}
