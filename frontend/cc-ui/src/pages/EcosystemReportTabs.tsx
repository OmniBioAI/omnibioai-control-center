import { useState, useMemo, useCallback } from 'react'
import {
  PieChart, Pie, Cell, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer,
} from 'recharts'
import type { ReportData } from '../api'

/**
 * Public Read-Only Control Center architecture: the parts of
 * EcosystemPage.tsx that are genuinely safe for anonymous access --
 * Projects/Languages/Coverage/Ecosystem(Git) Status, all sourced
 * entirely from GET /report/data (already public, no permission
 * requirement) -- extracted verbatim into their own module so
 * PublicEcosystemPage.tsx can import exactly these and nothing else.
 *
 * Deliberately does NOT include ArchTab, the LANES/ArchNode/Lane
 * architecture-diagram data (real internal service names, internal
 * ports, tech-stack descriptions -- e.g. "auth-service · bcrypt · JWT ·
 * port 8001"), HealthTab (sourced from GET /summary,
 * platform.manage_infra-gated), or GenerateCta (POST /report/generate,
 * platform.manage_content-gated) -- those stay in EcosystemPage.tsx,
 * imported by AdminApp only. Every function/component below is pure
 * presentation over the `data: ReportData` prop each Tab receives; none
 * of them touch the network themselves.
 *
 * EcosystemPage.tsx now imports ProjectsTab/LanguagesTab/CoverageTab/
 * GitStatusTab (and the shared UI pieces they need) from here instead of
 * defining them inline -- same components, same behavior, unchanged for
 * AdminApp -- so this is a relocation, not a rewrite.
 */

// ── Dark theme tokens ──────────────────────────────────────────────────────────
export const C = {
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
export const CAT: Record<string, { color: string; bg: string; label: string }> = {
  core:  { color: C.teal,   bg: 'rgba(0,229,160,0.15)',   label: 'core workbench' },
  sec:   { color: C.red,    bg: 'rgba(239,68,68,0.15)',    label: 'security' },
  exec:  { color: C.purple, bg: 'rgba(168,85,247,0.15)',   label: 'execution' },
  infra: { color: C.amber,  bg: 'rgba(245,158,11,0.15)',   label: 'infrastructure' },
  sdk:   { color: C.blue,   bg: 'rgba(0,148,255,0.15)',    label: 'sdk / clients' },
}

// ── Language type colors (dark theme) ─────────────────────────────────────────
export const LANG: Record<string, { color: string; bg: string; icon: string; label: string }> = {
  backend:  { color: C.teal,   bg: 'rgba(0,229,160,0.15)',    icon: '🐍', label: 'backend' },
  frontend: { color: C.blue,   bg: 'rgba(0,148,255,0.15)',    icon: '🌐', label: 'frontend' },
  docs:     { color: C.muted,  bg: 'rgba(107,114,128,0.15)',  icon: '📄', label: 'docs' },
  config:   { color: C.amber,  bg: 'rgba(245,158,11,0.15)',   icon: '⚙️', label: 'config' },
  infra:    { color: C.purple, bg: 'rgba(168,85,247,0.15)',   icon: '🔧', label: 'infra' },
}

export function fmt(n: number) { return n.toLocaleString() }
export function k(n: number) { return n >= 1000 ? (n / 1000).toFixed(0) + 'k' : String(n) }

// ── Shared UI pieces ───────────────────────────────────────────────────────────
export function KpiCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color ?? C.text, lineHeight: 1, marginBottom: 3 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.muted }}>{sub}</div>}
    </div>
  )
}

export function Badge({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 99, background: bg, color, whiteSpace: 'nowrap' }}>
      {label}
    </span>
  )
}

export function SectionCard({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 18, marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: C.text, marginBottom: 2 }}>{title}</div>
      {sub && <div style={{ fontSize: 11, color: C.muted, marginBottom: 14 }}>{sub}</div>}
      {children}
    </div>
  )
}

// ── Donut chart with center label ─────────────────────────────────────────────
export interface DonutSlice { name: string; value: number; color: string }
export function DonutChart({ data, cx, cy, r, label, sublabel }: { data: DonutSlice[]; cx: number; cy: number; r: number; label: string; sublabel: string }) {
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
export function useTable<T extends Record<string, unknown>>(_rows: T[], defaultSort: string) {
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

export function applyTable<T extends Record<string, unknown>>(
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

export function Pagination({ page, pages, total, perPage, onPage, onPerPage }: {
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

export const thStyle = (active: boolean, right = false): React.CSSProperties => ({
  padding: '8px 12px', fontSize: 10, fontWeight: 700, color: active ? C.teal : C.muted,
  textTransform: 'uppercase', letterSpacing: '0.07em', background: C.surface,
  borderBottom: `1px solid ${C.border}`, cursor: 'pointer', userSelect: 'none',
  textAlign: right ? 'right' : 'left', whiteSpace: 'nowrap',
})

// ── Tab: Projects ───────────────────────────────────────────────────────────
export function ProjectsTab({ data }: { data: ReportData }) {
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

// ── Tab: Languages ───────────────────────────────────────────────────────────
export function LanguagesTab({ data }: { data: ReportData }) {
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

// ── Tab: Code Coverage ───────────────────────────────────────────────────────
export function covBand(pct: number | null) {
  if (pct == null) return 'none'
  if (pct >= 95) return 'excellent'
  if (pct >= 85) return 'good'
  return 'low'
}
export function covColor(pct: number | null) {
  if (pct == null) return C.muted
  return pct >= 95 ? C.green : pct >= 85 ? C.amber : C.red
}

export function CoverageTab({ data }: { data: ReportData }) {
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

// ── Tab: Ecosystem (Git) Status ─────────────────────────────────────────────────
export function gitBand(r: { clean: boolean }) { return r.clean ? 'clean' : 'dirty' }

export function GitStatusTab({ data }: { data: ReportData }) {
  const rows = data.gitStatus ?? []
  const tbl = useTable(rows as unknown as Record<string, unknown>[], 'repo')

  const filtered = useMemo(() => {
    let d = rows.slice()
    if (tbl.search) {
      const q = tbl.search.toLowerCase()
      d = d.filter(r => r.repo.toLowerCase().includes(q) || r.branch.toLowerCase().includes(q))
    }
    if (tbl.filterVal) {
      d = d.filter(r => gitBand(r) === tbl.filterVal)
    }
    const { sortKey, sortDir } = tbl
    d.sort((a, b) => {
      const av = (a as unknown as Record<string, unknown>)[sortKey]
      const bv = (b as unknown as Record<string, unknown>)[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return sortDir
      if (bv == null) return -sortDir
      return av < bv ? sortDir : av > bv ? -sortDir : 0
    })
    return d
  }, [rows, tbl.search, tbl.filterVal, tbl.sortKey, tbl.sortDir])

  const pages = Math.ceil(filtered.length / tbl.perPage)
  const paged = filtered.slice((tbl.page - 1) * tbl.perPage, tbl.page * tbl.perPage)

  const total = rows.length
  const clean = rows.filter(r => r.clean).length
  const dirty = total - clean
  const nonMain = rows.filter(r => r.nonMain).length

  const SortTh = ({ col, label, right = false }: { col: string; label: string; right?: boolean }) => (
    <th onClick={() => tbl.toggleSort(col)} style={thStyle(tbl.sortKey === col, right)}>
      {label}{tbl.sortKey === col ? (tbl.sortDir === 1 ? ' ↑' : ' ↓') : ''}
    </th>
  )

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
        <KpiCard label="repos scanned" value={total} sub="ecosystem root" />
        <KpiCard label="clean" value={clean} sub="working tree" color={C.green} />
        <KpiCard label="dirty" value={dirty} sub="needs attention" color={dirty ? C.red : C.text} />
        <KpiCard label="non-main branch" value={nonMain} sub="not on main/master" color={nonMain ? C.amber : C.text} />
      </div>

      <SectionCard title="git working-tree status" sub="every repo under the ecosystem root · same check as `bash omnibioai-utils/ecosystem_status.sh` · click headers to sort">
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input
            value={tbl.search} onChange={e => { tbl.setSearch(e.target.value); tbl.setPage(1) }}
            placeholder="search repo or branch…" style={{ flex: 1, minWidth: 140, padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}
          />
          <select value={tbl.filterVal} onChange={e => { tbl.setFilterVal(e.target.value); tbl.setPage(1) }}
            style={{ padding: '6px 10px', fontSize: 12, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, color: C.text }}>
            <option value="">all statuses</option>
            <option value="clean">clean</option>
            <option value="dirty">dirty</option>
          </select>
          <span style={{ fontSize: 11, color: C.muted, alignSelf: 'center' }}>{filtered.length} items</span>
        </div>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortTh col="repo" label="repository" />
                <SortTh col="branch" label="branch" />
                <th style={thStyle(false)}>status</th>
                <th style={thStyle(false)}>details</th>
              </tr>
            </thead>
            <tbody>
              {paged.map(r => (
                <tr key={r.repo} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '8px 12px', fontWeight: 600, fontSize: 12, color: C.text }}>{r.repo}</td>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 11, color: r.nonMain ? C.amber : C.muted }}>{r.branch}</td>
                  <td style={{ padding: '8px 12px' }}>
                    {r.clean
                      ? <Badge label="✓ clean" color={C.green} bg={`${C.green}22`} />
                      : <Badge label="✗ dirty" color={C.red} bg={`${C.red}22`} />}
                  </td>
                  <td style={{ padding: '8px 12px', fontSize: 11, color: C.muted }}>{r.details || '—'}</td>
                </tr>
              ))}
              {paged.length === 0 && (
                <tr><td colSpan={4} style={{ textAlign: 'center', color: C.muted, padding: 20, fontSize: 12 }}>no repos found</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <Pagination page={tbl.page} pages={pages} total={filtered.length} perPage={tbl.perPage} onPage={tbl.setPage} onPerPage={n => { tbl.setPerPage(n); tbl.setPage(1) }} />
      </SectionCard>
    </div>
  )
}
