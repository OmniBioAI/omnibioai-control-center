import { useState, useEffect } from 'react'

interface BackendInfo {
  label: string
  configured: boolean
  region?: string
  project?: string
  account?: string
  queue?: string
  host?: string
  context?: string
  note?: string
}

async function fetchCloud(): Promise<Record<string, BackendInfo>> {
  const r = await fetch('/cloud')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

const ICONS: Record<string, string> = {
  local:      '🖥',
  slurm:      '⚡',
  aws:        '☁️',
  azure:      '🔷',
  gcp:        '🟡',
  kubernetes: '⎈',
}

export default function CloudPage({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<Record<string, BackendInfo> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchCloud()
      .then(d => { setData(d); setError(null) })
      .catch(e => setError(String(e)))
  }, [refreshKey])

  const badge = (ok: boolean) => (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '2px 8px',
      borderRadius: 99, letterSpacing: '0.05em',
      background: ok ? 'rgba(0,229,160,0.15)' : 'rgba(148,163,184,0.1)',
      color: ok ? '#00e5a0' : 'var(--muted)',
      border: `1px solid ${ok ? 'rgba(0,229,160,0.3)' : 'var(--border)'}`,
    }}>
      {ok ? '✓ CONFIGURED' : 'NOT CONFIGURED'}
    </span>
  )

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Execution Backends</h1>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Cloud and HPC execution backend configuration status
        </p>
      </div>

      {error && (
        <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--radius)', padding: '10px 14px', color: 'var(--red)', fontSize: 12, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 16 }}>
          {Object.entries(data).map(([key, info]) => (
            <div key={key} style={{
              background: 'var(--surface)',
              border: `1px solid ${info.configured ? 'rgba(0,229,160,0.2)' : 'var(--border)'}`,
              borderRadius: 'var(--radius)',
              padding: '16px 18px',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 20 }}>{ICONS[key] || '🔧'}</span>
                  <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{info.label}</span>
                </div>
                {badge(info.configured)}
              </div>

              {/* Show config details if configured */}
              {info.configured && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {info.region && <Detail label="Region" value={info.region} />}
                  {info.project && <Detail label="Project" value={info.project} />}
                  {info.account && <Detail label="Account" value={info.account} />}
                  {info.queue && <Detail label="Queue" value={info.queue} />}
                  {info.host && <Detail label="Host" value={info.host} />}
                  {info.context && <Detail label="Context" value={info.context} />}
                  {info.note && <Detail label="Note" value={info.note} />}
                </div>
              )}

              {!info.configured && key !== 'local' && (
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  Set environment variables in <code style={{ fontFamily: 'var(--mono)', color: '#a855f7' }}>.env</code> to enable
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 11 }}>
      <span style={{ color: 'var(--muted)', minWidth: 60 }}>{label}</span>
      <span style={{ fontFamily: 'var(--mono)', color: 'var(--text2)' }}>{value}</span>
    </div>
  )
}
