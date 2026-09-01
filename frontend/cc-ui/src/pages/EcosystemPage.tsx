import { useState, useEffect, useRef, useCallback } from 'react'
import { fetchSummary, fetchReportData, fetchReportStatus, triggerGenerate } from '../api'
import type { SummaryResponse, ServiceResult, DiskResult, ReportData } from '../api'
import {
  C, KpiCard, Badge, SectionCard, DonutChart,
  ProjectsTab, LanguagesTab, CoverageTab, GitStatusTab,
} from './EcosystemReportTabs'

/**
 * Public Read-Only Control Center architecture: this file now imports
 * ProjectsTab/LanguagesTab/CoverageTab/GitStatusTab (and the shared UI
 * pieces they need -- KpiCard/Badge/SectionCard/DonutChart/C) from
 * ./EcosystemReportTabs instead of defining them inline -- same
 * components, same behavior, unchanged for AdminApp. That relocation is
 * what lets PublicEcosystemPage.tsx (the anonymous ControlApp's
 * Ecosystem Report page) import exactly those four tabs without ever
 * importing this file -- and therefore without ever bundling ArchTab or
 * the LANES architecture-diagram data below (real internal service
 * names, internal ports, tech-stack descriptions), or HealthTab (GET
 * /summary, platform.manage_infra-gated), or GenerateCta (POST
 * /report/generate, platform.manage_content-gated). See
 * docs/public-control-center.md for the full rationale.
 */

// ── Architecture lanes ─────────────────────────────────────────────────────────
interface ArchNode { key: string; name: string; desc: string; port: string | null; ui: string | null }
interface Lane { id: string; label: string; sublabel?: string; color: string; bg: string; border: string; nodes: ArchNode[] }

const LANES: Lane[] = [
  {
    id: 'clients', label: 'dev / clients', color: C.blue,
    bg: 'rgba(0,148,255,0.07)', border: 'rgba(0,148,255,0.3)',
    nodes: [
      { key: 'studio',       name: 'studio',       desc: 'Electron · v0.2.0',   port: null,    ui: null },
      { key: 'dev-hub',      name: 'dev-hub',       desc: 'knowledge graph',      port: '5173',  ui: null },
      { key: 'sdk',          name: 'sdk',           desc: 'Python SDK',           port: '5190',  ui: null },
      { key: 'iam-client',   name: 'iam-client',    desc: 'auth SDK',             port: null,    ui: null },
      { key: 'security-sdk', name: 'security-sdk',  desc: 'policy client',        port: null,    ui: null },
    ],
  },
  {
    id: 'security', label: '🔐 security plane', sublabel: 'zero-trust boundary', color: C.red,
    bg: 'rgba(239,68,68,0.07)', border: 'rgba(239,68,68,0.4)',
    nodes: [
      { key: 'api-gateway',       name: 'api-gateway',       desc: 'JWT · trace prop', port: '8080', ui: null },
      { key: 'auth-service',      name: 'auth-service',      desc: 'bcrypt · JWT',     port: '8001', ui: null },
      { key: 'policy-engine',     name: 'policy-engine',     desc: 'RBAC/ABAC',        port: '8002', ui: null },
      { key: 'hpc-policy-engine', name: 'hpc-policy-engine', desc: 'GPU quota',        port: '8003', ui: null },
      { key: 'security-audit',    name: 'security-audit',    desc: 'Redis streams',    port: '8004', ui: null },
    ],
  },
  {
    id: 'workbench', label: 'workbench', color: C.teal,
    bg: 'rgba(0,229,160,0.07)', border: 'rgba(0,229,160,0.3)',
    nodes: [
      { key: 'workbench',         name: 'workbench',         desc: 'Django · 80+ plugins', port: '8000', ui: 'https://webstudio.omnibioai.org' },
      { key: 'lims',              name: 'lims',              desc: 'lab data',             port: '7000', ui: 'https://lims.omnibioai.org' },
      { key: 'rag',               name: 'rag',               desc: 'PubMed · DeepSeek',    port: '8090', ui: null },
      { key: 'workflow-bundles',  name: 'workflow-bundles',  desc: 'WDL/Nextflow/CWL',     port: '8098', ui: null },
      { key: 'control-center',   name: 'control-center',    desc: 'health · images',      port: '7070', ui: 'https://control.omnibioai.org' },
    ],
  },
  {
    id: 'services', label: 'services', color: C.amber,
    bg: 'rgba(245,158,11,0.07)', border: 'rgba(245,158,11,0.3)',
    nodes: [
      { key: 'toolserver',      name: 'toolserver',      desc: 'FastAPI bio tools', port: '9090',  ui: 'https://tools.omnibioai.org' },
      { key: 'model-registry',  name: 'model-registry',  desc: 'ML versioning',    port: '8095',  ui: 'https://models.omnibioai.org' },
      { key: 'opa',             name: 'opa',             desc: 'Open Policy Agent', port: '8181',  ui: null },
      { key: 'ollama',          name: 'ollama',          desc: 'Llama/DeepSeek',   port: '11434', ui: null },
      { key: 'videos',          name: 'videos',          desc: 'tutorials · SDK',   port: '8086',  ui: null },
    ],
  },
  {
    id: 'execution', label: 'execution', color: C.purple,
    bg: 'rgba(168,85,247,0.07)', border: 'rgba(168,85,247,0.3)',
    nodes: [
      { key: 'tes',          name: 'tes',          desc: 'Slurm/AWS/Azure/GCP', port: '8081', ui: 'https://api.omnibioai.org/_svc/tes' },
      { key: 'tool-runtime', name: 'tool-runtime', desc: 'Docker/Singularity',  port: null,   ui: null },
      { key: 'tool-images',  name: 'tool-images',  desc: '80+ bio tools',       port: '8097', ui: null },
      { key: 'dev-docker',   name: 'dev-docker',   desc: 'DGX · GPU env',       port: null,   ui: null },
    ],
  },
]

// ── Shared helpers ─────────────────────────────────────────────────────────────
function statusColor(s: string) { return s === 'UP' ? C.green : s === 'WARN' ? C.amber : C.red }
function latColor(ms: number) { return ms < 5 ? C.green : ms < 20 ? C.amber : C.red }

function StatusDot({ status }: { status?: string }) {
  const color = !status ? C.muted : statusColor(status)
  const pulse = !status
  return (
    <span style={{
      width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0,
      animation: pulse ? 'pulse-dot 1.2s ease-in-out infinite' : 'none',
    }} />
  )
}

function GenerateCta({ onGenerate, generating }: { onGenerate: () => void; generating: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 20px', gap: 14 }}>
      <div style={{ fontSize: 40, opacity: 0.25 }}>⊞</div>
      <div style={{ fontWeight: 700, fontSize: 16, color: C.text }}>No report data yet</div>
      <div style={{ fontSize: 12, color: C.muted, textAlign: 'center', maxWidth: 360 }}>
        Generate the ecosystem report to populate Projects, Languages, and Coverage tabs.
      </div>
      <button
        onClick={onGenerate}
        disabled={generating}
        style={{
          background: C.teal, color: '#000', fontWeight: 700, fontSize: 13,
          border: 'none', borderRadius: 8, padding: '10px 22px', cursor: generating ? 'not-allowed' : 'pointer',
          opacity: generating ? 0.6 : 1, display: 'flex', alignItems: 'center', gap: 8,
        }}
      >
        {generating && <span style={{ width: 12, height: 12, border: '2px solid rgba(0,0,0,0.3)', borderTopColor: '#000', borderRadius: '50%', animation: 'spin 0.8s linear infinite', display: 'inline-block' }} />}
        {generating ? 'Generating…' : '⊕ Generate Report'}
      </button>
    </div>
  )
}

// ── Tab 1: Architecture ────────────────────────────────────────────────────────
interface SelectedNode { node: ArchNode; lane: Lane }

function ArchTab({ summary }: { summary: SummaryResponse | null }) {
  const [selected, setSelected] = useState<SelectedNode | null>(null)

  const hmap: Record<string, ServiceResult> = {}
  summary?.services.forEach(s => { hmap[s.name] = s })

  const overall = summary?.overall_status
  const overallColor = !overall ? C.muted : statusColor(overall)

  const handleSelect = (node: ArchNode, lane: Lane) => {
    setSelected(prev => prev?.node.key === node.key ? null : { node, lane })
  }

  return (
    <div>
      {/* Status bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.text }}>OmniBioAI ecosystem</div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Click any node to see live health and details</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', background: C.surface, border: `1px solid ${C.border}`, borderRadius: 99, fontSize: 12 }}>
            <StatusDot status={overall} />
            <span style={{ color: overallColor, fontWeight: 600 }}>
              {!overall ? 'fetching…' : overall === 'UP' ? 'all systems up' : overall.toLowerCase()}
            </span>
          </div>
        </div>
      </div>

      {/* Security separator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <div style={{ flex: 1, height: 1, background: C.red, opacity: 0.4 }} />
        <span style={{ fontSize: 10, color: C.red, fontWeight: 700, whiteSpace: 'nowrap' }}>enforced request path →</span>
        <div style={{ flex: 1, height: 1, background: C.red, opacity: 0.4 }} />
      </div>

      {/* 5-lane grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 12 }}>
        {LANES.map(lane => (
          <div key={lane.id} style={{ background: lane.bg, border: `1px solid ${lane.border}`, borderRadius: 12, padding: '10px 8px 12px' }}>
            <div style={{ fontSize: 11, fontWeight: 700, textAlign: 'center', color: lane.color, marginBottom: 4 }}>{lane.label}</div>
            {lane.sublabel && <div style={{ fontSize: 9, textAlign: 'center', color: lane.color, opacity: 0.75, marginBottom: 6 }}>{lane.sublabel}</div>}
            {lane.nodes.map(node => {
              const health = hmap[node.key]
              const isSelected = selected?.node.key === node.key
              return (
                <div
                  key={node.key}
                  onClick={() => handleSelect(node, lane)}
                  style={{
                    background: isSelected ? lane.border : `${C.surface}cc`,
                    border: `1px solid ${isSelected ? lane.color : C.border}`,
                    borderRadius: 8, padding: '7px 10px', marginBottom: 6, cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color: lane.color }}>{node.name}</span>
                    <StatusDot status={health?.status} />
                  </div>
                  <div style={{ fontSize: 9, color: C.muted, lineHeight: 1.3 }}>
                    {node.desc}{node.port ? ` · :${node.port}` : ''}
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {/* Detail panel */}
      {selected && (() => {
        const { node, lane } = selected
        const health = hmap[node.key]
        return (
          <div style={{ background: C.surface, border: `1px solid ${lane.color}44`, borderLeft: `4px solid ${lane.color}`, borderRadius: 12, overflow: 'hidden', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: `1px solid ${C.border}` }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{node.name}</div>
                <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{lane.label}</div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {node.ui && (
                  <a href={node.ui} target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 11, padding: '3px 10px', border: `1px solid ${lane.border}`, borderRadius: 6, background: lane.bg, color: lane.color, textDecoration: 'none' }}>
                    open UI ↗
                  </a>
                )}
                <button onClick={() => setSelected(null)}
                  style={{ padding: '4px 10px', border: `1px solid ${C.border}`, borderRadius: 6, background: 'transparent', fontSize: 11, color: C.muted, cursor: 'pointer' }}>
                  close
                </button>
              </div>
            </div>
            <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <div style={{ fontSize: 11, color: C.muted, marginBottom: 3 }}>health status</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: health ? statusColor(health.status) : C.muted }}>
                  {health ? health.status : 'not monitored'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: C.muted, marginBottom: 3 }}>latency</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {health?.latency_ms != null ? (
                    <span style={{ color: latColor(health.latency_ms) }}>{health.latency_ms} ms</span>
                  ) : '—'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: C.muted, marginBottom: 3 }}>port</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{node.port ? `:${node.port}` : '—'}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: C.muted, marginBottom: 3 }}>message</div>
                <div style={{ fontSize: 12, color: C.muted }}>{health?.message || '—'}</div>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <div style={{ fontSize: 11, color: C.muted, marginBottom: 3 }}>description</div>
                <div style={{ fontSize: 12, color: C.muted }}>{node.desc}</div>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', paddingTop: 8, borderTop: `1px solid ${C.border}` }}>
        {[['healthy', C.green], ['down', C.red], ['not monitored', C.muted]].map(([label, color]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: C.muted }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color as string, display: 'inline-block' }} />
            {label}
          </div>
        ))}
        <div style={{ marginLeft: 'auto', fontSize: 11, color: C.muted }}>live from <code style={{ fontSize: 10, color: C.teal }}>/summary</code> · auto-refreshes every 30s</div>
      </div>
    </div>
  )
}

// ── Tab 5: Health Status ───────────────────────────────────────────────────────
const SVC_ICONS: Record<string, string> = { mysql: '🗄️', redis: '⚡', http: '🌐', tcp: '🔌' }

function HealthTab({ refreshKey }: { refreshKey: number }) {
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [error, setError] = useState(false)
  const [countdown, setCountdown] = useState(30)
  const cdRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const doFetch = useCallback(async () => {
    try {
      const d = await fetchSummary()
      setSummary(d)
      setError(false)
    } catch {
      setError(true)
    }
    setCountdown(30)
    if (cdRef.current) clearInterval(cdRef.current)
    cdRef.current = setInterval(() => setCountdown(c => {
      if (c <= 1) { doFetch(); return 30 }
      return c - 1
    }), 1000)
  }, [])

  useEffect(() => {
    doFetch()
    return () => { if (cdRef.current) clearInterval(cdRef.current) }
  }, [refreshKey, doFetch])

  if (!summary && !error) {
    return <div style={{ padding: 40, textAlign: 'center', color: C.muted }}>Fetching health data…</div>
  }

  const svcs = summary?.services ?? []
  const disk = summary?.system?.disk ?? []
  const overall = summary?.overall_status ?? 'DOWN'
  const up = svcs.filter(s => s.status === 'UP').length
  const dn = svcs.filter(s => s.status === 'DOWN').length
  const wn = svcs.filter(s => s.status === 'WARN').length
  const diskWarn = disk.filter((d: DiskResult) => d.status !== 'UP').length

  const bannerBg = error ? `${C.red}22` : overall === 'UP' ? `${C.green}22` : overall === 'DOWN' ? `${C.red}22` : `${C.amber}22`
  const bannerBorder = error ? C.red : overall === 'UP' ? C.green : overall === 'DOWN' ? C.red : C.amber
  const bannerTitle = error ? 'Control center unreachable' : overall === 'UP' ? 'All systems operational' : overall === 'DOWN' ? 'One or more services are down' : 'One or more services degraded'

  const withLatency = svcs.filter(s => s.latency_ms != null)
  const maxLat = withLatency.length ? Math.max(...withLatency.map(s => s.latency_ms!)) : 1

  return (
    <div>
      {/* Banner */}
      <div style={{ background: bannerBg, border: `1px solid ${bannerBorder}44`, borderRadius: 12, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <StatusDot status={error ? 'DOWN' : overall} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{bannerTitle}</div>
          {summary && (
            <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
              Checked: {new Date(summary.generated_at).toLocaleTimeString()} · Source: /summary
            </div>
          )}
        </div>
        <span style={{ fontSize: 11, color: C.muted }}>next refresh in {countdown}s</span>
        <button onClick={doFetch} style={{ padding: '5px 12px', border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface, fontSize: 12, color: C.muted, cursor: 'pointer' }}>
          ↻ refresh
        </button>
      </div>

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 16 }}>
        <KpiCard label="monitored" value={svcs.length} sub="services" />
        <KpiCard label="healthy" value={up} sub="UP" color={C.green} />
        <KpiCard label="down" value={dn} sub="need attention" color={dn > 0 ? C.red : C.text} />
        <KpiCard label="degraded" value={wn} sub="WARN" color={wn > 0 ? C.amber : C.text} />
        <KpiCard label="disk warnings" value={diskWarn} sub="paths checked" color={diskWarn > 0 ? C.amber : C.text} />
      </div>

      {/* Charts row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <SectionCard title="status distribution" sub="across all monitored services">
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <DonutChart
              data={[
                { name: 'healthy', value: up, color: C.green },
                { name: 'down', value: dn, color: C.red },
                { name: 'degraded', value: wn, color: C.amber },
              ].filter(d => d.value > 0)}
              cx={70} cy={70} r={62} label={String(up)} sublabel={`of ${svcs.length} UP`}
            />
            <div>
              {[['healthy', C.green, up], ['down', C.red, dn], ['degraded', C.amber, wn]].map(([lbl, color, cnt]) => (
                <div key={lbl as string} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0', fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: color as string, flexShrink: 0 }} />
                  <span style={{ color: C.muted, flex: 1 }}>{lbl as string}</span>
                  <span style={{ fontWeight: 600, color: C.text, marginLeft: 12 }}>{cnt as number}</span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>

        <SectionCard title="response latency" sub="per service · proportional bars">
          {withLatency.length === 0 ? (
            <div style={{ fontSize: 12, color: C.muted }}>no latency data</div>
          ) : withLatency.map(s => {
            const pct = Math.round((s.latency_ms! / maxLat) * 100)
            const color = latColor(s.latency_ms!)
            return (
              <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: C.muted, width: 100, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                <div style={{ flex: 1, height: 14, background: C.border, borderRadius: 3, position: 'relative', overflow: 'hidden' }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: `${color}33`, borderRadius: 3 }} />
                  <span style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', fontSize: 9, fontWeight: 600, color }}>{s.latency_ms} ms</span>
                </div>
              </div>
            )
          })}
        </SectionCard>
      </div>

      {/* Service cards grid */}
      <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>services</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 8, marginBottom: 12 }}>
        {svcs.map(s => {
          const sc = s.status === 'UP' ? 'up' : s.status === 'DOWN' ? 'down' : 'warn'
          const bgMap = { up: `${C.green}11`, down: `${C.red}11`, warn: `${C.amber}11` }
          const bdMap = { up: `${C.green}44`, down: `${C.red}44`, warn: `${C.amber}44` }
          const bdLeft = { up: C.green, down: C.red, warn: C.amber }
          const icon = SVC_ICONS[s.type] ?? '⚙️'
          return (
            <div key={s.name} style={{
              background: bgMap[sc], border: `1px solid ${bdMap[sc]}`,
              borderLeft: `4px solid ${bdLeft[sc]}`, borderRadius: 12, padding: 14,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ fontSize: 18 }}>{icon}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{s.name}</span>
                </div>
                <Badge label={s.status} color={statusColor(s.status)} bg={`${statusColor(s.status)}22`} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr', gap: '3px 8px', fontSize: 11 }}>
                <span style={{ color: C.muted }}>target</span>
                <span style={{ color: C.muted, fontFamily: 'monospace', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.target}</span>
                <span style={{ color: C.muted }}>latency</span>
                <span>
                  {s.latency_ms != null
                    ? <span style={{ color: latColor(s.latency_ms), fontWeight: 600 }}>{s.latency_ms} ms</span>
                    : <span style={{ color: C.muted }}>—</span>}
                </span>
                <span style={{ color: C.muted }}>message</span>
                <span style={{ color: C.muted }}>{s.message || '—'}</span>
              </div>
              {s.ui_url && (
                <a href={s.ui_url} target="_blank" rel="noopener noreferrer"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 3, marginTop: 8, fontSize: 11, color: C.blue, textDecoration: 'none' }}>
                  open UI ↗
                </a>
              )}
            </div>
          )
        })}
      </div>

      {/* Disk checks */}
      <SectionCard title="disk checks" sub="storage paths monitored by control center">
        {disk.length === 0 ? (
          <div style={{ fontSize: 12, color: C.muted }}>no disk checks configured</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
            {disk.map((d: DiskResult) => {
              const m = (d.message ?? '').match(/([0-9.]+)%/)
              const pct = m ? parseFloat(m[1]) : 0
              const color = d.status === 'UP' ? C.green : d.status === 'WARN' ? C.amber : C.red
              return (
                <div key={d.name} style={{ background: `${C.surface}80`, borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{d.name.replace('disk:', '')}</span>
                    <span style={{ fontSize: 11, fontWeight: 600, color }}>{d.message}</span>
                  </div>
                  <div style={{ fontSize: 10, color: C.muted, marginBottom: 6 }}>{d.target}</div>
                  <div style={{ height: 5, background: C.border, borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: color, borderRadius: 3 }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </SectionCard>
    </div>
  )
}

// ── Main EcosystemPage ─────────────────────────────────────────────────────────
type SubTab = 'architecture' | 'projects' | 'languages' | 'coverage' | 'gitStatus' | 'health'

const SUBTABS: { id: SubTab; label: string }[] = [
  { id: 'architecture', label: 'Architecture' },
  { id: 'projects',     label: 'Projects' },
  { id: 'languages',    label: 'Languages' },
  { id: 'coverage',     label: 'Code Coverage' },
  { id: 'gitStatus',    label: 'Ecosystem Status' },
  { id: 'health',       label: 'Health Status' },
]

export default function EcosystemPage({ refreshKey }: { refreshKey: number }) {
  const [subTab, setSubTab] = useState<SubTab>('architecture')
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [reportData, setReportData] = useState<ReportData | null>(null)
  const [, setDataError] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [progressMsg, setProgressMsg] = useState('')
  const [lastGen, setLastGen] = useState<string | null>(null)

  const pollStatus = useCallback(async () => {
    try {
      const s = await fetchReportStatus()
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
        if (s.status === 'done' || s.report_exists) {
          loadData()
        }
      }
    } catch { /* ignore */ }
  }, [])

  const loadData = useCallback(async () => {
    try {
      const d = await fetchReportData()
      setReportData(d)
      setDataError(false)
    } catch {
      setDataError(true)
    }
  }, [])

  useEffect(() => {
    fetchSummary().then(setSummary).catch(() => {})
    loadData()
    pollStatus()
    const t = setInterval(() => fetchSummary().then(setSummary).catch(() => {}), 30_000)
    return () => clearInterval(t)
  }, [refreshKey])

  const handleGenerate = async () => {
    try {
      await triggerGenerate()
      setGenerating(true)
      setProgressMsg('Generating… (2–5 min)')
      setTimeout(pollStatus, 2000)
    } catch { /* ignore */ }
  }

  const needsReport = (subTab === 'projects' || subTab === 'languages' || subTab === 'coverage' || subTab === 'gitStatus') && !reportData

  return (
    // No negative margin here (this page used to carry `margin: '-24px
    // -28px -48px'`) -- it was presumably meant to cancel some parent
    // padding, but nothing in the actual AppShell/renderPage chain has
    // any: every other page's content starts flush at the sidebar's
    // right edge (x = sidebar width, confirmed by measuring the live
    // DOM) with zero extra gutter, relying only on its own interior
    // padding for spacing, same as this div's own `padding: 20` below.
    // The negative margin shifted this div 28px further left than that
    // baseline, and its own 20px padding only clawed back 20 of those
    // 28 -- a net 8px past the sidebar boundary, clipping the leading
    // edge of "Ecosystem Report"/"Architecture overview..." on every
    // sub-tab of this page (they all share this one wrapper).
    <div style={{ background: C.bg, borderRadius: 14, padding: 20, minHeight: 'calc(100vh - 100px)', color: C.text }}>
      {/* Hero */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 20, paddingBottom: 16, borderBottom: `1px solid ${C.border}` }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, marginBottom: 4 }}>Ecosystem Report</h1>
          <p style={{ fontSize: 13, color: C.muted }}>Architecture overview and project health metrics</p>
          {lastGen && <p style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>Last generated: {new Date(lastGen).toLocaleString()}</p>}
        </div>
        {/* The Generate Report button that used to live here was removed --
            AppShell's TopAppBar extraActions slot (AdminApp.tsx's
            StatusAndReportActions) already renders one globally, on every
            page, via its own independent generating/handleGenerate state.
            Having both meant two unsynchronized controls for the same
            triggerGenerate() action visible at once on this page. This
            page's own generating/handleGenerate/progressMsg state is kept
            -- GenerateCta's empty-state button below still needs it. */}
        {progressMsg && (
          <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: generating ? C.muted : C.red }}>{progressMsg}</span>
          </div>
        )}
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
      {subTab === 'architecture' && <ArchTab summary={summary} />}
      {subTab === 'health'       && <HealthTab refreshKey={refreshKey} />}
      {needsReport && <GenerateCta onGenerate={handleGenerate} generating={generating} />}
      {!needsReport && subTab === 'projects'  && reportData && <ProjectsTab data={reportData} />}
      {!needsReport && subTab === 'languages' && reportData && <LanguagesTab data={reportData} />}
      {!needsReport && subTab === 'coverage'  && reportData && <CoverageTab data={reportData} />}
      {!needsReport && subTab === 'gitStatus' && reportData && <GitStatusTab data={reportData} />}
    </div>
  )
}
