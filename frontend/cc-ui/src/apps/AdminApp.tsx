import { useState, useEffect, useCallback } from 'react'
import { fetchSummary, fetchReportStatus, triggerGenerate } from '../api'
import {
  hasAdminAccess, hasOrganizationsAccess, hasPlatformAdminAccess,
} from '../auth'
import Header from '../components/Header'
import type { Tab } from '../components/Header'
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
import AuthGate from './AuthGate'

/**
 * Admin Console dual build architecture -- built with VITE_APP_MODE=admin,
 * served at admin.omnibioai.org. Contains everything the pre-split
 * App.tsx did: the ops pages (Health/Docker/Ecosystem/Config/LLMs/Cloud)
 * AND the enterprise console (Organizations, Organization Details, Users,
 * User Details -- Roles/Permissions/Teams are components rendered inside
 * OrganizationDetailPage, not separate pages, so they come along
 * automatically). This is a relocation of the pre-split App.tsx's
 * behavior, not a rewrite -- see git history for the byte-for-byte
 * equivalent prior version.
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

// Phase 3 PR2: deep-link support for /organizations and
// /organizations/{id}, using the browser's native History API directly
// rather than adding a router dependency -- this app still has none (a
// deliberate choice worth revisiting once the admin console grows past a
// couple of deep-linkable pages -- not this PR's scope, which is the
// build split itself, not a router migration).
function orgIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/organizations\/(\d+)$/)
  return m ? Number(m[1]) : null
}

// Phase 3 PR3A: same pattern, extended to /users and /users/{id}.
function userIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/users\/(\d+)$/)
  return m ? Number(m[1]) : null
}

function AdminDashboard() {
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
