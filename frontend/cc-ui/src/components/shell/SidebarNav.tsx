import {
  Activity, Bot, BookOpen, BrainCircuit, Building2, Cloud, Container,
  CreditCard, FlaskConical, KeyRound, KeySquare, LayoutDashboard, Network,
  Plug, Puzzle, ScrollText, Server, Settings, Settings2, ShieldCheck, Clock, Users,
  UsersRound, Workflow, Wrench,
} from 'lucide-react'
import { NAVIGATION, isNavItemVisible } from '../../navigation'
import type { NavItem, PageKey } from '../../navigation'
import type { IconComponent } from '../ui/icon-type'

const ICONS: Partial<Record<PageKey, IconComponent>> = {
  overview: LayoutDashboard,
  organizations: Building2,
  users: Users,
  teams: UsersRound,
  roles: ShieldCheck,
  infrastructure: Server,
  health: Activity,
  docker: Container,
  ecosystem: Network,
  config: Settings2,
  llms: Bot,
  cloud: Cloud,
  workflows: Workflow,
  'tool-execution': Wrench,
  'ai-models': BrainCircuit,
  iam: KeyRound,
  'audit-logs': ScrollText,
  sessions: Clock,
  'api-keys': KeySquare,
  billing: CreditCard,
  rag: BookOpen,
  pubmed: FlaskConical,
  plugins: Puzzle,
  integrations: Plug,
  settings: Settings,
}

interface Props {
  active: PageKey
  onNavigate: (key: PageKey) => void
  /** Mobile off-canvas open state -- controlled by AppShell/TopAppBar's
   * hamburger button. Always "open" (irrelevant) above the 768px
   * breakpoint; see index.css's .shell-sidebar rules. */
  mobileOpen: boolean
  onCloseMobile: () => void
}

function NavRow({ item, active, onNavigate, depth }: {
  item: NavItem; active: PageKey; onNavigate: (key: PageKey) => void; depth: number
}) {
  const Icon = ICONS[item.key]
  const isActive = item.key === active
  return (
    <button
      onClick={() => onNavigate(item.key)}
      style={{
        display: 'flex', alignItems: 'center', gap: 9,
        width: '100%', textAlign: 'left',
        padding: depth ? '6px 14px 6px 34px' : '7px 14px',
        fontSize: depth ? 12 : 13, fontWeight: isActive ? 600 : 400,
        color: isActive ? 'var(--accent)' : 'var(--text2)',
        background: isActive ? 'var(--accent-dim)' : 'transparent',
        borderLeft: isActive ? '3px solid var(--accent)' : '3px solid transparent',
      }}
    >
      {!depth && Icon && <Icon size={15} />}
      <span className="shell-nav-label" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.label}
      </span>
      {!item.functional && (
        <span
          className="shell-nav-label"
          style={{
            fontSize: 9, fontWeight: 700, color: 'var(--muted)', background: 'var(--bg3)',
            borderRadius: 99, padding: '2px 6px', flexShrink: 0, textTransform: 'uppercase',
          }}
        >
          Soon
        </span>
      )}
    </button>
  )
}

/**
 * Admin Console Phase 2: the sectioned, permission-aware left nav.
 * Replaces Header.tsx's flat tab strip for AdminApp only -- ControlApp
 * keeps using Header.tsx exactly as before, unmodified.
 *
 * Renders every section/item from navigation.ts, skipping only what
 * isNavItemVisible() says isn't visible for the current session (the
 * exact same auth.ts permission checks that gated the old tab strip --
 * no new permission logic). Coming-soon items are always shown (see
 * navigation.ts's own docstring for why) and remain clickable, landing
 * on the shared <ComingSoon /> page for that section.
 */
export default function SidebarNav({ active, onNavigate, mobileOpen, onCloseMobile }: Props) {
  return (
    <>
      <div
        className="shell-sidebar-backdrop"
        data-open={mobileOpen}
        onClick={onCloseMobile}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 199 }}
      />
      <aside className="shell-sidebar" data-open={mobileOpen} style={aside}>
        <div style={logoWrap}>
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 34" width="28" height="28" style={{ flexShrink: 0 }}>
            <polygon points="16,2 28,8 28,22 16,28 4,22 4,8" fill="none" stroke="var(--accent)" strokeWidth="1.8" />
            <path d="M11 9 C16 13,14 17,20 20 M20 9 C15 13,17 17,11 20" stroke="var(--accent)" strokeWidth="1.6" fill="none" strokeLinecap="round" />
            <circle cx="16" cy="15" r="2.2" fill="var(--accent)" />
          </svg>
          <div className="shell-nav-label">
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--accent)', letterSpacing: '-0.01em' }}>
              Omni<span style={{ fontWeight: 400, color: 'var(--text)' }}>BioAI</span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 1 }}>Admin Console</div>
          </div>
        </div>

        <nav style={{ flex: 1, overflowY: 'auto', paddingBottom: 12 }}>
          {NAVIGATION.map(section => {
            const visibleItems = section.items.filter(isNavItemVisible)
            if (visibleItems.length === 0) return null
            return (
              <div key={section.key} style={{ marginBottom: 14 }}>
                {section.label && (
                  <div className="shell-section-label" style={sectionLabel}>{section.label}</div>
                )}
                {visibleItems.map(item => (
                  <div key={item.key}>
                    <NavRow item={item} active={active} onNavigate={onNavigate} depth={0} />
                    {item.children?.filter(isNavItemVisible).map(child => (
                      <NavRow key={child.key} item={child} active={active} onNavigate={onNavigate} depth={1} />
                    ))}
                  </div>
                ))}
              </div>
            )
          })}
        </nav>
      </aside>
    </>
  )
}

const aside: React.CSSProperties = {
  width: 220,
  flexShrink: 0,
  height: '100vh',
  borderRight: '1px solid var(--border)',
  background: 'var(--bg)',
  display: 'flex',
  flexDirection: 'column',
  padding: '14px 0 10px',
}

const logoWrap: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 9,
  padding: '0 14px 16px',
  borderBottom: '1px solid var(--border)',
  marginBottom: 12,
}

const sectionLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '0.07em',
  textTransform: 'uppercase', color: 'var(--text3)',
  padding: '0 14px 6px',
}
