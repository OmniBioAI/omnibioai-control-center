export type Tab = 'health' | 'ecosystem' | 'llms' | 'cloud' | 'integrations' | 'organizations' | 'users'

interface Props {
  tab: Tab
  onTab: (t: Tab) => void
  status: 'UP' | 'WARN' | 'DOWN' | null
  reportExists: boolean
  onRefresh: () => void
  // Phase 3 PR2: the existing ops tabs stay admin-role-gated exactly as
  // before; "Organizations" has a broader audience (org_admin/platform_admin
  // too, not just the global "admin" role) -- see auth.ts's
  // hasOrganizationsAccess(). Both default true so every existing caller
  // of Header (App.test.tsx, any future one that doesn't pass these) keeps
  // seeing today's full tab set unless explicitly told otherwise.
  showOpsTabs?: boolean
  showOrganizationsTab?: boolean
  // Phase 3 PR3A: narrower than showOrganizationsTab -- platform_admin
  // only (hasPlatformAdminAccess()), since org_admins have no capability
  // in this cross-tenant user directory at all (their own org's members
  // stay reachable via the existing, unrelated /orgs/{id}/members).
  // Defaults true for the same "unaffected caller" reason as above.
  showUsersTab?: boolean
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

// Public Read-Only Control Center architecture: Docker/Config are gone
// from this list -- both call backend routes gated behind
// platform.manage_infra (docker_router/config_router in main.py), and
// this Header component's only consumer (ControlApp) is now a always-
// anonymous build with no way to satisfy that gate. They remain fully
// available, unchanged, through AdminApp's own Infrastructure section.
// Integrations is new here -- routes_integrations.py has never required
// auth (booleans/labels only, see that module's own comment), it just
// wasn't in ControlApp's tab set before this PR.
const OPS_TABS: { id: Tab; label: string }[] = [
  { id: 'health',       label: 'Health Dashboard' },
  { id: 'ecosystem',    label: 'Ecosystem Report' },
  { id: 'llms',         label: 'LLMs' },
  { id: 'cloud',        label: 'Cloud' },
  { id: 'integrations', label: 'Integrations' },
]

const ORGANIZATIONS_TAB: { id: Tab; label: string } = { id: 'organizations', label: 'Organizations' }
const USERS_TAB: { id: Tab; label: string } = { id: 'users', label: 'Users' }

const STATUS_CFG = {
  UP:   { label: 'All systems operational', bg: 'rgba(34,197,94,0.12)',   color: '#22c55e', border: 'rgba(34,197,94,0.3)',   dot: '#22c55e', pulse: true },
  WARN: { label: 'Services degraded',       bg: 'rgba(245,158,11,0.12)',  color: '#f59e0b', border: 'rgba(245,158,11,0.3)',  dot: '#f59e0b', pulse: false },
  DOWN: { label: 'One or more systems down',bg: 'rgba(239,68,68,0.12)',   color: '#ef4444', border: 'rgba(239,68,68,0.3)',   dot: '#ef4444', pulse: false },
}

export default function Header({
  tab, onTab, status, reportExists, onRefresh,
  showOpsTabs = true, showOrganizationsTab = true, showUsersTab = true,
}: Props) {
  const sc = status ? STATUS_CFG[status] : null
  const tabs = [
    ...(showOpsTabs ? OPS_TABS : []),
    ...(showOrganizationsTab ? [ORGANIZATIONS_TAB] : []),
    ...(showUsersTab ? [USERS_TAB] : []),
  ]

  return (
    <header style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100 }}>
      {/* ── Row 1: logo + status + action buttons ── */}
      <div style={{
        height: 56,
        background: 'var(--surface)',
        borderBottom: '1px solid var(--border)',
        boxShadow: 'var(--shadow-header)',
        display: 'flex', alignItems: 'center',
        padding: '0 28px', gap: 12,
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width="34" height="34" style={{ flexShrink: 0 }}>
            <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="#00e5a0" strokeWidth="1.8" />
            <path d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20"
              stroke="#00e5a0" strokeWidth="1.6" fill="none" strokeLinecap="round" />
            <circle cx="16" cy="15" r="2.2" fill="#00e5a0" />
          </svg>
          <div>
            <div style={{ fontWeight: 700, fontSize: 18, color: '#00e5a0', letterSpacing: '-0.01em', lineHeight: 1.2 }}>
              Omni<span style={{ fontWeight: 400, color: 'var(--text)' }}>BioAI</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>Control Center</div>
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
              border: '1px solid var(--border)', borderRadius: 8,
              background: 'transparent', color: 'var(--muted)',
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}
          >
            ↺ Refresh
          </button>

          {/* Public Read-Only Control Center architecture: the "Generate
              Report" button (POST /report/generate, platform.manage_content
              -gated) is gone -- this build has no way to satisfy that gate
              and no mutation belongs in an always-anonymous surface. "View
              Report" below stays: it's a plain GET link to already-generated,
              already-public report content. */}
          {reportExists && (
            <a
              href={`${BASE}/`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                fontSize: 13, fontWeight: 600, padding: '7px 15px',
                border: '1px solid rgba(0,229,160,0.3)', borderRadius: 8,
                background: 'rgba(0,229,160,0.08)', color: '#00e5a0',
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
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => onTab(t.id)}
            style={{
              padding: '0 18px',
              fontSize: 13,
              fontWeight: tab === t.id ? 600 : 400,
              color: tab === t.id ? '#00e5a0' : 'var(--muted)',
              background: 'none', border: 'none',
              borderBottom: tab === t.id ? '2px solid #00e5a0' : '2px solid transparent',
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
