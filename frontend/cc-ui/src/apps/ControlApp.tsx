import { useState, useEffect } from 'react'
import { fetchHealth } from '../api'
import { clearToken } from '../auth'
import Header from '../components/Header'
// Website palette and layout rules, scoped to .public-brand (see the file).
import '../public-brand.css'

const BRAND_FONTS_HREF = 'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Playfair+Display:wght@700&display=swap'

// Loaded at runtime rather than via a CSS @import so the admin bundle,
// which also receives public-brand.css, never downloads these fonts.
function useBrandFonts() {
  useEffect(() => {
    if (document.querySelector(`link[href="${BRAND_FONTS_HREF}"]`)) return
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = BRAND_FONTS_HREF
    document.head.appendChild(link)
  }, [])
}
import type { Tab } from '../components/Header'
import PublicOverviewPage from '../pages/PublicOverviewPage'
import PublicEvidencePage from '../pages/PublicEvidencePage'
import PublicEcosystemPage from '../pages/PublicEcosystemPage'

/**
 * Public Read-Only Control Center architecture -- built with
 * VITE_APP_MODE=control, served at control.omnibioai.org. This build is
 * now a genuinely anonymous, public dashboard: no AuthGate, no login
 * screen, no token of any kind is required or sent. See
 * docs/public-control-center.md for the full investigation this PR
 * implements.
 *
 Public page set (2026-09-25 showcase trim): Overview, Evidence and
 * Ecosystem Report, each reachable at its own URL (/overview, /evidence,
 * /ecosystem; / opens Overview) so a tab can be linked directly. The
 * former Health, LLMs, Cloud and Integrations tabs were operator detail:
 * the Overview already shows control-center status, execution backends
 * and AI platform counts, and those pages remain in AdminApp. Every
 * route these pages call answers anonymously with its public shape
 * (core/public_view.py, test_public_dashboard_no_leak.py). Ecosystem
 * Report renders via PublicEcosystemPage.tsx here, NOT the full
 * EcosystemPage.tsx AdminApp uses -- that file also contains ArchTab's
 * static internal-topology map (real service names/ports/tech stack)
 * and the /summary-sourced HealthTab, neither safe for anonymous
 * access; see PublicEcosystemPage.tsx's own doc comment and
 * docs/public-control-center.md.
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
export const TAB_PATHS: Record<Tab, string> = {
  overview: '/overview',
  evidence: '/evidence',
  ecosystem: '/ecosystem',
}

const TAB_TITLES: Record<Tab, string> = {
  overview: 'Platform Overview',
  evidence: 'Evidence',
  ecosystem: 'Ecosystem Report',
}

/** '/', unknown paths and trailing slashes all resolve to a real tab. */
export function tabFromPath(pathname: string): Tab {
  const path = pathname.replace(/\/+$/, '') || '/'
  const match = (Object.keys(TAB_PATHS) as Tab[]).find(t => TAB_PATHS[t] === path)
  return match ?? 'overview'
}

export default function ControlApp() {
  return <ControlDashboard />
}

function ControlDashboard() {
  useBrandFonts()
  const [tab, setTabState] = useState<Tab>(() => tabFromPath(window.location.pathname))
  const [overallStatus, setOverallStatus] = useState<'UP' | 'WARN' | 'DOWN' | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  // Each tab has its own URL so it can be shared; Back/Forward move
  // between tabs.
  const setTab = (next: Tab) => {
    if (next === tab) return
    window.history.pushState(null, '', TAB_PATHS[next])
    setTabState(next)
    window.scrollTo(0, 0)
  }

  useEffect(() => {
    const onPop = () => setTabState(tabFromPath(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    document.title = `OmniBioAI — ${TAB_TITLES[tab]}`
  }, [tab])

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

  return (
    <div className="public-brand" style={{ minHeight: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' }}>
      <Header
        tab={tab}
        onTab={setTab}
        status={overallStatus}
        onRefresh={() => setRefreshKey(k => k + 1)}
      />
      {/* 56px header + 44px tab bar = 100px offset */}
      <div style={{ paddingTop: 100 }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '24px 28px 48px' }}>
          {tab === 'overview'  && <PublicOverviewPage  refreshKey={refreshKey} />}
          {tab === 'evidence'  && <PublicEvidencePage  refreshKey={refreshKey} />}
          {tab === 'ecosystem' && <PublicEcosystemPage refreshKey={refreshKey} />}
        </div>
      </div>
    </div>
  )
}
