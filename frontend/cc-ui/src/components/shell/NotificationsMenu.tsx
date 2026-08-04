import { useState } from 'react'
import { Bell } from 'lucide-react'
import EmptyState from '../ui/EmptyState'

/**
 * Admin Console Phase 2: notifications placeholder. The bell is real UI
 * (click to open), but the panel always shows an honest empty state --
 * there is no notification system to back this yet, so it never
 * fabricates example notifications.
 */
export default function NotificationsMenu() {
  const [open, setOpen] = useState(false)

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        aria-label="Notifications"
        title="Notifications"
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 32, height: 32, borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)',
        }}
      >
        <Bell size={15} />
      </button>
      {open && (
        <>
          <div
            onClick={() => setOpen(false)}
            style={{ position: 'fixed', inset: 0, zIndex: 149 }}
          />
          <div
            style={{
              position: 'absolute', top: 40, right: 0, zIndex: 150,
              width: 280, background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)',
            }}
          >
            <EmptyState icon={Bell} title="No notifications" description="You're all caught up." />
          </div>
        </>
      )}
    </div>
  )
}
