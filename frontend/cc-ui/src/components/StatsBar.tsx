interface Props {
  total: number
  up: number
  down: number
  warn: number
  avgLatency: number | null
}

export default function StatsBar({ total, up, down, warn, avgLatency }: Props) {
  const stats = [
    { label: 'Services', value: total, color: 'var(--text)',  bg: 'var(--bg3)' },
    { label: 'Up',       value: up,    color: 'var(--green)', bg: 'var(--green-dim)' },
    { label: 'Down',     value: down,  color: 'var(--red)',   bg: 'var(--red-dim)'   },
    { label: 'Warn',     value: warn,  color: 'var(--amber)', bg: 'var(--amber-dim)' },
    {
      label: 'Avg Latency',
      value: avgLatency != null ? `${avgLatency}ms` : '—',
      color: 'var(--accent)',
      bg: 'var(--accent-dim)',
    },
  ]

  return (
    <div style={bar}>
      {stats.map(s => (
        <div key={s.label} style={{ ...chip, background: s.bg }}>
          <span style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text3)' }}>
            {s.label}
          </span>
          <span style={{ fontSize: 20, fontWeight: 700, color: s.color, lineHeight: 1 }}>
            {s.value}
          </span>
        </div>
      ))}
    </div>
  )
}

const bar: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  padding: '10px 20px',
  borderBottom: '1px solid var(--border)',
  background: 'var(--bg)',
  flexShrink: 0,
}

const chip: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 3,
  padding: '8px 14px',
  borderRadius: 'var(--radius)',
  minWidth: 70,
}
