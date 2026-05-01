import type { ServiceResult } from '../api'

type Tab = 'health' | 'ecosystem' | 'config'

interface Props {
  tab: Tab
  onTab: (t: Tab) => void
  services: ServiceResult[]
  liveTs: string | null
}

const statusColor = (s: string) =>
  s === 'UP' ? 'var(--green)' : s === 'WARN' ? 'var(--amber)' : 'var(--red)'

const nav: { id: Tab; label: string; icon: string }[] = [
  { id: 'health', label: 'Health', icon: '◉' },
  { id: 'ecosystem', label: 'Ecosystem Report', icon: '⊞' },
  { id: 'config', label: 'Config', icon: '⚙' },
]

export default function Sidebar({ tab, onTab, services, liveTs }: Props) {
  return (
    <aside style={aside}>
      {/* Logo */}
      <div style={logoWrap}>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width="28" height="28" style={{ flexShrink: 0 }}>
          <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="var(--accent)" strokeWidth="1.8" />
          <path d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20" stroke="var(--accent)" strokeWidth="1.6" fill="none" strokeLinecap="round" />
          <circle cx="16" cy="15" r="2.2" fill="var(--accent)" />
        </svg>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--accent)', letterSpacing: '-0.01em' }}>
            Omni<span style={{ fontWeight: 400, color: 'var(--text)' }}>BioAI</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 1 }}>Control Center</div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ marginBottom: 20 }}>
        {nav.map(n => (
          <button key={n.id} onClick={() => onTab(n.id)} style={navBtn(tab === n.id)}>
            <span style={{ fontSize: 14 }}>{n.icon}</span>
            {n.label}
          </button>
        ))}
      </nav>

      {/* Live services */}
      <div style={sectionLabel}>Live Services</div>
      <div style={{ flex: 1, overflowY: 'auto', marginBottom: 10 }}>
        {services.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text3)', padding: '6px 10px' }}>Loading…</div>
        ) : (
          services.map(s => (
            <div key={s.name} style={svcRow}>
              <span
                style={{
                  width: 7, height: 7, borderRadius: '50%',
                  background: statusColor(s.status),
                  flexShrink: 0,
                  ...(s.status === 'UP' ? { animation: 'pulse-dot 2.4s ease-in-out infinite' } : {}),
                }}
              />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>
                {s.name}
              </span>
              {s.latency_ms != null && (
                <span style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--mono)', flexShrink: 0 }}>
                  {s.latency_ms}ms
                </span>
              )}
            </div>
          ))
        )}
      </div>

      {/* Live indicator */}
      <div style={liveRow}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', animation: 'pulse-dot 1.8s ease-in-out infinite', flexShrink: 0 }} />
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>
          Live · {liveTs ? new Date(liveTs).toLocaleTimeString() : '—'}
        </span>
      </div>
    </aside>
  )
}

const aside: React.CSSProperties = {
  width: 196,
  flexShrink: 0,
  height: '100vh',
  borderRight: '1px solid var(--border)',
  background: 'var(--bg)',
  display: 'flex',
  flexDirection: 'column',
  padding: '14px 0 10px',
  overflow: 'hidden',
}

const logoWrap: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 9,
  padding: '0 14px 16px',
  borderBottom: '1px solid var(--border)',
  marginBottom: 12,
}

const navBtn = (active: boolean): React.CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 8,
  width: '100%', textAlign: 'left',
  padding: '7px 14px',
  borderRadius: 0,
  fontSize: 12, fontWeight: active ? 600 : 400,
  color: active ? 'var(--accent)' : 'var(--text2)',
  background: active ? 'var(--accent-dim)' : 'transparent',
  borderLeft: active ? '3px solid var(--accent)' : '3px solid transparent',
  transition: 'background 0.1s, color 0.1s',
  cursor: 'pointer',
})

const sectionLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '0.07em',
  textTransform: 'uppercase', color: 'var(--text3)',
  padding: '0 14px 6px',
}

const svcRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 7,
  padding: '5px 14px',
}

const liveRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6,
  padding: '8px 14px 0',
  borderTop: '1px solid var(--border)',
}
