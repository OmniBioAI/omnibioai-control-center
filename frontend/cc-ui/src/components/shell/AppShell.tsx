import { useState, type ReactNode } from 'react'
import type { SessionUser } from '../../auth'
import type { PageKey } from '../../navigation'
import { findNavItem, NAVIGATION } from '../../navigation'
import SidebarNav from './SidebarNav'
import TopAppBar from './TopAppBar'
import type { RecordKind } from './GlobalSearch'
import Footer from './Footer'
import PageErrorBoundary from '../ui/PageErrorBoundary'

interface Props {
  active: PageKey
  onNavigate: (key: PageKey) => void
  user: SessionUser | null
  onSignOut: () => void
  extraActions?: ReactNode
  /** Opens a user's or organization's detail page from the global search. */
  onOpenRecord?: (kind: RecordKind, id: number) => void
  children: ReactNode
}

function breadcrumbFor(key: PageKey): string[] {
  const item = findNavItem(key)
  if (!item) return []
  const section = NAVIGATION.find(s => s.items.some(i => i.key === key || i.children?.some(c => c.key === key)))
  const parent = section?.items.find(i => i.children?.some(c => c.key === key))
  return [section?.label, parent?.label, item.label].filter((v): v is string => !!v)
}

/**
 * Admin Console Phase 2: the reusable enterprise shell -- persistent
 * left nav, top app bar, footer -- every future module plugs its page
 * into via `children`. Wraps AdminApp only; ControlApp is unaffected
 * (still Header.tsx's flat tab strip, unchanged).
 */
export default function AppShell({ active, onNavigate, user, onSignOut, extraActions, onOpenRecord, children }: Props) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const handleNavigate = (key: PageKey) => {
    onNavigate(key)
    setMobileNavOpen(false)
  }

  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' }}>
      <SidebarNav
        active={active}
        onNavigate={handleNavigate}
        mobileOpen={mobileNavOpen}
        onCloseMobile={() => setMobileNavOpen(false)}
      />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <TopAppBar
          breadcrumb={breadcrumbFor(active)}
          user={user}
          onSignOut={onSignOut}
          onMenuToggle={() => setMobileNavOpen(o => !o)}
          onNavigate={handleNavigate}
          onOpenRecord={onOpenRecord && ((kind, id) => { onOpenRecord(kind, id); setMobileNavOpen(false) })}
          extraActions={extraActions}
        />
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
          {/* Every page's padding comes from here, once, so no page can
              render flush against the sidebar or top bar. Full width and
              left-aligned: tables and card grids use the space. */}
          <main className="shell-content" style={{ flex: 1, width: '100%', padding: '24px 32px 48px' }}>
            <PageErrorBoundary key={active}>{children}</PageErrorBoundary>
          </main>
          <Footer />
        </div>
      </div>
    </div>
  )
}
