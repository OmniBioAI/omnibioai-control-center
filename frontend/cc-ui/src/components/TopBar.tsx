type Status = 'UP' | 'WARN' | 'DOWN'

interface Props {
  title: string
  status: Status | null
  lastUpdated: string | null
  onRefresh: () => void
}

const statusConfig = {
  UP:   { label: 'SYSTEM UP',   bg: 'var(--green-dim)',  color: 'var(--green)',  dot: 'var(--green)' },
  WARN: { label: 'DEGRADED',    bg: 'var(--amber-dim)',  color: 'var(--amber)',  dot: 'var(--amber)' },
  DOWN: { label: 'SYSTEM DOWN', bg: 'var(--red-dim)',    color: 'var(--red)',    dot: 'var(--red)'   },
}

export default function TopBar({ title, status, lastUpdated, onRefresh }: Props) {
  const sc = status ? statusConfig[status] : null

  return (
    <header style={header}>
      <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)', letterSpacing: '-0.01em' }}>
        {title}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {lastUpdated && (
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>
            Updated {new Date(lastUpdated).toLocaleTimeString()}
          </span>
        )}
        {sc && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: sc.bg, border: `1px solid ${sc.color}33`, borderRadius: 99, padding: '4px 12px' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: sc.dot, flexShrink: 0 }} />
            <span style={{ fontSize: 11, fontWeight: 700, color: sc.color, letterSpacing: '0.05em' }}>{sc.label}</span>
          </div>
        )}
        <button onClick={onRefresh} style={refreshBtn} title="Refresh">
          ↺ Refresh
        </button>
      </div>
    </header>
  )
}

const header: React.CSSProperties = {
  height: 50,
  flexShrink: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '0 20px',
  borderBottom: '1px solid var(--border)',
  background: 'var(--bg)',
}

const refreshBtn: React.CSSProperties = {
  fontSize: 12, fontWeight: 500,
  padding: '5px 12px',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius)',
  background: 'var(--bg2)',
  color: 'var(--text2)',
  cursor: 'pointer',
  transition: 'background 0.1s, border-color 0.1s',
}
