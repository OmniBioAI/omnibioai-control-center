import { useState, useEffect, useRef } from 'react'
import type { ServiceResult, DiskResult, SummaryResponse } from '../api'
import { fetchSummary } from '../api'

interface Props { refreshKey: number }

/* ── KPI Card ───────────────────────────────────────────────── */
const KPI_TOP: Record<string, string> = {
  gray: '#d1d5db', green: '#10b981', red: '#ef4444', amber: '#f59e0b', blue: '#2563eb',
}
const KPI_VAL: Record<string, string> = {
  gray: '#111827', green: '#059669', red: '#dc2626', amber: '#d97706', blue: '#2563eb',
}

function KpiCard({ label, value, sub, color }: {
  label: string; value: string | number; sub: string; color: keyof typeof KPI_TOP
}) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '16px 18px',
      position: 'relative', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: KPI_TOP[color] }} />
      <div style={{ fontSize: 10, fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: KPI_VAL[color], lineHeight: 1, marginBottom: 3 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: '#9ca3af' }}>{sub}</div>
    </div>
  )
}

/* ── Type Pill ──────────────────────────────────────────────── */
function TypePill({ type }: { type: string }) {
  const s: Record<string, [string, string]> = {
    http:  ['#eff6ff', '#2563eb'],
    mysql: ['rgba(124,58,237,0.08)', '#7c3aed'],
    redis: ['#fef2f2', '#dc2626'],
  }
  const [bg, color] = s[type] ?? ['#f3f4f6', '#6b7280']
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
      background: bg, color, letterSpacing: '0.04em', whiteSpace: 'nowrap',
    }}>
      {type}
    </span>
  )
}

/* ── Status Badge ───────────────────────────────────────────── */
function StatusBadge({ status }: { status: 'UP' | 'WARN' | 'DOWN' }) {
  const cfg = {
    UP:   { bg: '#dcfce7', color: '#15803d' },
    WARN: { bg: '#fef3c7', color: '#92400e' },
    DOWN: { bg: '#fee2e2', color: '#b91c1c' },
  }[status]
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '3px 9px',
      borderRadius: 99, background: cfg.bg, color: cfg.color, whiteSpace: 'nowrap',
    }}>
      {status}
    </span>
  )
}

/* ── Services Table ─────────────────────────────────────────── */
function ServicesTable({ services }: { services: ServiceResult[] }) {
  if (!services.length) {
    return (
      <div style={{ textAlign: 'center', padding: 24, color: '#9ca3af', fontSize: 12 }}>
        No services configured
      </div>
    )
  }
  return (
    <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          {['Service', 'Type', 'Target', 'Latency', 'Message', 'Status', 'UI'].map(h => (
            <th key={h}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {services.map(svc => (
          <tr key={svc.name}>
            <td style={{ fontWeight: 700, color: '#111827', fontSize: 13, whiteSpace: 'nowrap' }}>
              {svc.name}
            </td>
            <td><TypePill type={svc.type || '—'} /></td>
            <td style={{
              fontFamily: 'var(--mono)', fontSize: 11, color: '#9ca3af',
              maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {svc.target || '—'}
            </td>
            <td style={{ fontFamily: 'var(--mono)', fontSize: 11, whiteSpace: 'nowrap' }}>
              {svc.latency_ms != null ? (
                <span style={{ color: svc.latency_ms < 10 ? '#059669' : '#374151', fontWeight: svc.latency_ms < 10 ? 600 : 400 }}>
                  {svc.latency_ms} ms
                </span>
              ) : (
                <span style={{ color: '#d1d5db' }}>—</span>
              )}
            </td>
            <td style={{
              maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis',
              whiteSpace: 'nowrap', fontSize: 11, color: '#6b7280',
            }}>
              {svc.message || '—'}
            </td>
            <td><StatusBadge status={svc.status} /></td>
            <td>
              {svc.ui_url ? (
                <a
                  href={svc.ui_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontSize: 11, fontWeight: 600, color: '#2563eb',
                    background: '#eff6ff', border: '1px solid #bfdbfe',
                    borderRadius: 6, padding: '3px 9px',
                    display: 'inline-block', whiteSpace: 'nowrap',
                  }}
                >
                  Open UI ↗
                </a>
              ) : (
                <span style={{ color: '#d1d5db', fontSize: 11 }}>—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/* ── Disk Grid ──────────────────────────────────────────────── */
function DiskGrid({ disks }: { disks: DiskResult[] }) {
  if (!disks.length) return null
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
      {disks.map(d => {
        const m = d.message?.match(/([0-9.]+)%/)
        const freePct = m ? parseFloat(m[1]) : null
        const borderColor = d.status === 'UP' ? '#10b981' : d.status === 'WARN' ? '#f59e0b' : '#ef4444'
        const fillColor  = d.status === 'UP' ? '#10b981' : d.status === 'WARN' ? '#f59e0b' : '#ef4444'
        const textColor  = d.status === 'UP' ? '#059669' : d.status === 'WARN' ? '#d97706' : '#dc2626'
        return (
          <div key={d.name} style={{
            background: '#fafafa', border: '1px solid #f3f4f6',
            borderLeft: `3px solid ${borderColor}`, borderRadius: 8, padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#111827' }}>
                {d.name.replace('disk:', '')}
              </div>
              <div style={{ fontSize: 12, fontWeight: 700, color: textColor }}>
                {d.message}
              </div>
            </div>
            <div style={{ fontSize: 10, color: '#9ca3af', marginBottom: 7, fontFamily: 'var(--mono)' }}>
              {d.target}
            </div>
            {freePct != null && (
              <div style={{ height: 5, background: '#e5e7eb', borderRadius: 99, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', width: `${freePct.toFixed(1)}%`,
                  background: fillColor, borderRadius: 99,
                }} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ── HealthPage ─────────────────────────────────────────────── */
export default function HealthPage({ refreshKey }: Props) {
  const [data, setData] = useState<SummaryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rawVisible, setRawVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = async () => {
    try {
      const d = await fetchSummary()
      setData(d)
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    load()
    timerRef.current = setInterval(load, 10_000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [refreshKey])

  const services = data?.services ?? []
  const disk = data?.system?.disk ?? []
  const up   = services.filter(s => s.status === 'UP').length
  const down = services.filter(s => s.status === 'DOWN').length
  const warn = services.filter(s => s.status === 'WARN').length
  const diskWarnings = disk.filter(d => d.status !== 'UP').length
  const ts = data?.generated_at ? new Date(data.generated_at).toLocaleTimeString() : '—'

  return (
    <div>
      {/* Hero */}
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#111827', marginBottom: 4 }}>Health Dashboard</h1>
        <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 10 }}>
          OmniBioAI Ecosystem · Stateless health monitoring
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <MetaPill>v0.1.0</MetaPill>
          <MetaPill blue>auto-refreshes every 10 s</MetaPill>
          <MetaPill>Last checked: {ts}</MetaPill>
        </div>
      </div>

      {error && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius)', padding: '10px 14px',
          color: '#dc2626', fontSize: 12, marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 20 }}>
        <KpiCard label="Services"      value={services.length} sub="monitored"      color="gray" />
        <KpiCard label="Healthy"       value={up}              sub="UP"             color="green" />
        <KpiCard label="Down"          value={down}            sub="need attention" color="red" />
        <KpiCard label="Degraded"      value={warn}            sub="WARN"           color="amber" />
        <KpiCard label="Disk warnings" value={diskWarnings}    sub="paths checked"  color="blue" />
      </div>

      {/* Services table */}
      <div style={card}>
        <div style={cardHead}>
          <span style={cardTitle}>Services</span>
          <span style={metaPillStyle}>Last checked: {ts}</span>
        </div>
        <ServicesTable services={services} />
      </div>

      {/* Disk grid */}
      {disk.length > 0 && (
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={cardHead}><span style={cardTitle}>Disk Checks</span></div>
          <div style={{ padding: 16 }}>
            <DiskGrid disks={disk} />
          </div>
        </div>
      )}

      {/* Raw JSON toggle */}
      <button
        onClick={() => setRawVisible(v => !v)}
        style={{ fontSize: 12, color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0, marginBottom: 8 }}
      >
        {rawVisible ? 'Hide raw JSON' : 'Show raw JSON'}
      </button>
      {rawVisible && data && (
        <pre style={{
          background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 8,
          padding: 14, overflow: 'auto', fontSize: 11, color: '#374151', lineHeight: 1.6,
        }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

/* ── Shared styles ──────────────────────────────────────────── */
function MetaPill({ children, blue }: { children: React.ReactNode; blue?: boolean }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 99,
      background: blue ? '#eff6ff' : '#f3f4f6',
      color: blue ? '#1d4ed8' : '#6b7280',
      border: `1px solid ${blue ? '#bfdbfe' : '#e5e7eb'}`,
    }}>
      {children}
    </span>
  )
}

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', marginBottom: 16, overflow: 'hidden',
  boxShadow: 'var(--shadow-card)',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid #f3f4f6',
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  background: '#fafafa',
}
const cardTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: '#111827' }
const metaPillStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 99,
  background: '#f3f4f6', color: '#6b7280', border: '1px solid #e5e7eb',
}
