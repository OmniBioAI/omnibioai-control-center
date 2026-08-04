import { useState } from 'react'
import { ChevronDown, LogOut, UserCircle } from 'lucide-react'
import type { SessionUser } from '../../auth'
import { logout } from '../../auth'

/**
 * Admin Console Phase 2: user profile menu. Sign-out reuses auth.ts's
 * existing logout() unchanged (revokes the refresh token + blacklists
 * the access token server-side, same as AuthGate's own sign-out path) --
 * not a second implementation of the same thing.
 */
export default function ProfileMenu({ user, onSignOut }: { user: SessionUser | null; onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  if (!user) return null

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          padding: '5px 10px', background: 'var(--bg2)', color: 'var(--text2)',
        }}
      >
        <UserCircle size={16} color="var(--muted)" />
        <span
          className="shell-profile-label"
          style={{ fontSize: 12, fontWeight: 600, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {user.email}
        </span>
        <ChevronDown size={12} color="var(--muted)" />
      </button>
      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 149 }} />
          <div
            style={{
              position: 'absolute', top: 40, right: 0, zIndex: 150,
              minWidth: 200, background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', overflow: 'hidden',
            }}
          >
            <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{user.email}</div>
              {user.roles.length > 0 && (
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{user.roles.join(', ')}</div>
              )}
            </div>
            <button
              onClick={() => {
                setOpen(false)
                void logout()
                onSignOut()
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                padding: '10px 14px', fontSize: 12, fontWeight: 600, color: 'var(--red)',
                textAlign: 'left',
              }}
            >
              <LogOut size={13} />
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  )
}
