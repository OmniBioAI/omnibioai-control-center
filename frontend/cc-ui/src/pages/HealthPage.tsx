import { useState, useEffect, useRef } from 'react'
import type { ServiceResult, DiskResult, SummaryResponse } from '../api'
import { fetchSummary } from '../api'

interface Props { refreshKey: number }

/* ── KPI Card ───────────────────────────────────────────────── */
const KPI_TOP: Record<string, string> = {
  gray: 'var(--color-text-muted)', green: 'var(--color-success)', red: 'var(--color-danger)', amber: 'var(--color-warning)', blue: 'var(--color-info)',
}
const KPI_VAL: Record<string, string> = {
  gray: 'var(--color-static-white)', green: 'var(--color-success)', red: 'var(--color-danger)', amber: 'var(--color-warning)', blue: 'var(--color-info)',
}

function KpiCard({ label, value, sub, color }: {
  label: string; value: string | number; sub: string; color: keyof typeof KPI_TOP
}) {
  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '16px 18px',
      position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: KPI_TOP[color] }} />
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: KPI_VAL[color], lineHeight: 1, marginBottom: 3 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{sub}</div>
    </div>
  )
}

/* ── Type Pill ──────────────────────────────────────────────── */
function TypePill({ type }: { type: string }) {
  const s: Record<string, [string, string]> = {
    http:  ['var(--color-info-dim)',   'var(--color-info)'],
    mysql: ['var(--color-purple-dim)',  'var(--color-purple)'],
    redis: ['var(--color-danger-dim)',   'var(--color-danger)'],
    tcp:   ['var(--color-warning-dim)',  'var(--color-warning)'],
    disk:  ['color-mix(in srgb, var(--color-text-muted) 12%, transparent)', 'var(--color-text-muted)'],
  }
  const [bg, color] = s[type] ?? ['color-mix(in srgb, var(--color-text-muted) 12%, transparent)', 'var(--color-text-muted)']
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
    UP:   { bg: 'var(--color-success-dim)',  color: 'var(--color-success)' },
    WARN: { bg: 'var(--color-warning-dim)', color: 'var(--color-warning)' },
    DOWN: { bg: 'var(--color-danger-dim)',  color: 'var(--color-danger)' },
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
      <div style={{ textAlign: 'center', padding: 24, color: 'var(--muted)', fontSize: 12 }}>
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
            <td style={{ fontWeight: 700, color: 'var(--text)', fontSize: 13, whiteSpace: 'nowrap' }}>
              {svc.name}
            </td>
            <td><TypePill type={svc.type || '—'} /></td>
            <td style={{
              fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)',
              maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {svc.target || '—'}
            </td>
            <td style={{ fontFamily: 'var(--mono)', fontSize: 11, whiteSpace: 'nowrap' }}>
              {svc.latency_ms != null ? (
                <span style={{ color: svc.latency_ms < 10 ? 'var(--color-success)' : 'var(--text)', fontWeight: svc.latency_ms < 10 ? 600 : 400 }}>
                  {svc.latency_ms} ms
                </span>
              ) : (
                <span style={{ color: 'var(--muted)' }}>—</span>
              )}
            </td>
            <td style={{
              maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis',
              whiteSpace: 'nowrap', fontSize: 11, color: 'var(--muted)',
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
                    fontSize: 11, fontWeight: 600, color: 'var(--color-accent)',
                    background: 'var(--color-accent-dim)', border: '1px solid var(--color-accent-dim)',
                    borderRadius: 6, padding: '3px 9px',
                    display: 'inline-block', whiteSpace: 'nowrap',
                  }}
                >
                  Open UI ↗
                </a>
              ) : (
                <span style={{ color: 'var(--muted)', fontSize: 11 }}>—</span>
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
        const borderColor = d.status === 'UP' ? 'var(--color-success)' : d.status === 'WARN' ? 'var(--color-warning)' : 'var(--color-danger)'
        const fillColor   = borderColor
        const textColor   = borderColor
        return (
          <div key={d.name} style={{
            background: 'color-mix(in srgb, var(--color-text) 3%, transparent)', border: '1px solid var(--border)',
            borderLeft: `3px solid ${borderColor}`, borderRadius: 8, padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
                {d.name.replace('disk:', '')}
              </div>
              <div style={{ fontSize: 12, fontWeight: 700, color: textColor }}>
                {d.message}
              </div>
            </div>
            <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 7, fontFamily: 'var(--mono)' }}>
              {d.target}
            </div>
            {freePct != null && (
              <div style={{ height: 5, background: 'var(--border)', borderRadius: 99, overflow: 'hidden' }}>
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
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Health Dashboard</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 10 }}>
          OmniBioAI Ecosystem · Stateless health monitoring
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <MetaPill>v0.1.0</MetaPill>
          <MetaPill accent>auto-refreshes every 10 s</MetaPill>
          <MetaPill>Last checked: {ts}</MetaPill>
        </div>
      </div>

      {error && (
        <div style={{
          background: 'var(--red-bg)', border: '1px solid var(--red-border)',
          borderRadius: 'var(--radius)', padding: '10px 14px',
          color: 'var(--red)', fontSize: 12, marginBottom: 16,
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
        style={{ fontSize: 12, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0, marginBottom: 8 }}
      >
        {rawVisible ? 'Hide raw JSON' : 'Show raw JSON'}
      </button>
      {rawVisible && data && (
        <pre style={{
          background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
          padding: 14, overflow: 'auto', fontSize: 11, color: 'var(--text2)', lineHeight: 1.6,
        }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

/* ── Shared styles ──────────────────────────────────────────── */
function MetaPill({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 99,
      background: accent ? 'var(--color-accent-dim)'  : 'color-mix(in srgb, var(--color-text) 5%, transparent)',
      color:      accent ? 'var(--color-accent)'               : 'var(--muted)',
      border:     `1px solid ${accent ? 'var(--color-accent-border)' : 'var(--border)'}`,
    }}>
      {children}
    </span>
  )
}

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', marginBottom: 16, overflow: 'hidden',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid var(--border)',
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  background: 'color-mix(in srgb, var(--color-text) 3%, transparent)',
}
const cardTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: 'var(--text)' }
const metaPillStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 99,
  background: 'color-mix(in srgb, var(--color-text) 5%, transparent)', color: 'var(--muted)', border: '1px solid var(--border)',
}
