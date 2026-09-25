// Header of the public control.omnibioai.org build (ControlApp is its only
// consumer). Three tabs, each with its own URL (see ControlApp's
// TAB_PATHS). The former Health/LLMs/Cloud/Integrations tabs were operator
// detail and remain in AdminApp; Docker/Config were removed earlier
// because their routes require platform.manage_infra.
export type Tab = 'overview' | 'evidence' | 'ecosystem'

interface Props {
  tab: Tab
  onTab: (t: Tab) => void
  status: 'UP' | 'WARN' | 'DOWN' | null
  onRefresh: () => void
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview',  label: 'Overview' },
  { id: 'evidence',  label: 'Evidence' },
  { id: 'ecosystem', label: 'Ecosystem Report' },
]

const STATUS_CFG = {
  // ControlApp derives this from GET /health on the control center itself,
  // so the label claims only what that check proves.
  UP:   { label: 'Control center online',   bg: 'rgba(34,197,94,0.12)',   color: '#22c55e', border: 'rgba(34,197,94,0.3)',   dot: '#22c55e', pulse: true },
  WARN: { label: 'Services degraded',       bg: 'rgba(245,158,11,0.12)',  color: '#f59e0b', border: 'rgba(245,158,11,0.3)',  dot: '#f59e0b', pulse: false },
  DOWN: { label: 'Control center unreachable',bg: 'rgba(239,68,68,0.12)',   color: '#ef4444', border: 'rgba(239,68,68,0.3)',   dot: '#ef4444', pulse: false },
}

export default function Header({ tab, onTab, status, onRefresh }: Props) {
  const sc = status ? STATUS_CFG[status] : null
  const tabs = TABS

  return (
    <header style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100 }}>
      {/* ── Row 1: logo + status + action buttons ── */}
      <div style={{
        height: 56,
        background: 'var(--surface)',
        borderBottom: '1px solid var(--border)',
        boxShadow: 'var(--shadow-header)',
        display: 'flex', alignItems: 'center',
        gap: 12,
      }} className="cc-header-row">
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
          {/* Same hexagon mark and wordmark as omnibioai.org. */}
          <a href="https://omnibioai.org" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="30" height="30" fill="none" style={{ flexShrink: 0 }} aria-hidden="true">
              <path d="M20 4L34 12V28L20 36L6 28V12L20 4Z" stroke="var(--accent)" strokeWidth="1.5" fill="rgba(0,212,170,0.06)" />
              <circle cx="20" cy="20" r="5" fill="rgba(0,212,170,0.2)" stroke="var(--accent)" strokeWidth="1" />
              <path d="M20 15V9M20 31V25M15 20H9M31 20H25" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            <div>
              <div style={{ fontFamily: 'var(--mono)', fontWeight: 500, fontSize: 16, color: 'var(--accent)', lineHeight: 1.2 }}>
                OmniBioAI
              </div>
              <div className="cc-subtitle" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>Control Center</div>
            </div>
          </a>
        </div>

        {/* Right: status chip + buttons */}
        <div className="cc-header-actions" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {sc && (
            <div className="cc-status-chip" title={sc.label} aria-label={sc.label} style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              background: sc.bg, border: `1px solid ${sc.border}`,
              borderRadius: 99, padding: '5px 13px',
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%', background: sc.dot, flexShrink: 0,
                ...(sc.pulse ? { animation: 'pulse-dot 2s ease-in-out infinite' } : {}),
              }} />
              <span className="cc-status-label" style={{ fontSize: 12, fontWeight: 600, color: sc.color }}>{sc.label}</span>
            </div>
          )}

          <button
            onClick={onRefresh}
            aria-label="Refresh"
            style={{
              fontSize: 13, fontWeight: 600, padding: '7px 15px',
              border: '1px solid var(--border)', borderRadius: 8,
              background: 'transparent', color: 'var(--muted)',
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            ↺<span className="cc-btn-label">Refresh</span>
          </button>

        </div>
      </div>

      {/* ── Row 2: tab navigation ── */}
      <div style={{
        height: 44,
        background: 'var(--surface)',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'stretch',
      }} className="cc-tabbar" role="tablist">
        {tabs.map(t => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => onTab(t.id)}
            style={{
              padding: '0 18px',
              fontSize: 13,
              fontWeight: tab === t.id ? 600 : 400,
              color: tab === t.id ? 'var(--accent)' : 'var(--muted)',
              background: 'none', border: 'none',
              borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
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
