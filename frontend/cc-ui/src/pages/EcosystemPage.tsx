import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import {
  PieChart, Pie, Cell, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer,
} from 'recharts'
import { fetchSummary, fetchReportData, fetchReportStatus, triggerGenerate } from '../api'
import type { SummaryResponse, ServiceResult, DiskResult, ReportData } from '../api'

// ── Dark theme tokens ──────────────────────────────────────────────────────────
const C = {
  bg:      '#0f1117',
  surface: '#1a1d2e',
  border:  '#2a2d3e',
  text:    '#ffffff',
  muted:   '#6b7280',
  teal:    '#00e5a0',
  blue:    '#0094ff',
  red:     '#ef4444',
  amber:   '#f59e0b',
  green:   '#22c55e',
  purple:  '#a855f7',
}

// ── Category colors (dark theme) ──────────────────────────────────────────────
const CAT: Record<string, { color: string; bg: string; label: string }> = {
  core:  { color: C.teal,   bg: 'rgba(0,229,160,0.15)',   label: 'core workbench' },
  sec:   { color: C.red,    bg: 'rgba(239,68,68,0.15)',    label: 'security' },
  exec:  { color: C.purple, bg: 'rgba(168,85,247,0.15)',   label: 'execution' },
  infra: { color: C.amber,  bg: 'rgba(245,158,11,0.15)',   label: 'infrastructure' },
  sdk:   { color: C.blue,   bg: 'rgba(0,148,255,0.15)',    label: 'sdk / clients' },
}

// ── Language type colors (dark theme) ─────────────────────────────────────────
const LANG: Record<string, { color: string; bg: string; icon: string; label: string }> = {
  backend:  { color: C.teal,   bg: 'rgba(0,229,160,0.15)',    icon: '🐍', label: 'backend' },
  frontend: { color: C.blue,   bg: 'rgba(0,148,255,0.15)',    icon: '🌐', label: 'frontend' },
  docs:     { color: C.muted,  bg: 'rgba(107,114,128,0.15)',  icon: '📄', label: 'docs' },
  config:   { color: C.amber,  bg: 'rgba(245,158,11,0.15)',   icon: '⚙️', label: 'config' },
  infra:    { color: C.purple, bg: 'rgba(168,85,247,0.15)',   icon: '🔧', label: 'infra' },
}

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
function fmt(n: number) { return n.toLocaleString() }
function k(n: number) { return n >= 1000 ? (n / 1000).toFixed(0) + 'k' : String(n) }
function statusColor(s: string) { return s === 'UP' ? C.green : s === 'WARN' ? C.amber : C.red }
function latColor(ms: number) { return ms < 5 ? C.green : ms < 20 ? C.amber : C.red }

// ── Shared UI pieces ───────────────────────────────────────────────────────────
function KpiCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color ?? C.text, lineHeight: 1, marginBottom: 3 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.muted }}>{sub}</div>}
    </div>
  )
}

function Badge({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 99, background: bg, color, whiteSpace: 'nowrap' }}>
      {label}
    </span>
  )
}

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

function SectionCard({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 18, marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 2 }}>{title}</div>
      {sub && <div style={{ fontSize: 11, color: C.muted, marginBottom: 14 }}>{sub}</div>}
      {children}
    </div>
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

// ── Donut chart with center label ─────────────────────────────────────────────
interface DonutSlice { name: string; value: number; color: string }
function DonutChart({ data, cx, cy, r, label, sublabel }: { data: DonutSlice[]; cx: number; cy: number; r: number; label: string; sublabel: string }) {
  return (
    <PieChart width={cx * 2} height={cy * 2}>
      <Pie data={data} cx={cx - 1} cy={cy - 1} innerRadius={r * 0.68} outerRadius={r} dataKey="value" paddingAngle={2} strokeWidth={0}>
        {data.map((d, i) => <Cell key={i} fill={d.color} />)}
      </Pie>
      <Tooltip
        contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 12 }}
        labelStyle={{ color: C.text }}
        itemStyle={{ color: C.muted }}
        formatter={(v) => [fmt(Number(v)), '']}
      />
      <text x={cx} y={cy - 5} textAnchor="middle" fill={C.text} fontSize={18} fontWeight={700}>{label}</text>
      <text x={cx} y={cy + 14} textAnchor="middle" fill={C.muted} fontSize={10}>{sublabel}</text>
    </PieChart>
  )
}

// ── Sortable/filterable/paginated table hook ──────────────────────────────────
function useTable<T extends Record<string, unknown>>(_rows: T[], defaultSort: string) {
  const [sortKey, setSortKey] = useState(defaultSort)
  const [sortDir, setSortDir] = useState<1 | -1>(-1)
  const [search, setSearch] = useState('')
  const [filterVal, setFilterVal] = useState('')
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(10)

  const toggleSort = useCallback((key: string) => {
    if (key === sortKey) setSortDir(d => (d === 1 ? -1 : 1))
    else { setSortKey(key); setSortDir(key === 'name' || key === 'repo' ? 1 : -1) }
    setPage(1)
  }, [sortKey])

  return { sortKey, sortDir, search, setSearch, filterVal, setFilterVal, page, setPage, perPage, setPerPage, toggleSort }
}

function applyTable<T extends Record<string, unknown>>(
  rows: T[],
  state: ReturnType<typeof useTable>,
  searchFields: (keyof T)[],
  filterField?: keyof T,
) {
  let d = rows.slice()
  if (state.search) {
    const q = state.search.toLowerCase()
    d = d.filter(r => searchFields.some(f => String(r[f] ?? '').toLowerCase().includes(q)))
  }
  if (state.filterVal && filterField) {
    d = d.filter(r => r[filterField] === state.filterVal)
  }
  const { sortKey, sortDir } = state
  d.sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    if (av == null && bv == null) return 0
    if (av == null) return sortDir
    if (bv == null) return -sortDir
    return av < bv ? sortDir : av > bv ? -sortDir : 0
  })
  return d
}

function Pagination({ page, pages, total, perPage, onPage, onPerPage }: {
  page: number; pages: number; total: number; perPage: number; onPage: (p: number) => void; onPerPage: (n: number) => void
}) {
  if (pages <= 1 && total <= 10) return null
  const start = (page - 1) * perPage + 1
  const end = Math.min(page * perPage, total)
  const btns: number[] = []
  const s = Math.max(1, page - 2), e = Math.min(pages, s + 4)
  for (let i = s; i <= e; i++) btns.push(i)

  const btn = (label: string | number, onClick: () => void, active = false, disabled = false) => (
    <button
      key={label}
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '4px 9px', fontSize: 11, border: `1px solid ${C.border}`, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
        background: active ? C.teal : C.surface, color: active ? '#000' : C.muted, opacity: disabled ? 0.4 : 1, minWidth: 28,
      }}
    >{label}</button>
  )

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 0', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 11, color: C.muted }}>{start}–{end} of {total}</span>
      {btn('←', () => onPage(page - 1), false, page === 1)}
      {btns.map(p => btn(p, () => onPage(p), p === page))}
      {btn('→', () => onPage(page + 1), false, page === pages)}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: C.muted }}>
        per page
        <select
          value={perPage}
          onChange={e => { onPerPage(Number(e.target.value)); onPage(1) }}
          style={{ padding: '3px 6px', fontSize: 11, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, color: C.text }}
        >
          {[10, 20, 50].map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
    </div>
  )
}

const thStyle = (active: boolean, right = false): React.CSSProperties => ({
  padding: '8px 12px', fontSize: 10, fontWeight: 700, color: active ? C.teal : C.muted,
  textTransform: 'uppercase', letterSpacing: '0.07em', background: C.surface,
  borderBottom: `1px solid ${C.border}`, cursor: 'pointer', userSelect: 'none',
  textAlign: right ? 'right' : 'left', whiteSpace: 'nowrap',
})

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

// ── Tab 2: Projects ────────────────────────────────────────────────────────────
function ProjectsTab({ data }: { data: ReportData }) {
  const { projects, grand } = data
  const tbl = useTable(projects as unknown as Record<string, unknown>[], 'code')

  const filtered = useMemo(() =>
    applyTable(projects as unknown as Record<string, unknown>[], tbl, ['name', 'catLabel'], 'cat'),
    [projects, tbl.search, tbl.filterVal, tbl.sortKey, tbl.sortDir]
  )
  const pages = Math.ceil(filtered.length / tbl.perPage)
  const paged = filtered.slice((tbl.page - 1) * tbl.perPage, tbl.page * tbl.perPage)

  const totalCode = grand.code || 1
  const catTotals: Record<string, number> = {}
  projects.forEach(r => { catTotals[r.cat] = (catTotals[r.cat] || 0) + r.code })
  const catOrder = Object.keys(CAT).sort((a, b) => (catTotals[b] || 0) - (catTotals[a] || 0))
  const donutData = catOrder.map(k => ({ name: CAT[k].label, value: catTotals[k] || 0, color: CAT[k].color }))
  const maxCode = projects[0]?.code || 1

  const SortTh = ({ col, label, right = false }: { col: string; label: string; right?: boolean }) => (
    <th onClick={() => { tbl.toggleSort(col); }} style={thStyle(tbl.sortKey === col, right)}>
      {label}{tbl.sortKey === col ? (tbl.sortDir === 1 ? ' ↑' : ' ↓') : ''}
    </th>
  )

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <KpiCard label="repositories" value={projects.length} sub="tracked by cloc" />
        <KpiCard label="code lines" value={fmt(grand.code)} sub="excl. vendored" />
        <KpiCard label="largest repo" value={projects[0]?.name ?? '—'} sub={projects[0] ? `${fmt(projects[0].code)} LOC` : ''} color={C.teal} />
        <KpiCard label="categories" value={5} sub="core · sec · exec · infra · sdk" />
      </div>

      <SectionCard title="share by project" sub="code lines · categorized by function">
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 20, alignItems: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <DonutChart data={donutData} cx={80} cy={80} r={72} label={k(grand.code)} sublabel="total LOC" />
            <div style={{ marginTop: 4, width: '100%' }}>
              {catOrder.map(cat => (
                <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0', fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: CAT[cat].color, flexShrink: 0 }} />
                  <span style={{ color: C.muted, flex: 1 }}>{CAT[cat].label}</span>
                  <span style={{ fontWeight: 600, color: C.text }}>{((catTotals[cat] || 0) / totalCode * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            {projects.slice(0, 16).map(r => {
              const pct = Math.round(r.code / maxCode * 100)
              const meta = CAT[r.cat] || CAT.infra
              return (
                <div key={r.name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                  <span style={{ fontSize: 11, color: C.muted, width: 110, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.full}>{r.name}</span>
                  <div style={{ flex: 1, height: 14, background: `${C.border}`, borderRadius: 3, overflow: 'hidden', position: 'relative' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: `${meta.color}33`, borderRadius: 3 }} />
                    <span style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', fontSize: 9, fontWeight: 600, color: meta.color }}>{k(r.code)}</span>
                  </div>
                  <Badge label={meta.label.split(' ')[0]} color={meta.color} bg={meta.bg} />
                </div>
              )
            })}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="per-project breakdown" sub="all repositories · click headers to sort">
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input
            value={tbl.search} onChange={e => { tbl.setSearch(e.target.value); tbl.setPage(1) }}
            placeholder="search…" style={{ flex: 1, minWidth: 140, padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}
          />
          <select value={tbl.filterVal} onChange={e => { tbl.setFilterVal(e.target.value); tbl.setPage(1) }}
            style={{ padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}>
            <option value="">all categories</option>
            {Object.entries(CAT).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <span style={{ fontSize: 11, color: C.muted, alignSelf: 'center' }}>{filtered.length} items</span>
        </div>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortTh col="name" label="repository" />
                <th style={thStyle(false)}>category</th>
                <SortTh col="files" label="files" right />
                <SortTh col="code" label="code" right />
                <SortTh col="comment" label="comment" right />
                <SortTh col="blank" label="blank" right />
                <SortTh col="pct" label="share" right />
              </tr>
            </thead>
            <tbody>
              {paged.map((r: any) => {
                const meta = CAT[r.cat] || CAT.infra
                return (
                  <tr key={r.name} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '8px 12px', fontWeight: 600, fontSize: 12, color: C.text }}>{r.name}</td>
                    <td style={{ padding: '8px 12px' }}><Badge label={meta.label} color={meta.color} bg={meta.bg} /></td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{fmt(r.files)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, fontWeight: 600, color: C.text }}>{fmt(r.code)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{fmt(r.comment)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{fmt(r.blank)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>
                      {r.pct.toFixed(1)}%
                      <span style={{ display: 'inline-block', width: 40, height: 4, background: C.border, borderRadius: 2, verticalAlign: 'middle', marginLeft: 6, overflow: 'hidden' }}>
                        <span style={{ display: 'block', width: `${Math.min(100, r.pct * 2)}%`, height: '100%', background: meta.color, borderRadius: 2 }} />
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Pagination page={tbl.page} pages={pages} total={filtered.length} perPage={tbl.perPage} onPage={tbl.setPage} onPerPage={n => { tbl.setPerPage(n); tbl.setPage(1) }} />
      </SectionCard>
    </div>
  )
}

// ── Tab 3: Languages ───────────────────────────────────────────────────────────
function LanguagesTab({ data }: { data: ReportData }) {
  const { languages, grand } = data
  const tbl = useTable(languages as unknown as Record<string, unknown>[], 'code')

  const filtered = useMemo(() =>
    applyTable(languages as unknown as Record<string, unknown>[], tbl, ['name', 'typeLabel'], 'type'),
    [languages, tbl.search, tbl.filterVal, tbl.sortKey, tbl.sortDir]
  )
  const pages = Math.ceil(filtered.length / tbl.perPage)
  const paged = filtered.slice((tbl.page - 1) * tbl.perPage, tbl.page * tbl.perPage)

  const totalCode = grand.code || 1
  const typeTotals: Record<string, number> = {}
  languages.forEach(r => { typeTotals[r.type] = (typeTotals[r.type] || 0) + r.code })
  const typeOrder = Object.keys(LANG).sort((a, b) => (typeTotals[b] || 0) - (typeTotals[a] || 0))
  const donutData = typeOrder.map(k => ({ name: LANG[k].label, value: typeTotals[k] || 0, color: LANG[k].color }))
  const maxCode = languages[0]?.code || 1

  const SortTh = ({ col, label, right = false }: { col: string; label: string; right?: boolean }) => (
    <th onClick={() => tbl.toggleSort(col)} style={thStyle(tbl.sortKey === col, right)}>
      {label}{tbl.sortKey === col ? (tbl.sortDir === 1 ? ' ↑' : ' ↓') : ''}
    </th>
  )

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <KpiCard label="languages" value={languages.length} sub="detected by cloc" />
        <KpiCard label="dominant" value={languages[0]?.name ?? '—'} sub={languages[0] ? `${(languages[0].pct).toFixed(1)}% of codebase` : ''} color={C.teal} />
        <KpiCard label="backend" value={`${((typeTotals.backend || 0) / totalCode * 100).toFixed(1)}%`} sub="Python + SQL + notebooks" color={C.teal} />
        <KpiCard label="frontend" value={`${((typeTotals.frontend || 0) / totalCode * 100).toFixed(1)}%`} sub="HTML + CSS + TS + JS" color={C.blue} />
      </div>

      <SectionCard title="language type distribution" sub="grouped by role in the stack">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 }}>
          {typeOrder.map(t => {
            const m = LANG[t]
            const pct = ((typeTotals[t] || 0) / totalCode * 100).toFixed(1)
            return (
              <div key={t} style={{ background: `${C.surface}80`, border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 32, height: 32, borderRadius: 8, background: m.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, flexShrink: 0 }}>{m.icon}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{m.label}</div>
                  <div style={{ fontSize: 11, color: C.muted }}>{fmt(typeTotals[t] || 0)} LOC</div>
                </div>
                <div style={{ fontSize: 14, fontWeight: 700, color: m.color }}>{pct}%</div>
              </div>
            )
          })}
        </div>
      </SectionCard>

      <SectionCard title="lines of code by language" sub="top languages · color = type">
        <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 20, alignItems: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <DonutChart data={donutData} cx={80} cy={80} r={72} label={String(languages.length)} sublabel="languages" />
            <div style={{ marginTop: 4, width: '100%' }}>
              {typeOrder.map(t => (
                <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0', fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: LANG[t].color, flexShrink: 0 }} />
                  <span style={{ color: C.muted, flex: 1 }}>{LANG[t].label}</span>
                  <span style={{ fontWeight: 600, color: C.text }}>{((typeTotals[t] || 0) / totalCode * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            {languages.slice(0, 18).map(r => {
              const m = LANG[r.type] || LANG.infra
              const pct = Math.round(r.code / maxCode * 100)
              return (
                <div key={r.name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                  <span style={{ fontSize: 11, color: C.muted, width: 110, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                  <div style={{ flex: 1, height: 14, background: C.border, borderRadius: 3, position: 'relative', overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: `${m.color}33`, borderRadius: 3 }} />
                    <span style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', fontSize: 9, fontWeight: 600, color: m.color }}>{k(r.code)}</span>
                  </div>
                  <Badge label={m.label} color={m.color} bg={m.bg} />
                </div>
              )
            })}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="all languages" sub="complete breakdown · click headers to sort">
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input
            value={tbl.search} onChange={e => { tbl.setSearch(e.target.value); tbl.setPage(1) }}
            placeholder="search language…" style={{ flex: 1, minWidth: 140, padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}
          />
          <select value={tbl.filterVal} onChange={e => { tbl.setFilterVal(e.target.value); tbl.setPage(1) }}
            style={{ padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}>
            <option value="">all types</option>
            {Object.entries(LANG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <span style={{ fontSize: 11, color: C.muted, alignSelf: 'center' }}>{filtered.length} items</span>
        </div>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortTh col="name" label="language" />
                <th style={thStyle(false)}>type</th>
                <SortTh col="files" label="files" right />
                <SortTh col="code" label="code" right />
                <SortTh col="comment" label="comment" right />
                <SortTh col="blank" label="blank" right />
                <SortTh col="pct" label="share" right />
              </tr>
            </thead>
            <tbody>
              {paged.map((r: any) => {
                const m = LANG[r.type] || LANG.infra
                return (
                  <tr key={r.name} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '8px 12px', fontWeight: 600, fontSize: 12, color: C.text }}>{r.name}</td>
                    <td style={{ padding: '8px 12px' }}><Badge label={m.label} color={m.color} bg={m.bg} /></td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{fmt(r.files)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, fontWeight: 600, color: C.text }}>{fmt(r.code)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{fmt(r.comment)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{fmt(r.blank)}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>
                      {r.pct.toFixed(1)}%
                      <span style={{ display: 'inline-block', width: 40, height: 4, background: C.border, borderRadius: 2, verticalAlign: 'middle', marginLeft: 6, overflow: 'hidden' }}>
                        <span style={{ display: 'block', width: `${Math.min(100, r.pct * 3)}%`, height: '100%', background: m.color, borderRadius: 2 }} />
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Pagination page={tbl.page} pages={pages} total={filtered.length} perPage={tbl.perPage} onPage={tbl.setPage} onPerPage={n => { tbl.setPerPage(n); tbl.setPage(1) }} />
      </SectionCard>
    </div>
  )
}

// ── Tab 4: Code Coverage ───────────────────────────────────────────────────────
function covBand(pct: number | null) {
  if (pct == null) return 'none'
  if (pct >= 95) return 'excellent'
  if (pct >= 85) return 'good'
  return 'low'
}
function covColor(pct: number | null) {
  if (pct == null) return C.muted
  return pct >= 95 ? C.green : pct >= 85 ? C.amber : C.red
}

function CoverageTab({ data }: { data: ReportData }) {
  const { coverage } = data
  const tbl = useTable(coverage as unknown as Record<string, unknown>[], 'pct')

  const filtered = useMemo(() => {
    let d = (coverage as unknown as Record<string, unknown>[]).slice()
    if (tbl.search) {
      const q = tbl.search.toLowerCase()
      d = d.filter(r => String(r.repo ?? '').toLowerCase().includes(q))
    }
    if (tbl.filterVal) {
      d = d.filter(r => covBand(r.pct as number | null) === tbl.filterVal)
    }
    const { sortKey, sortDir } = tbl
    d.sort((a, b) => {
      const av = a[sortKey] as number | null, bv = b[sortKey] as number | null
      if (av == null && bv == null) return 0
      if (av == null) return sortDir
      if (bv == null) return -sortDir
      return av < bv ? sortDir : av > bv ? -sortDir : 0
    })
    return d
  }, [coverage, tbl.search, tbl.filterVal, tbl.sortKey, tbl.sortDir])

  const pages = Math.ceil(filtered.length / tbl.perPage)
  const paged = filtered.slice((tbl.page - 1) * tbl.perPage, tbl.page * tbl.perPage)

  const withData = coverage.filter(r => r.pct != null)
  const avg = withData.length ? withData.reduce((s, r) => s + r.pct!, 0) / withData.length : 0
  const excellent = withData.filter(r => r.pct! >= 95).length
  const good = withData.filter(r => r.pct! >= 85 && r.pct! < 95).length
  const low = withData.filter(r => r.pct! < 85).length
  const nodata = coverage.length - withData.length

  const barData = withData.slice().sort((a, b) => b.pct! - a.pct!).map(r => ({
    name: r.repo.replace('omnibioai-', '').replace('omnibioai_', ''),
    value: r.pct!,
    fill: covColor(r.pct!),
  }))

  const donutData: DonutSlice[] = [
    { name: '≥95%', value: excellent, color: C.green },
    { name: '85–94%', value: good, color: C.amber },
    { name: '<85%', value: low, color: C.red },
    { name: 'no data', value: nodata, color: C.muted },
  ].filter(d => d.value > 0)

  const SortTh = ({ col, label, right = false }: { col: string; label: string; right?: boolean }) => (
    <th onClick={() => tbl.toggleSort(col)} style={thStyle(tbl.sortKey === col, right)}>
      {label}{tbl.sortKey === col ? (tbl.sortDir === 1 ? ' ↑' : ' ↓') : ''}
    </th>
  )

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 16 }}>
        <KpiCard label="repos scanned" value={coverage.length} sub="full ecosystem" />
        <KpiCard label="with data" value={withData.length} sub="coverage collected" />
        <KpiCard label="average" value={`${avg.toFixed(1)}%`} sub={`across ${withData.length} repos`} color={covColor(avg)} />
        <KpiCard label="excellent ≥95%" value={excellent} sub="repos" color={C.green} />
        <KpiCard label="needs attention" value={low} sub="below 85%" color={C.red} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 200px', gap: 12, marginBottom: 12 }}>
        <SectionCard title="coverage by repository" sub="sorted high to low">
          <div style={{ height: Math.max(180, barData.length * 22 + 40) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} horizontal={false} />
                <XAxis type="number" domain={[0, 102]} tickFormatter={v => `${v}%`} tick={{ fill: C.muted, fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" tick={{ fill: C.muted, fontSize: 10 }} axisLine={false} tickLine={false} width={90} />
                <Tooltip
                  contentStyle={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => [`${Number(v).toFixed(2)}%`, 'coverage']}
                  labelStyle={{ color: C.text }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {barData.map((entry, i) => <Cell key={i} fill={`${entry.fill}66`} stroke={entry.fill} strokeWidth={1} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="band distribution" sub="repos per band">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <DonutChart data={donutData} cx={80} cy={80} r={72} label={String(withData.length)} sublabel="repos" />
            <div style={{ width: '100%' }}>
              {[['≥95%', C.green, excellent], ['85–94%', C.amber, good], ['<85%', C.red, low], ['no data', C.muted, nodata]].map(([lbl, color, cnt]) => (
                <div key={lbl as string} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0', fontSize: 11 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: color as string, flexShrink: 0 }} />
                  <span style={{ color: C.muted, flex: 1 }}>{lbl as string}</span>
                  <span style={{ fontWeight: 600, color: C.text }}>{cnt as number}</span>
                </div>
              ))}
            </div>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="coverage summary" sub="all repos · status · thresholds · click headers to sort">
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input
            value={tbl.search} onChange={e => { tbl.setSearch(e.target.value); tbl.setPage(1) }}
            placeholder="search repo…" style={{ flex: 1, minWidth: 140, padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}
          />
          <select value={tbl.filterVal} onChange={e => { tbl.setFilterVal(e.target.value); tbl.setPage(1) }}
            style={{ padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}>
            <option value="">all bands</option>
            <option value="excellent">excellent ≥95%</option>
            <option value="good">good 85–94%</option>
            <option value="low">needs attention</option>
            <option value="none">no data</option>
          </select>
          <span style={{ fontSize: 11, color: C.muted, alignSelf: 'center' }}>{filtered.length} items</span>
        </div>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortTh col="repo" label="repository" />
                <SortTh col="status" label="status" />
                <SortTh col="pct" label="coverage" />
                <SortTh col="stmts" label="stmts" right />
                <SortTh col="missed" label="missed" right />
                <SortTh col="branches" label="branches" right />
                <SortTh col="failUnder" label="fail under" right />
              </tr>
            </thead>
            <tbody>
              {paged.map((r: any) => {
                const color = covColor(r.pct)
                const stLbl = r.status === 'ok' ? 'ok' : r.status?.includes('skip') ? 'skipped' : r.status?.includes('miss') ? 'missing' : r.status?.startsWith('error') ? 'error' : 'partial'
                const stColor = r.status === 'ok' ? C.green : r.status?.includes('skip') || r.status?.includes('miss') ? C.muted : C.amber
                return (
                  <tr key={r.repo} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '8px 12px', fontWeight: 600, fontSize: 12, color: C.text }}>{r.repo.replace('omnibioai-', '').replace('omnibioai_', '')}</td>
                    <td style={{ padding: '8px 12px' }}><Badge label={stLbl} color={stColor} bg={`${stColor}22`} /></td>
                    <td style={{ padding: '8px 12px', minWidth: 130 }}>
                      {r.pct != null ? (
                        <>
                          <div style={{ fontSize: 12, fontWeight: 600, color, marginBottom: 3 }}>{r.pct.toFixed(2)}%</div>
                          <div style={{ height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
                            <div style={{ width: `${r.pct.toFixed(1)}%`, height: '100%', background: color, borderRadius: 2 }} />
                          </div>
                        </>
                      ) : <span style={{ color: C.muted, fontSize: 12 }}>—</span>}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{r.stmts != null ? fmt(r.stmts) : '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{r.missed != null ? fmt(r.missed) : '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{r.branches != null ? fmt(r.branches) : '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontSize: 12, color: C.muted }}>{r.failUnder != null ? r.failUnder : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Pagination page={tbl.page} pages={pages} total={filtered.length} perPage={tbl.perPage} onPage={tbl.setPage} onPerPage={n => { tbl.setPerPage(n); tbl.setPage(1) }} />
      </SectionCard>
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
type SubTab = 'architecture' | 'projects' | 'languages' | 'coverage' | 'health'

const SUBTABS: { id: SubTab; label: string }[] = [
  { id: 'architecture', label: 'Architecture' },
  { id: 'projects',     label: 'Projects' },
  { id: 'languages',    label: 'Languages' },
  { id: 'coverage',     label: 'Code Coverage' },
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

  const needsReport = (subTab === 'projects' || subTab === 'languages' || subTab === 'coverage') && !reportData

  return (
    <div style={{ background: C.bg, borderRadius: 14, padding: 20, margin: '-24px -28px -48px', minHeight: 'calc(100vh - 100px)', color: C.text }}>
      {/* Hero */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 20, paddingBottom: 16, borderBottom: `1px solid ${C.border}` }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, marginBottom: 4 }}>Ecosystem Report</h1>
          <p style={{ fontSize: 13, color: C.muted }}>Architecture overview and project health metrics</p>
          {lastGen && <p style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>Last generated: {new Date(lastGen).toLocaleString()}</p>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          {progressMsg && <span style={{ fontSize: 11, color: generating ? C.muted : C.red }}>{progressMsg}</span>}
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              fontSize: 12, fontWeight: 600, padding: '7px 16px', border: `1px solid ${C.teal}`,
              borderRadius: 8, background: generating ? C.surface : C.teal, color: generating ? C.teal : '#000',
              cursor: generating ? 'not-allowed' : 'pointer', opacity: generating ? 0.7 : 1,
              display: 'flex', alignItems: 'center', gap: 6, transition: 'all 0.15s',
            }}
          >
            {generating && <span style={{ width: 11, height: 11, border: `2px solid ${C.teal}55`, borderTopColor: C.teal, borderRadius: '50%', animation: 'spin 0.8s linear infinite', display: 'inline-block', flexShrink: 0 }} />}
            {generating ? 'Generating…' : '⊕ Generate Report'}
          </button>
        </div>
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
    </div>
  )
}
