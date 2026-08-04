import { Menu } from 'lucide-react'
import type { SessionUser } from '../../auth'
import Breadcrumb from './Breadcrumb'
import GlobalSearch from './GlobalSearch'
import NotificationsMenu from './NotificationsMenu'
import OrgSelector from './OrgSelector'
import ProfileMenu from './ProfileMenu'
import ThemeToggle from './ThemeToggle'

interface Props {
  breadcrumb: string[]
  user: SessionUser | null
  onSignOut: () => void
  onMenuToggle: () => void
  /** Page-contextual extra actions (e.g. the pre-existing status chip +
   * Refresh/Generate Report controls, relocated from the old Header.tsx
   * unchanged in behavior) -- optional so most pages don't need it. */
  extraActions?: React.ReactNode
}

/**
 * Admin Console Phase 2: top app bar. Breadcrumb (left) + global search /
 * notifications / theme toggle / org selector / profile menu (right) --
 * every one of these is new UI except ProfileMenu's sign-out, which
 * reuses auth.ts's existing logout() (see ProfileMenu.tsx).
 */
export default function TopAppBar({ breadcrumb, user, onSignOut, onMenuToggle, extraActions }: Props) {
  return (
    <header style={header}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0, flex: 1 }}>
        <button
          onClick={onMenuToggle}
          aria-label="Toggle navigation"
          className="shell-menu-toggle"
          style={{
            display: 'none', alignItems: 'center', justifyContent: 'center',
            width: 32, height: 32, borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)',
            flexShrink: 0,
          }}
        >
          <Menu size={15} />
        </button>
        <Breadcrumb trail={breadcrumb} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        {extraActions && <div className="shell-topbar-extra" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>{extraActions}</div>}
        <GlobalSearch />
        <OrgSelector user={user} />
        <ThemeToggle />
        <NotificationsMenu />
        <ProfileMenu user={user} onSignOut={onSignOut} />
      </div>
    </header>
  )
}

const header: React.CSSProperties = {
  height: 56,
  flexShrink: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 16,
  padding: '0 20px',
  borderBottom: '1px solid var(--border)',
  background: 'var(--surface)',
  boxShadow: 'var(--shadow-header)',
}
