export type Tab = 'health' | 'docker' | 'ecosystem' | 'config'

interface Props {
  tab: Tab
  onTab: (t: Tab) => void
  status: 'UP' | 'WARN' | 'DOWN' | null
  generating: boolean
  reportExists: boolean
  onRefresh: () => void
  onGenerate: () => void
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:7070'

const TABS: { id: Tab; label: string }[] = [
  { id: 'health',    label: 'Health Dashboard' },
  { id: 'docker',    label: 'Docker Images' },
  { id: 'ecosystem', label: 'Ecosystem Report' },
  { id: 'config',    label: 'Config' },
]

const STATUS_CFG = {
  UP:   { label: 'All systems operational', bg: '#ecfdf5', color: '#059669', border: '#a7f3d0', dot: '#059669', pulse: true },
  WARN: { label: 'Services degraded',       bg: '#fffbeb', color: '#d97706', border: '#fde68a', dot: '#d97706', pulse: false },
  DOWN: { label: 'One or more systems down',bg: '#fef2f2', color: '#dc2626', border: '#fecaca', dot: '#dc2626', pulse: false },
}

export default function Header({ tab, onTab, status, generating, reportExists, onRefresh, onGenerate }: Props) {
  const sc = status ? STATUS_CFG[status] : null

  return (
    <header style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100 }}>
      {/* ── Row 1: logo + status + action buttons ── */}
      <div style={{
        height: 56,
        background: 'var(--surface)',
        boxShadow: 'var(--shadow-header)',
        display: 'flex', alignItems: 'center',
        padding: '0 28px', gap: 12,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width="34" height="34" style={{ flexShrink: 0 }}>
            <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="#2563eb" strokeWidth="1.8" />
            <path d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20"
              stroke="#2563eb" strokeWidth="1.6" fill="none" strokeLinecap="round" />
            <circle cx="16" cy="15" r="2.2" fill="#2563eb" />
          </svg>
          <div>
            <div style={{ fontWeight: 700, fontSize: 18, color: '#2563eb', letterSpacing: '-0.01em', lineHeight: 1.2 }}>
              Omni<span style={{ fontWeight: 400, color: '#111827' }}>BioAI</span>
            </div>
            <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 1 }}>Control Center</div>
          </div>
        </div>

        {/* Right: status chip + buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {sc && (
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              background: sc.bg, border: `1px solid ${sc.border}`,
              borderRadius: 99, padding: '5px 13px',
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%', background: sc.dot, flexShrink: 0,
                ...(sc.pulse ? { animation: 'pulse-dot 2s ease-in-out infinite' } : {}),
              }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: sc.color }}>{sc.label}</span>
            </div>
          )}

          <button
            onClick={onRefresh}
            style={{
              fontSize: 13, fontWeight: 600, padding: '7px 15px',
              border: '1px solid #d1d5db', borderRadius: 8,
              background: 'white', color: '#374151',
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            ↺ Refresh
          </button>

          <button
            onClick={onGenerate}
            disabled={generating}
            style={{
              fontSize: 13, fontWeight: 600, padding: '7px 15px',
              border: 'none', borderRadius: 8,
              background: generating ? '#93c5fd' : '#2563eb',
              color: 'white',
              display: 'inline-flex', alignItems: 'center', gap: 6,
              cursor: generating ? 'not-allowed' : 'pointer',
            }}
          >
            {generating && (
              <span style={{
                width: 12, height: 12,
                border: '2px solid rgba(255,255,255,0.4)', borderTopColor: 'white',
                borderRadius: '50%', animation: 'spin 0.8s linear infinite', flexShrink: 0,
              }} />
            )}
            {generating ? 'Generating…' : '⊕ Generate Report'}
          </button>

          {reportExists && (
            <a
              href={`${BASE}/`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 13, fontWeight: 600, padding: '7px 15px',
                border: '1px solid #bfdbfe', borderRadius: 8,
                background: '#eff6ff', color: '#1d4ed8',
                display: 'inline-flex', alignItems: 'center', gap: 4,
              }}
            >
              View Report ↗
            </a>
          )}
        </div>
      </div>

      {/* ── Row 2: tab navigation ── */}
      <div style={{
        height: 44,
        background: 'var(--surface)',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'stretch',
        padding: '0 28px',
      }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => onTab(t.id)}
            style={{
              padding: '0 18px',
              fontSize: 13,
              fontWeight: tab === t.id ? 600 : 400,
              color: tab === t.id ? '#2563eb' : '#6b7280',
              background: 'none', border: 'none',
              borderBottom: tab === t.id ? '2px solid #2563eb' : '2px solid transparent',
              cursor: 'pointer',
              transition: 'color 0.1s',
              marginBottom: -1,
              whiteSpace: 'nowrap',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
    </header>
  )
}
