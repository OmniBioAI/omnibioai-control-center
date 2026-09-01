import { useState, useEffect, useCallback } from 'react'
import { fetchReportData, fetchReportStatus } from '../api'
import type { ReportData } from '../api'
import {
  C, ProjectsTab, LanguagesTab, CoverageTab, GitStatusTab,
} from './EcosystemReportTabs'

/**
 * Public Read-Only Control Center architecture: the anonymous
 * ControlApp's Ecosystem Report page. Deliberately a standalone module
 * that imports only from ./EcosystemReportTabs (Projects/Languages/
 * Coverage/Ecosystem-Status, all sourced from GET /report/data, already
 * public) and never from ./EcosystemPage.tsx -- so this page's bundle
 * can never contain ArchTab, the LANES architecture-diagram data (real
 * internal service names, internal ports, tech-stack descriptions --
 * e.g. "auth-service · bcrypt · JWT · port 8001"), HealthTab (GET
 * /summary, platform.manage_infra-gated), or GenerateCta (POST
 * /report/generate, platform.manage_content-gated). Verified by build-
 * output inspection, not just by import inspection -- see
 * docs/public-control-center.md.
 *
 * No mutation control here at all (unlike EcosystemPage.tsx's
 * GenerateCta): "no mutations" is one of this dashboard's own stated
 * public-surface requirements, and POST /report/generate would 401 for
 * an anonymous caller regardless -- an inert button has no place on an
 * always-anonymous page. If no report has been generated yet, this page
 * just says so.
 */
type SubTab = 'projects' | 'languages' | 'coverage' | 'gitStatus'

const SUBTABS: { id: SubTab; label: string }[] = [
  { id: 'projects',  label: 'Projects' },
  { id: 'languages', label: 'Languages' },
  { id: 'coverage',  label: 'Code Coverage' },
  { id: 'gitStatus', label: 'Ecosystem Status' },
]

function NoReportYet() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 20px', gap: 10 }}>
      <div style={{ fontSize: 40, opacity: 0.25 }}>⊞</div>
      <div style={{ fontWeight: 700, fontSize: 16, color: C.text }}>No report data yet</div>
      <div style={{ fontSize: 12, color: C.muted, textAlign: 'center', maxWidth: 360 }}>
        Check back soon -- this report is regenerated periodically.
      </div>
    </div>
  )
}

export default function PublicEcosystemPage({ refreshKey }: { refreshKey: number }) {
  const [subTab, setSubTab] = useState<SubTab>('projects')
  const [reportData, setReportData] = useState<ReportData | null>(null)
  const [lastGen, setLastGen] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      const d = await fetchReportData()
      setReportData(d)
    } catch { /* ignore -- NoReportYet covers this */ }
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      const s = await fetchReportStatus()
      if (s.report_generated_at) setLastGen(s.report_generated_at)
      if (s.report_exists) loadData()
    } catch { /* ignore */ }
  }, [loadData])

  useEffect(() => {
    loadData()
    loadStatus()
  }, [refreshKey, loadData, loadStatus])

  return (
    // No negative margin here (this page used to carry `margin: '-24px
    // -28px -48px'`, copied over from EcosystemPage.tsx's dark-card
    // wrapper by the split -- see that file's own comment for the
    // AdminApp/sidebar half of this history). In ControlApp this div
    // sits inside a wrapper with `padding: '24px 28px 48px'`
    // (ControlApp.tsx), and this page is the only one of ControlApp's
    // tabs that tried to cancel it -- LlmPage/CloudPage both render a
    // bare `<div>` and take that padding as-is. The negative margin
    // pulled this tab's content flush to the container's outer edge
    // and relied on its own `padding: 20` instead, so Ecosystem Report
    // sat inset 20px from the content area while every sibling tab
    // sat inset 24-28-48px -- a visible seam when switching tabs, not
    // sidebar clipping (ControlApp has no sidebar), but the same root
    // cause: this wrapper's own `padding: 20` is enough on its own,
    // same as every sibling tab relies on the parent's padding alone.
    <div style={{ background: C.bg, borderRadius: 14, padding: 20, minHeight: 'calc(100vh - 100px)', color: C.text }}>
      {/* Hero */}
      <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: `1px solid ${C.border}` }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, marginBottom: 4 }}>Ecosystem Report</h1>
        <p style={{ fontSize: 13, color: C.muted }}>Project and codebase health metrics</p>
        {lastGen && <p style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>Last generated: {new Date(lastGen).toLocaleString()}</p>}
      </div>

      {/* Sub-tab bar */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}`, marginBottom: 20 }}>
        {SUBTABS.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            style={{
              padding: '10px 16px', fontSize: 13, background: 'none', border: 'none', cursor: 'pointer',
              fontWeight: subTab === t.id ? 700 : 400,
              color: subTab === t.id ? C.teal : C.muted,
              borderBottom: `2px solid ${subTab === t.id ? C.teal : 'transparent'}`,
              marginBottom: -1, transition: 'color 0.12s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {!reportData && <NoReportYet />}
      {reportData && subTab === 'projects'  && <ProjectsTab data={reportData} />}
      {reportData && subTab === 'languages' && <LanguagesTab data={reportData} />}
      {reportData && subTab === 'coverage'  && <CoverageTab data={reportData} />}
      {reportData && subTab === 'gitStatus' && <GitStatusTab data={reportData} />}
    </div>
  )
}
