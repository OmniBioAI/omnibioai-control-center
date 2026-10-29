import { useState, useEffect } from 'react'
import type {
  ContainersResponse, SifImagesResponse, PluginImagesResponse,
} from '../api'
import { fetchContainers, fetchSifImages, fetchPluginImages } from '../api'

type Sub = 'containers' | 'sif' | 'plugins'

/* ── Shared table header / cell styles ──────────────────────── */
const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '9px 14px', borderBottom: '1px solid var(--border)',
  textAlign: 'left', background: 'color-mix(in srgb, var(--color-text) 3%, transparent)', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  fontSize: 12, color: 'var(--text2)',
  padding: '10px 14px', borderBottom: '1px solid var(--border)',
  verticalAlign: 'middle',
}
const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid var(--border)',
  background: 'color-mix(in srgb, var(--color-text) 3%, transparent)', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
}

/* ── Pagination ─────────────────────────────────────────────── */
function Pagination({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  if (totalPages <= 1) return null
  const btnBase: React.CSSProperties = {
    fontSize: 12, fontWeight: 600, padding: '5px 12px', borderRadius: 6,
    border: '1px solid var(--border)', background: 'var(--surface)',
    cursor: 'pointer', transition: 'all 0.1s',
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 0' }}>
      <button
        onClick={() => onPage(page - 1)}
        disabled={page === 1}
        style={{ ...btnBase, color: page === 1 ? 'var(--muted)' : 'var(--text2)', opacity: page === 1 ? 0.4 : 1 }}
      >
        ← Prev
      </button>
      <span style={{ fontSize: 12, color: 'var(--muted)', minWidth: 90, textAlign: 'center' }}>
        Page <span style={{ color: 'var(--text)', fontWeight: 700 }}>{page}</span> of {totalPages}
      </span>
      <button
        onClick={() => onPage(page + 1)}
        disabled={page === totalPages}
        style={{ ...btnBase, color: page === totalPages ? 'var(--muted)' : 'var(--text2)', opacity: page === totalPages ? 0.4 : 1 }}
      >
        Next →
      </button>
    </div>
  )
}

/* ── Stat pill ──────────────────────────────────────────────── */
function StatPill({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <span style={{
      fontSize: 12, fontWeight: 600, padding: '4px 12px',
      borderRadius: 99, background: 'color-mix(in srgb, var(--color-text) 8%, transparent)',
      color: color ?? 'var(--text2)', border: '1px solid var(--border)',
    }}>
      {value} {label}
    </span>
  )
}

/* ── Container status badge ─────────────────────────────────── */
function ContainerBadge({ status, state }: { status: string; state?: string }) {
  const s = (state ?? '').toLowerCase()
  const isRunning = s === 'running' || status.startsWith('Up')
  const isRestarting = s === 'restarting' || status.toLowerCase().includes('restart')
  const [bg, color] = isRunning
    ? ['var(--color-success-dim)', 'var(--color-success)']
    : isRestarting
    ? ['var(--color-warning-dim)', 'var(--color-warning)']
    : ['var(--color-danger-dim)', 'var(--color-danger)']
  const label = isRunning ? 'running' : isRestarting ? 'restarting' : 'stopped'
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99, background: bg, color, whiteSpace: 'nowrap' }}>
      {label}
    </span>
  )
}

/* ── Category chip ──────────────────────────────────────────── */
const CAT_COLORS: Record<string, [string, string]> = {
  alignment:            ['var(--color-info-dim)',   'var(--color-info)'],
  assembly:             ['var(--color-success-dim)',   'var(--color-success)'],
  'variant-calling':    ['var(--color-purple-dim)',  'var(--color-purple)'],
  'rna-seq':            ['var(--color-warning-dim)',  'var(--color-warning)'],
  'single-cell':        ['var(--color-info-dim)',   'var(--color-info)'],
  epigenomics:          ['var(--color-warning-dim)',  'var(--color-warning)'],
  'protein-structure':  ['var(--color-purple-dim)',  'var(--color-purple)'],
  proteomics:           ['var(--color-danger-dim)',   'var(--color-danger)'],
  'population-genetics':['var(--color-success-dim)',   'var(--color-success)'],
  annotation:           ['var(--color-warning-dim)',  'var(--color-warning)'],
  metagenomics:         ['var(--color-info-dim)',  'var(--color-info)'],
  qc:                   ['color-mix(in srgb, var(--color-text-muted) 12%, transparent)', 'var(--color-text-muted)'],
  imaging:              ['var(--color-danger-dim)',   'var(--color-danger)'],
  genomics:             ['var(--color-info-dim)',   'var(--color-info)'],
}
function getCatColors(cat: string): [string, string] {
  return CAT_COLORS[cat] ?? ['color-mix(in srgb, var(--color-text-muted) 12%, transparent)', 'var(--color-text-muted)']
}
function CategoryChip({ category }: { category: string }) {
  const [bg, color] = getCatColors(category)
  return (
    <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 99, background: bg, color, whiteSpace: 'nowrap' }}>
      {category}
    </span>
  )
}

/* ── Error / Loading ────────────────────────────────────────── */
function ErrBox({ msg }: { msg: string }) {
  return (
    <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--radius)', padding: '10px 14px', color: 'var(--red)', fontSize: 12, marginBottom: 16 }}>
      {msg}
    </div>
  )
}
function Loading({ msg }: { msg: string }) {
  return <div style={{ textAlign: 'center', padding: 32, color: 'var(--muted)', fontSize: 12 }}>{msg}</div>
}

/* ── Category sidebar button ────────────────────────────────── */
function CatButton({ cat, count, active, onClick }: { cat: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%', textAlign: 'left',
        padding: '6px 10px', borderRadius: 6, fontSize: 12,
        background: active ? 'var(--color-accent-dim)' : 'transparent',
        color: active ? 'var(--color-accent)' : 'var(--muted)',
        border: active ? '1px solid var(--color-accent-border)' : '1px solid transparent',
        fontWeight: active ? 600 : 400, marginBottom: 2,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        cursor: 'pointer',
      }}
    >
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cat}</span>
      <span style={{ background: 'color-mix(in srgb, var(--color-text) 8%, transparent)', color: 'var(--muted)', borderRadius: 99, fontSize: 10, fontWeight: 700, padding: '1px 6px', flexShrink: 0, marginLeft: 4 }}>
        {count}
      </span>
    </button>
  )
}

/* ── A: Platform Containers ─────────────────────────────────── */
const CONT_PAGE_SIZE = 15

function ContainersSection({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<ContainersResponse | null>(null)
  const [err, setErr]   = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  useEffect(() => {
    setLoading(true)
    setPage(1)
    fetchContainers()
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshKey])

  const containers = data?.containers ?? []
  const totalPages = Math.ceil(containers.length / CONT_PAGE_SIZE)
  const pageRows = containers.slice((page - 1) * CONT_PAGE_SIZE, page * CONT_PAGE_SIZE)

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {data && (
          <>
            <StatPill label="running" value={data.running} color="var(--color-success)" />
            <StatPill label="stopped" value={data.stopped} color="var(--color-danger)" />
          </>
        )}
      </div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Loading containers…" /> : (
        <div style={card}>
          <div style={cardHead}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Platform Containers</span>
            {containers.length > 0 && (
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                {containers.length} total
              </span>
            )}
          </div>
          {!containers.length ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
              {data?.error ? `Error: ${data.error}` : 'No containers found — is Docker running?'}
            </div>
          ) : (
            <>
              <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={th}>Container</th>
                    <th style={th}>Image</th>
                    <th style={th}>Status</th>
                    <th style={th}>Uptime</th>
                    <th style={th}>Ports</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((c, i) => (
                    <tr key={i}>
                      <td style={{ ...td, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>
                        {(c.Names ?? '').replace(/^\//, '') || '—'}
                      </td>
                      <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {c.Image || '—'}
                      </td>
                      <td style={td}>
                        <ContainerBadge status={c.Status ?? ''} state={c.State} />
                      </td>
                      <td style={{ ...td, fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                        {c.RunningFor || '—'}
                      </td>
                      <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {c.Ports || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination page={page} totalPages={totalPages} onPage={setPage} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* ── B: Tool SIF Images ─────────────────────────────────────── */
const SIF_PAGE_SIZE = 20

function SifImagesSection({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<SifImagesResponse | null>(null)
  const [err, setErr]   = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selCat, setSelCat] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  useEffect(() => {
    setLoading(true)
    setPage(1)
    fetchSifImages()
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshKey])

  // Reset to page 1 whenever filters change
  useEffect(() => { setPage(1) }, [search, selCat])

  const images = data?.images ?? []

  const cats = images.reduce<Record<string, number>>((acc, img) => {
    acc[img.category] = (acc[img.category] ?? 0) + 1
    return acc
  }, {})
  const catList = Object.entries(cats).sort((a, b) => b[1] - a[1])

  const filtered = images.filter(img => {
    const matchSearch = !search || img.tool.toLowerCase().includes(search.toLowerCase())
    const matchCat = !selCat || img.category === selCat
    return matchSearch && matchCat
  })

  const totalPages = Math.ceil(filtered.length / SIF_PAGE_SIZE)
  const pageRows = filtered.slice((page - 1) * SIF_PAGE_SIZE, page * SIF_PAGE_SIZE)

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {data && (
          <>
            <StatPill label="built"    value={data.built}     color="var(--color-success)" />
            <StatPill label="missing"  value={data.missing}   color="var(--color-danger)" />
            <StatPill label="GB total" value={`${data.total_gb}`} color="var(--color-info)" />
          </>
        )}
      </div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Scanning SIF images…" /> : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          {/* Category sidebar */}
          <div style={{ width: 168, flexShrink: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--muted)', marginBottom: 8 }}>
              Categories
            </div>
            {[['All', images.length] as [string, number], ...catList].map(([cat, count]) => {
              const isAll = cat === 'All'
              const active = isAll ? !selCat : selCat === cat
              return (
                <CatButton
                  key={cat}
                  cat={cat}
                  count={count}
                  active={active}
                  onClick={() => setSelCat(isAll ? null : (selCat === cat ? null : cat))}
                />
              )
            })}
          </div>

          {/* Search + table */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search tools…"
                style={{ width: '100%', maxWidth: 300 }}
              />
              <span style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                {filtered.length} results
              </span>
            </div>
            <div style={card}>
              {!filtered.length ? (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
                  No SIF images found
                </div>
              ) : (
                <>
                  <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={th}>Tool</th>
                        <th style={th}>Category</th>
                        <th style={th}>Status</th>
                        <th style={th}>Size</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageRows.map((img, i) => (
                        <tr key={i}>
                          <td style={{ ...td, fontWeight: 600, color: 'var(--text)' }}>{img.tool}</td>
                          <td style={td}><CategoryChip category={img.category} /></td>
                          <td style={td}>
                            <span style={{
                              fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
                              background: img.exists ? 'var(--color-success-dim)' : 'var(--color-danger-dim)',
                              color: img.exists ? 'var(--color-success)' : 'var(--color-danger)',
                            }}>
                              {img.exists ? 'built' : 'missing'}
                            </span>
                          </td>
                          <td style={{ ...td, minWidth: 130 }}>
                            {img.exists ? (
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <div style={{ width: 60, height: 4, background: 'var(--border)', borderRadius: 99, overflow: 'hidden', flexShrink: 0 }}>
                                  <div style={{
                                    height: '100%',
                                    width: `${Math.min(100, (img.size_mb / 5120) * 100)}%`,
                                    background: 'var(--color-info)', borderRadius: 99,
                                  }} />
                                </div>
                                <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                                  {img.size_mb >= 1024
                                    ? `${(img.size_mb / 1024).toFixed(1)} GB`
                                    : `${img.size_mb} MB`}
                                </span>
                              </div>
                            ) : (
                              <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination page={page} totalPages={totalPages} onPage={setPage} />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── C: Plugin Docker Images ────────────────────────────────── */
const PLUGIN_PAGE_SIZE = 20

function PluginsSection({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<PluginImagesResponse | null>(null)
  const [err, setErr]   = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selCat, setSelCat] = useState<string | null>(null)
  const [showMissingOnly, setShowMissingOnly] = useState(false)
  const [page, setPage] = useState(1)

  useEffect(() => {
    setLoading(true)
    setPage(1)
    fetchPluginImages()
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshKey])

  // Reset to page 1 whenever filters change
  useEffect(() => { setPage(1) }, [search, selCat, showMissingOnly])

  const plugins = data?.plugins ?? []

  const cats = plugins.reduce<Record<string, number>>((acc, p) => {
    acc[p.category] = (acc[p.category] ?? 0) + 1
    return acc
  }, {})
  const catList = Object.entries(cats).sort((a, b) => b[1] - a[1])

  const filtered = plugins.filter(p => {
    const matchSearch = !search || p.name.toLowerCase().includes(search.toLowerCase()) || p.plugin.toLowerCase().includes(search.toLowerCase())
    const matchCat = !selCat || p.category === selCat
    const matchStatus = !showMissingOnly || p.local_status === 'missing'
    return matchSearch && matchCat && matchStatus
  })

  const totalPages = Math.ceil(filtered.length / PLUGIN_PAGE_SIZE)
  const pageRows = filtered.slice((page - 1) * PLUGIN_PAGE_SIZE, page * PLUGIN_PAGE_SIZE)

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {data && (
          <>
            <StatPill label="plugins" value={plugins.length} />
            <StatPill label="present" value={data.present} color="var(--color-success)" />
            <StatPill label="missing" value={data.missing} color="var(--color-danger)" />
          </>
        )}
      </div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Scanning plugin images…" /> : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          {/* Category sidebar */}
          <div style={{ width: 168, flexShrink: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--muted)', marginBottom: 8 }}>
              Categories
            </div>
            {[['All', plugins.length] as [string, number], ...catList].map(([cat, count]) => {
              const isAll = cat === 'All'
              const active = isAll ? !selCat : selCat === cat
              return (
                <CatButton
                  key={cat}
                  cat={cat}
                  count={count}
                  active={active}
                  onClick={() => setSelCat(isAll ? null : (selCat === cat ? null : cat))}
                />
              )
            })}
          </div>

          {/* Search + table */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search plugins…"
                style={{ maxWidth: 260 }}
              />
              <label style={{ fontSize: 12, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                <input type="checkbox" checked={showMissingOnly} onChange={e => setShowMissingOnly(e.target.checked)} />
                Missing only
              </label>
              <span style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap', marginLeft: 'auto' }}>
                {filtered.length} results
              </span>
            </div>
            <div style={card}>
              {!filtered.length ? (
                <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
                  No plugins match the current filters
                </div>
              ) : (
                <>
                  <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={th}>Plugin</th>
                        <th style={th}>Category</th>
                        <th style={th}>Image</th>
                        <th style={th}>Local Status</th>
                        <th style={th}>Size</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageRows.map((p, i) => (
                        <tr key={i}>
                          <td style={{ ...td, fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap' }}>{p.name}</td>
                          <td style={td}><CategoryChip category={p.category} /></td>
                          <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {p.image}
                          </td>
                          <td style={td}>
                            <span style={{
                              fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
                              background: p.local_status === 'present' ? 'var(--color-success-dim)' : 'var(--color-danger-dim)',
                              color: p.local_status === 'present' ? 'var(--color-success)' : 'var(--color-danger)',
                            }}>
                              {p.local_status}
                            </span>
                          </td>
                          <td style={{ ...td, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                            {p.local_status === 'present' && p.size_mb > 0
                              ? p.size_mb >= 1024
                                ? `${(p.size_mb / 1024).toFixed(1)} GB`
                                : `${p.size_mb} MB`
                              : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <Pagination page={page} totalPages={totalPages} onPage={setPage} />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── DockerPage ─────────────────────────────────────────────── */
export default function DockerPage({ refreshKey }: { refreshKey: number }) {
  const [sub, setSub] = useState<Sub>('containers')

  const subTabs: { id: Sub; label: string }[] = [
    { id: 'containers', label: 'Platform Containers' },
    { id: 'sif',        label: 'Tool SIF Images' },
    { id: 'plugins',    label: 'Plugin Docker Images' },
  ]

  return (
    <div>
      {/* Hero */}
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Docker Images</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Platform containers, tool SIF images, and plugin Docker images
        </p>
      </div>

      {/* Sub-section tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
        {subTabs.map(t => (
          <button
            key={t.id}
            onClick={() => setSub(t.id)}
            style={{
              padding: '10px 16px', fontSize: 13,
              fontWeight: sub === t.id ? 600 : 400,
              color: sub === t.id ? 'var(--color-accent)' : 'var(--muted)',
              background: 'none', border: 'none',
              borderBottom: sub === t.id ? '2px solid var(--color-accent)' : '2px solid transparent',
              cursor: 'pointer', marginBottom: -1, transition: 'color 0.1s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {sub === 'containers' && <ContainersSection refreshKey={refreshKey} />}
      {sub === 'sif'        && <SifImagesSection  refreshKey={refreshKey} />}
      {sub === 'plugins'    && <PluginsSection     refreshKey={refreshKey} />}
    </div>
  )
}
