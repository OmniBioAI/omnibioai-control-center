import { useEffect, useState } from 'react'
import { fetchHealth } from '../api'

interface Props { refreshKey: number }

/**
 * Public Read-Only Control Center architecture, section 5 (Health):
 * the existing HealthPage.tsx calls GET /summary, which is deliberately
 * gated behind platform.manage_infra (main.py) -- it returns per-service
 * connection targets (svc.target), which is exactly the "internal
 * topology" class of data that gate exists to keep out of an anonymous
 * response. Rather than weakening that gate, this is a genuinely
 * separate, deliberately minimal page for the anonymous ControlApp
 * build: it calls only GET /health (routes_health.py -- no permission
 * requirement, `{"status": "ok"}`, nothing else) and renders a single
 * liveness indicator. No hostnames, LAN IPs, container inventory, mount
 * paths, or per-service detail of any kind. HealthPage.tsx itself is
 * unchanged and still used, as before, by AdminApp's authenticated
 * Infrastructure > Health page.
 */
export default function PublicHealthPage({ refreshKey }: Props) {
  const [status, setStatus] = useState<'checking' | 'ok' | 'unreachable'>('checking')
  const [checkedAt, setCheckedAt] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setStatus('checking')
      try {
        const r = await fetchHealth()
        if (cancelled) return
        setStatus(r.status === 'ok' ? 'ok' : 'unreachable')
      } catch {
        if (!cancelled) setStatus('unreachable')
      }
      if (!cancelled) setCheckedAt(new Date().toLocaleTimeString())
    }
    load()
    const t = setInterval(load, 15_000)
    return () => { cancelled = true; clearInterval(t) }
  }, [refreshKey])

  const cfg = {
    checking:    { label: 'Checking…',          bg: 'rgba(255,255,255,0.05)', color: 'var(--muted)' },
    ok:          { label: 'Operational',         bg: 'rgba(34,197,94,0.12)',   color: '#22c55e' },
    unreachable: { label: 'Unreachable',          bg: 'rgba(239,68,68,0.12)',  color: '#ef4444' },
  }[status]

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Platform Status</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          OmniBioAI Ecosystem · Public liveness check
        </p>
      </div>

      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', padding: '20px 22px',
        display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <span style={{
          width: 10, height: 10, borderRadius: '50%', background: cfg.color, flexShrink: 0,
        }} />
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: cfg.color }}>{cfg.label}</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            {checkedAt ? `Last checked: ${checkedAt}` : 'Checking…'}
          </div>
        </div>
      </div>
    </div>
  )
}
