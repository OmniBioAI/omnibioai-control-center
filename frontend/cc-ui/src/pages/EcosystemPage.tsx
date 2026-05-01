import { useState, useEffect } from 'react'
import type { ServiceResult } from '../api'
import { fetchSummary, fetchReportStatus, triggerGenerate } from '../api'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:7070'

type SubTab = 'architecture' | 'projects' | 'languages' | 'coverage'

/* ── Architecture diagram ───────────────────────────────────── */
const TIER_MAP: Record<string, string> = {
  omnibioai:        'Frontend',
  'lims-x':         'Frontend',
  tes:              'Execution',
  toolserver:       'Execution',
  'model-registry': 'ML + AI',
  mysql:            'Data',
  redis:            'Data',
}
const TIER_ORDER = ['Frontend', 'Execution', 'Data', 'ML + AI']
const TIER_COLORS: Record<string, [string, string]> = {
  Frontend:  ['#eff6ff',             '#2563eb'],
  Execution: ['#ecfdf5',             '#059669'],
  Data:      ['#fffbeb',             '#d97706'],
  'ML + AI': ['rgba(124,58,237,0.08)', '#7c3aed'],
}

function ArchitectureTab({ services }: { services: ServiceResult[] }) {
  const byTier: Record<string, ServiceResult[]> = {}
  for (const t of TIER_ORDER) byTier[t] = []
  for (const s of services) {
    const tier = TIER_MAP[s.name] ?? 'Frontend'
    byTier[tier].push(s)
  }
  const statusColor = (st: string) =>
    st === 'UP' ? '#059669' : st === 'WARN' ? '#d97706' : '#dc2626'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {TIER_ORDER.map(tier => {
        const svcs = byTier[tier] ?? []
        const [bg, accent] = TIER_COLORS[tier]
        return (
          <div key={tier} style={{
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', padding: 16, boxShadow: 'var(--shadow-card)',
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: accent, marginBottom: 10 }}>
              {tier}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {svcs.length === 0 ? (
                <span style={{ fontSize: 11, color: '#9ca3af', fontStyle: 'italic' }}>No services in this tier</span>
              ) : svcs.map(s => (
                <div key={s.name} style={{ background: bg, border: `1px solid ${accent}33`, borderRadius: 'var(--radius)', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: statusColor(s.status), flexShrink: 0 }} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#111827' }}>{s.name}</span>
                  <span style={{ fontSize: 10, color: '#6b7280' }}>{s.type}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── Report iframe tab ──────────────────────────────────────── */
function ReportTab({ anchor }: { anchor: string }) {
  return (
    <iframe
      src={`${BASE}/#${anchor}`}
      style={{ width: '100%', height: 600, border: 'none', borderRadius: 'var(--radius)', background: 'var(--surface)' }}
      title={anchor}
    />
  )
}

/* ── No-report CTA ──────────────────────────────────────────── */
function GenerateCta({ onGenerate, generating }: { onGenerate: () => void; generating: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '60px 20px', gap: 14 }}>
      <div style={{ fontSize: 36, opacity: 0.3 }}>⊞</div>
      <div style={{ fontWeight: 700, fontSize: 15, color: '#111827' }}>No report generated yet</div>
      <div style={{ fontSize: 12, color: '#6b7280', textAlign: 'center', maxWidth: 340 }}>
        Run the ecosystem report to populate Projects, Languages, and Coverage tabs.
      </div>
      <button
        onClick={onGenerate}
        disabled={generating}
        style={{
          background: '#2563eb', color: '#fff', fontWeight: 600, fontSize: 13,
          border: 'none', borderRadius: 'var(--radius)', padding: '9px 20px', cursor: 'pointer',
          opacity: generating ? 0.65 : 1, display: 'flex', alignItems: 'center', gap: 7,
        }}
      >
        {generating ? (
          <>
            <span style={{ width: 12, height: 12, border: '2px solid rgba(255,255,255,0.4)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite', display: 'inline-block' }} />
            Generating…
          </>
        ) : '⊕ Generate Report'}
      </button>
    </div>
  )
}

/* ── EcosystemPage ──────────────────────────────────────────── */
export default function EcosystemPage({ refreshKey }: { refreshKey: number }) {
  const [subTab, setSubTab] = useState<SubTab>('architecture')
  const [services, setServices] = useState<ServiceResult[]>([])
  const [reportExists, setReportExists] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [lastGen, setLastGen] = useState<string | null>(null)
  const [progressMsg, setProgressMsg] = useState('')

  const pollStatus = async () => {
    try {
      const s = await fetchReportStatus()
      setReportExists(s.report_exists)
      if (s.report_generated_at) setLastGen(s.report_generated_at)
      if (s.status === 'running') {
        setGenerating(true)
        setProgressMsg('Generating… (2–5 min)')
        setTimeout(pollStatus, 2000)
      } else if (s.status === 'error') {
        setGenerating(false)
        setProgressMsg(`Error: ${s.message}`)
      } else {
        setGenerating(false)
        setProgressMsg('')
      }
    } catch { /* ignore */ }
  }

  useEffect(() => {
    fetchSummary().then(d => setServices(d.services)).catch(() => {})
    pollStatus()
  }, [refreshKey])

  const handleGenerate = async () => {
    try {
      await triggerGenerate()
      setGenerating(true)
      setProgressMsg('Generating… (2–5 min)')
      setTimeout(pollStatus, 2000)
    } catch { /* ignore */ }
  }

  const subTabs: { id: SubTab; label: string }[] = [
    { id: 'architecture', label: 'Architecture' },
    { id: 'projects',     label: 'Projects' },
    { id: 'languages',    label: 'Languages' },
    { id: 'coverage',     label: 'Coverage' },
  ]
  const needsReport = subTab !== 'architecture' && !reportExists

  return (
    <div>
      {/* Hero */}
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Ecosystem Report</h1>
            <p style={{ fontSize: 13, color: '#6b7280' }}>Architecture overview and project health metrics</p>
            {lastGen && (
              <p style={{ fontSize: 11, color: '#9ca3af', marginTop: 6 }}>
                Last generated: {new Date(lastGen).toLocaleString()}
              </p>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            {progressMsg && (
              <span style={{ fontSize: 11, color: generating ? '#6b7280' : '#dc2626' }}>{progressMsg}</span>
            )}
            {reportExists && (
              <a
                href={`${BASE}/`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 12, fontWeight: 600, color: '#2563eb', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: '6px 14px' }}
              >
                Full Report ↗
              </a>
            )}
            <button
              onClick={handleGenerate}
              disabled={generating}
              style={{
                fontSize: 12, fontWeight: 600, padding: '6px 14px',
                border: '1px solid #2563eb', borderRadius: 8,
                background: '#2563eb', color: 'white',
                cursor: generating ? 'not-allowed' : 'pointer',
                opacity: generating ? 0.65 : 1,
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              {generating && (
                <span style={{ width: 11, height: 11, border: '2px solid rgba(255,255,255,0.4)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite', flexShrink: 0 }} />
              )}
              {generating ? 'Running…' : '⊕ Generate'}
            </button>
          </div>
        </div>
      </div>

      {/* Sub-tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
        {subTabs.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            style={{
              padding: '10px 16px', fontSize: 13,
              fontWeight: subTab === t.id ? 600 : 400,
              color: subTab === t.id ? '#2563eb' : '#6b7280',
              background: 'none', border: 'none',
              borderBottom: subTab === t.id ? '2px solid #2563eb' : '2px solid transparent',
              cursor: 'pointer', marginBottom: -1, transition: 'color 0.1s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {subTab === 'architecture' && <ArchitectureTab services={services} />}
      {needsReport && <GenerateCta onGenerate={handleGenerate} generating={generating} />}
      {!needsReport && subTab === 'projects'  && <ReportTab anchor="section-projects" />}
      {!needsReport && subTab === 'languages' && <ReportTab anchor="section-languages" />}
      {!needsReport && subTab === 'coverage'  && <ReportTab anchor="section-coverage" />}
    </div>
  )
}
