import { useState, useEffect } from 'react'
import type {
  ContainersResponse, SifImagesResponse, PluginImagesResponse,
} from '../api'
import { fetchContainers, fetchSifImages, fetchPluginImages } from '../api'

type Sub = 'containers' | 'sif' | 'plugins'

/* ── Shared table header / cell styles ──────────────────────── */
const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: '#9ca3af',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '9px 14px', borderBottom: '1px solid #f3f4f6',
  textAlign: 'left', background: '#fafafa', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  fontSize: 12, color: '#374151',
  padding: '10px 14px', borderBottom: '1px solid #f9fafb',
  verticalAlign: 'middle',
}
const card: React.CSSProperties = {
  background: 'white', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid #f3f4f6',
  background: '#fafafa', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
}

/* ── Stat pill ──────────────────────────────────────────────── */
function StatPill({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <span style={{
      fontSize: 12, fontWeight: 600, padding: '4px 12px',
      borderRadius: 99, background: '#f3f4f6',
      color: color ?? '#374151', border: '1px solid #e5e7eb',
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
    ? ['#dcfce7', '#15803d']
    : isRestarting
    ? ['#fef3c7', '#92400e']
    : ['#fee2e2', '#b91c1c']
  const label = isRunning ? 'running' : isRestarting ? 'restarting' : 'stopped'
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99, background: bg, color, whiteSpace: 'nowrap' }}>
      {label}
    </span>
  )
}

/* ── Category chip ──────────────────────────────────────────── */
const CAT_COLORS: Record<string, [string, string]> = {
  alignment:           ['#eff6ff', '#2563eb'],
  assembly:            ['#ecfdf5', '#059669'],
  'variant-calling':   ['#fdf4ff', '#9333ea'],
  'rna-seq':           ['#fff7ed', '#ea580c'],
  'single-cell':       ['#f0f9ff', '#0284c7'],
  epigenomics:         ['#fefce8', '#ca8a04'],
  'protein-structure': ['#f5f3ff', '#7c3aed'],
  proteomics:          ['#fff1f2', '#be123c'],
  'population-genetics':['#f0fdf4', '#16a34a'],
  annotation:          ['#fef3c7', '#92400e'],
  metagenomics:        ['#ecfeff', '#0e7490'],
  qc:                  ['#f8fafc', '#475569'],
  imaging:             ['#fdf2f8', '#be185d'],
  genomics:            ['#eff6ff', '#1d4ed8'],
}
function getCatColors(cat: string): [string, string] {
  return CAT_COLORS[cat] ?? ['#f3f4f6', '#6b7280']
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
    <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius)', padding: '10px 14px', color: '#dc2626', fontSize: 12, marginBottom: 16 }}>
      {msg}
    </div>
  )
}
function Loading({ msg }: { msg: string }) {
  return <div style={{ textAlign: 'center', padding: 32, color: '#9ca3af', fontSize: 12 }}>{msg}</div>
}

/* ── A: Platform Containers ─────────────────────────────────── */
function ContainersSection({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<ContainersResponse | null>(null)
  const [err, setErr]   = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchContainers()
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshKey])

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {data && (
          <>
            <StatPill label="running" value={data.running} color="#059669" />
            <StatPill label="stopped" value={data.stopped} color="#dc2626" />
          </>
        )}
      </div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Loading containers…" /> : (
        <div style={card}>
          <div style={cardHead}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>Platform Containers</span>
          </div>
          {!data?.containers?.length ? (
            <div style={{ padding: 24, textAlign: 'center', color: '#9ca3af', fontSize: 12 }}>
              {data?.error ? `Error: ${data.error}` : 'No containers found — is Docker running?'}
            </div>
          ) : (
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
                {data.containers.map((c, i) => (
                  <tr key={i}>
                    <td style={{ ...td, fontWeight: 600, color: '#111827', whiteSpace: 'nowrap' }}>
                      {(c.Names ?? '').replace(/^\//, '') || '—'}
                    </td>
                    <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11, color: '#6b7280', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.Image || '—'}
                    </td>
                    <td style={td}>
                      <ContainerBadge status={c.Status ?? ''} state={c.State} />
                    </td>
                    <td style={{ ...td, fontSize: 11, color: '#9ca3af', whiteSpace: 'nowrap' }}>
                      {c.RunningFor || '—'}
                    </td>
                    <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11, color: '#6b7280', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.Ports || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

/* ── B: Tool SIF Images ─────────────────────────────────────── */
function SifImagesSection({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<SifImagesResponse | null>(null)
  const [err, setErr]   = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selCat, setSelCat] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetchSifImages()
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshKey])

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

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {data && (
          <>
            <StatPill label="built"    value={data.built}     color="#059669" />
            <StatPill label="missing"  value={data.missing}   color="#dc2626" />
            <StatPill label="GB total" value={`${data.total_gb}`} color="#2563eb" />
          </>
        )}
      </div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Scanning SIF images…" /> : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          {/* Category sidebar */}
          <div style={{ width: 168, flexShrink: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#9ca3af', marginBottom: 8 }}>
              Categories
            </div>
            {[['All', images.length] as [string, number], ...catList].map(([cat, count]) => {
              const isAll = cat === 'All'
              const active = isAll ? !selCat : selCat === cat
              return (
                <button
                  key={cat}
                  onClick={() => setSelCat(isAll ? null : (selCat === cat ? null : cat))}
                  style={{
                    width: '100%', textAlign: 'left',
                    padding: '6px 10px', borderRadius: 6, fontSize: 12,
                    background: active ? '#eff6ff' : 'transparent',
                    color: active ? '#2563eb' : '#374151',
                    border: active ? '1px solid #bfdbfe' : '1px solid transparent',
                    fontWeight: active ? 600 : 400, marginBottom: 2,
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cat}</span>
                  <span style={{ background: '#e5e7eb', color: '#6b7280', borderRadius: 99, fontSize: 10, fontWeight: 700, padding: '1px 6px', flexShrink: 0, marginLeft: 4 }}>
                    {count}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Search + table */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: 10 }}>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search tools…"
                style={{ width: '100%', maxWidth: 300 }}
              />
            </div>
            <div style={card}>
              {!filtered.length ? (
                <div style={{ padding: 24, textAlign: 'center', color: '#9ca3af', fontSize: 12 }}>
                  No SIF images found
                </div>
              ) : (
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
                    {filtered.map((img, i) => (
                      <tr key={i}>
                        <td style={{ ...td, fontWeight: 600, color: '#111827' }}>{img.tool}</td>
                        <td style={td}><CategoryChip category={img.category} /></td>
                        <td style={td}>
                          <span style={{
                            fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
                            background: img.exists ? '#dcfce7' : '#fee2e2',
                            color: img.exists ? '#15803d' : '#b91c1c',
                          }}>
                            {img.exists ? 'built' : 'missing'}
                          </span>
                        </td>
                        <td style={{ ...td, minWidth: 130 }}>
                          {img.exists ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <div style={{ width: 60, height: 4, background: '#e5e7eb', borderRadius: 99, overflow: 'hidden', flexShrink: 0 }}>
                                <div style={{
                                  height: '100%',
                                  width: `${Math.min(100, (img.size_mb / 5120) * 100)}%`,
                                  background: '#2563eb', borderRadius: 99,
                                }} />
                              </div>
                              <span style={{ fontSize: 11, fontFamily: 'var(--mono)', color: '#6b7280', whiteSpace: 'nowrap' }}>
                                {img.size_mb >= 1024
                                  ? `${(img.size_mb / 1024).toFixed(1)} GB`
                                  : `${img.size_mb} MB`}
                              </span>
                            </div>
                          ) : (
                            <span style={{ color: '#d1d5db', fontSize: 11 }}>—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── C: Plugin Docker Images ────────────────────────────────── */
function PluginsSection({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<PluginImagesResponse | null>(null)
  const [err, setErr]   = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selCat, setSelCat] = useState<string | null>(null)
  const [showMissingOnly, setShowMissingOnly] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchPluginImages()
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshKey])

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

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {data && (
          <>
            <StatPill label="plugins" value={plugins.length} />
            <StatPill label="present" value={data.present} color="#059669" />
            <StatPill label="missing" value={data.missing} color="#dc2626" />
          </>
        )}
      </div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Scanning plugin images…" /> : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          {/* Category sidebar */}
          <div style={{ width: 168, flexShrink: 0 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#9ca3af', marginBottom: 8 }}>
              Categories
            </div>
            {[['All', plugins.length] as [string, number], ...catList].map(([cat, count]) => {
              const isAll = cat === 'All'
              const active = isAll ? !selCat : selCat === cat
              return (
                <button
                  key={cat}
                  onClick={() => setSelCat(isAll ? null : (selCat === cat ? null : cat))}
                  style={{
                    width: '100%', textAlign: 'left',
                    padding: '6px 10px', borderRadius: 6, fontSize: 12,
                    background: active ? '#eff6ff' : 'transparent',
                    color: active ? '#2563eb' : '#374151',
                    border: active ? '1px solid #bfdbfe' : '1px solid transparent',
                    fontWeight: active ? 600 : 400, marginBottom: 2,
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cat}</span>
                  <span style={{ background: '#e5e7eb', color: '#6b7280', borderRadius: 99, fontSize: 10, fontWeight: 700, padding: '1px 6px', flexShrink: 0, marginLeft: 4 }}>
                    {count}
                  </span>
                </button>
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
              <label style={{ fontSize: 12, color: '#374151', display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
                <input type="checkbox" checked={showMissingOnly} onChange={e => setShowMissingOnly(e.target.checked)} />
                Missing only
              </label>
            </div>
            <div style={card}>
              {!filtered.length ? (
                <div style={{ padding: 24, textAlign: 'center', color: '#9ca3af', fontSize: 12 }}>
                  No plugins match the current filters
                </div>
              ) : (
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
                    {filtered.map((p, i) => (
                      <tr key={i}>
                        <td style={{ ...td, fontWeight: 600, color: '#111827', whiteSpace: 'nowrap' }}>{p.name}</td>
                        <td style={td}><CategoryChip category={p.category} /></td>
                        <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11, color: '#6b7280', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.image}
                        </td>
                        <td style={td}>
                          <span style={{
                            fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
                            background: p.local_status === 'present' ? '#dcfce7' : '#fee2e2',
                            color: p.local_status === 'present' ? '#15803d' : '#b91c1c',
                          }}>
                            {p.local_status}
                          </span>
                        </td>
                        <td style={{ ...td, fontSize: 11, fontFamily: 'var(--mono)', color: '#6b7280', whiteSpace: 'nowrap' }}>
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
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Docker Images</h1>
        <p style={{ fontSize: 13, color: '#6b7280' }}>
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
              color: sub === t.id ? '#2563eb' : '#6b7280',
              background: 'none', border: 'none',
              borderBottom: sub === t.id ? '2px solid #2563eb' : '2px solid transparent',
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
