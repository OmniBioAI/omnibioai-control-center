import { useState, useEffect, useCallback } from 'react'
import { fetchHealth, fetchReportStatus } from '../api'
import { clearToken } from '../auth'
import Header from '../components/Header'
import type { Tab } from '../components/Header'
import PublicHealthPage from '../pages/PublicHealthPage'
import EcosystemPage from '../pages/EcosystemPage'
import LlmPage from '../pages/LlmPage'
import CloudPage from '../pages/CloudPage'
import IntegrationsPage from '../pages/IntegrationsPage'

/**
 * Public Read-Only Control Center architecture -- built with
 * VITE_APP_MODE=control, served at control.omnibioai.org. This build is
 * now a genuinely anonymous, public dashboard: no AuthGate, no login
 * screen, no token of any kind is required or sent. See
 * docs/public-control-center.md for the full investigation this PR
 * implements.
 *
 * Health, Ecosystem Report, LLMs, Cloud, Integrations are exactly the
 * pages whose backend routes are safe for anonymous access (health_
 * router/report_router/llm_router/cloud_router/integrations_router carry
 * no permission dependency in main.py, and none of their response shapes
 * contain a per-user identifier, credential, or internal topology
 * detail -- confirmed by reading each one directly, not assumed; see
 * test_public_dashboard_no_leak.py for the regression guard).
 *
 * Docker and Config are deliberately NOT here anymore -- both call
 * backend routes gated behind platform.manage_infra (docker_router/
 * config_router in main.py), and per this PR's own task brief, "if
 * Docker/Config cannot safely coexist with anonymous ControlApp
 * rendering, remove them ... and leave them available through the
 * authenticated admin surface instead." They remain fully reachable,
 * unchanged, through AdminApp's own Infrastructure section
 * (navigation.ts) -- this is a page-set change in this one build only,
 * not a removal of the feature or a weakening of its backend gate.
 *
 * Same reasoning as before for what's absent from this module's own
 * import graph (still verified by ControlApp.test.tsx's own
 * source-text check): Organizations/Users/Roles/Teams/etc. were never
 * here and still aren't.
 */
export default function ControlApp() {
  return <ControlDashboard />
}

function ControlDashboard() {
  const [tab, setTab] = useState<Tab>('health')
  const [overallStatus, setOverallStatus] = useState<'UP' | 'WARN' | 'DOWN' | null>(null)
  const [reportExists, setReportExists] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  // This build never operates in an authenticated mode -- there is no
  // login screen to reach one from. Clearing unconditionally on mount
  // (rather than simply never reading it) means every fetch below runs
  // with zero chance of forwarding a token that happens to be sitting in
  // this origin's storage (e.g. a stale value from a build served on a
  // shared origin in local dev) -- "do not send a JWT merely because one
  // happens to exist" holds even in that edge case, not just in the
  // normal cross-origin-isolated control.omnibioai.org/admin.omnibioai.org
  // production topology where it couldn't happen anyway.
  useEffect(() => {
    clearToken()
  }, [])

  useEffect(() => {
    const poll = async () => {
      try {
        await fetchHealth()
        setOverallStatus('UP')
      } catch {
        setOverallStatus('DOWN')
      }
    }
    poll()
    const t = setInterval(poll, 15_000)
    return () => clearInterval(t)
  }, [])

  const pollReport = useCallback(async () => {
    try {
      const s = await fetchReportStatus()
      setReportExists(s.report_exists)
      if (s.status === 'running') {
        setTimeout(pollReport, 2000)
      }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { pollReport() }, [pollReport])

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' }}>
      <Header
        tab={tab}
        onTab={setTab}
        status={overallStatus}
        reportExists={reportExists}
        onRefresh={() => setRefreshKey(k => k + 1)}
        showOpsTabs={true}
        showOrganizationsTab={false}
        showUsersTab={false}
      />
      {/* 56px header + 44px tab bar = 100px offset */}
      <div style={{ paddingTop: 100 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '24px 28px 48px' }}>
          {tab === 'health'       && <PublicHealthPage refreshKey={refreshKey} />}
          {tab === 'ecosystem'    && <EcosystemPage     refreshKey={refreshKey} />}
          {tab === 'llms'         && <LlmPage           refreshKey={refreshKey} />}
          {tab === 'cloud'        && <CloudPage         refreshKey={refreshKey} />}
          {tab === 'integrations' && <IntegrationsPage />}
        </div>
      </div>
    </div>
  )
}
