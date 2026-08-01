import { useState, useEffect, useCallback } from 'react'
import { fetchSummary, fetchReportStatus, triggerGenerate } from './api'
import {
  getToken, clearToken, ensureSession, hasAdminAccess, hasOrganizationsAccess,
  hasPlatformAdminAccess, UNAUTHORIZED_EVENT,
} from './auth'
import type { SessionUser } from './auth'
import Header from './components/Header'
import type { Tab } from './components/Header'
import LoginScreen from './components/LoginScreen'
import AccessDenied from './components/AccessDenied'
import HealthPage from './pages/HealthPage'
import DockerPage from './pages/DockerPage'
import EcosystemPage from './pages/EcosystemPage'
import ConfigPage from './pages/ConfigPage'
import LlmPage from './pages/LlmPage'
import CloudPage from './pages/CloudPage'
import OrganizationsPage from './pages/OrganizationsPage'
import OrganizationDetailPage from './pages/OrganizationDetailPage'
import UsersPage from './pages/UsersPage'
import UserDetailPage from './pages/UserDetailPage'

type AuthState = 'resolving' | 'anonymous' | 'denied' | 'admin'

// Phase 3 PR2: the gate below widened from hasAdminAccess() alone to also
// admit hasOrganizationsAccess() -- an org_admin or platform_admin with no
// global "admin" role must still reach the Organizations page. This is a
// deliberate, minimal widening of the one existing App-level gate, not the
// full admin.omnibioai.org/control.omnibioai.org build split the original
// Phase 3 blueprint envisioned (that split is not implemented in this
// repository as of this PR -- verified directly). See auth.ts's
// hasOrganizationsAccess() and this PR's implementation report.
function hasConsoleAccess(): boolean {
  return hasAdminAccess() || hasOrganizationsAccess()
}

export default function App() {
  const [state, setState] = useState<AuthState>('resolving')
  const [user, setUser] = useState<SessionUser | null>(null)

  const resolve = useCallback(async () => {
    if (!getToken()) {
      setState('anonymous')
      return
    }
    const resolved = await ensureSession()
    setUser(resolved)
    setState(resolved && hasConsoleAccess() ? 'admin' : resolved ? 'denied' : 'anonymous')
  }, [])

  useEffect(() => {
    resolve()
  }, [resolve])

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null)
      setState('anonymous')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  if (state === 'resolving') {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg)', color: 'var(--muted)', fontFamily: 'var(--mono)', fontSize: 13,
      }}>
        Authenticating…
      </div>
    )
  }

  if (state === 'anonymous') {
    return (
      <LoginScreen
        onSuccess={(loggedInUser) => {
          setUser(loggedInUser)
          setState(loggedInUser && hasConsoleAccess() ? 'admin' : loggedInUser ? 'denied' : 'anonymous')
        }}
      />
    )
  }

  if (state === 'denied') {
    return (
      <AccessDenied
        user={user}
        onSignOut={() => {
          clearToken()
          setUser(null)
          setState('anonymous')
        }}
      />
    )
  }

  return <Dashboard />
}

// Phase 3 PR2: minimal deep-link support for /organizations and
// /organizations/{id}, using the browser's native History API directly
// rather than adding a router dependency -- this app has none today (a
// deliberate choice worth revisiting once the admin console grows past a
// couple of deep-linkable pages, per this PR's implementation report),
// and every other tab still has no distinct URL, unchanged.
function orgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/organizations\/(\d+)$/)
  return m ? Number(m[1]) : null
}

// Phase 3 PR3A: same pattern, extended to /users and /users/{id}.
function userIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/users\/(\d+)$/)
  return m ? Number(m[1]) : null
}

function Dashboard() {
  const canSeeOps = hasAdminAccess()
  const canSeeOrganizations = hasOrganizationsAccess()
  const canSeeUsers = hasPlatformAdminAccess()

  const [tab, setTab] = useState<Tab>(() => {
    if (window.location.pathname.startsWith('/organizations')) return 'organizations'
    if (window.location.pathname.startsWith('/users')) return 'users'
    return canSeeOps ? 'health' : canSeeOrganizations ? 'organizations' : 'users'
  })
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(() => orgIdFromPath())
  const [selectedUserId, setSelectedUserId] = useState<number | null>(() => userIdFromPath())
  const [overallStatus, setOverallStatus] = useState<'UP' | 'WARN' | 'DOWN' | null>(null)
  const [reportExists, setReportExists] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  // Ops-only polling: skipped entirely for a caller who can't see the ops
  // tabs at all (org_admin/platform_admin with no global "admin" role) --
  // otherwise this silently fires a doomed-to-403 request every 15s for
  // an audience this page was never shown to.
  useEffect(() => {
    if (!canSeeOps) return
    const poll = async () => {
      try {
        const d = await fetchSummary()
        setOverallStatus(d.overall_status)
      } catch { /* sidebar stays stale */ }
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

  // Keep the URL in sync with the Organizations/Users tab+detail state --
  // every other tab is left exactly as before (no distinct URL).
  useEffect(() => {
    const path =
      tab === 'organizations' ? (selectedOrgId != null ? `/organizations/${selectedOrgId}` : '/organizations')
      : tab === 'users' ? (selectedUserId != null ? `/users/${selectedUserId}` : '/users')
      : '/'
    if (window.location.pathname !== path) {
      window.history.pushState(null, '', path)
    }
  }, [tab, selectedOrgId, selectedUserId])

  // Browser back/forward.
  useEffect(() => {
    const onPopState = () => {
      if (window.location.pathname.startsWith('/organizations')) {
        setTab('organizations')
        setSelectedOrgId(orgIdFromPath())
      } else if (window.location.pathname.startsWith('/users')) {
        setTab('users')
        setSelectedUserId(userIdFromPath())
      } else {
        setTab(canSeeOps ? 'health' : canSeeOrganizations ? 'organizations' : 'users')
        setSelectedOrgId(null)
        setSelectedUserId(null)
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [canSeeOps, canSeeOrganizations])

  const handleTab = (t: Tab) => {
    setTab(t)
    if (t !== 'organizations') setSelectedOrgId(null)
    if (t !== 'users') setSelectedUserId(null)
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' }}>
      <Header
        tab={tab}
        onTab={handleTab}
        status={overallStatus}
        generating={generating}
        reportExists={reportExists}
        onRefresh={() => setRefreshKey(k => k + 1)}
        onGenerate={handleGenerate}
        showOpsTabs={canSeeOps}
        showOrganizationsTab={canSeeOrganizations}
        showUsersTab={canSeeUsers}
      />
      {/* 56px header + 44px tab bar = 100px offset */}
      <div style={{ paddingTop: 100 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '24px 28px 48px' }}>
          {tab === 'health'    && canSeeOps && <HealthPage    refreshKey={refreshKey} />}
          {tab === 'docker'    && canSeeOps && <DockerPage    refreshKey={refreshKey} />}
          {tab === 'ecosystem' && canSeeOps && <EcosystemPage refreshKey={refreshKey} />}
          {tab === 'config'    && canSeeOps && <ConfigPage    refreshKey={refreshKey} />}
          {tab === 'llms'      && canSeeOps && <LlmPage       refreshKey={refreshKey} />}
          {tab === 'cloud'     && canSeeOps && <CloudPage     refreshKey={refreshKey} />}
          {tab === 'organizations' && canSeeOrganizations && (
            selectedOrgId != null
              ? <OrganizationDetailPage orgId={selectedOrgId} onBack={() => setSelectedOrgId(null)} />
              : <OrganizationsPage onSelect={setSelectedOrgId} />
          )}
          {tab === 'users' && canSeeUsers && (
            selectedUserId != null
              ? <UserDetailPage userId={selectedUserId} onBack={() => setSelectedUserId(null)} />
              : <UsersPage onSelect={setSelectedUserId} />
          )}
        </div>
      </div>
    </div>
  )
}
