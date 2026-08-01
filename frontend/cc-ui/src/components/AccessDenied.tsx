import AdminLogo from './AdminLogo'
import type { SessionUser } from '../auth'

interface Props {
  user: SessionUser | null
  onSignOut: () => void
}

// Reached when a token validates (the user IS authenticated) but
// hasAdminAccess() is false -- distinct from the login screen's own error
// states, which only ever mean "not authenticated yet". Never redirects on
// its own; the only way out is the explicit sign-out action below, so an
// admin-less account can't end up bouncing between /login and here.
export default function AccessDenied({ user, onSignOut }: Props) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        fontFamily: 'var(--sans)',
        padding: 24,
      }}
    >
      <div
        style={{
          width: 380,
          maxWidth: '100%',
          textAlign: 'center',
          background: 'var(--surface)',
          border: '1px solid var(--red-border)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-card)',
          padding: '32px 28px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16, opacity: 0.6 }}>
          <AdminLogo />
        </div>

        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            background: 'var(--red-bg)',
            border: '1px solid var(--red-border)',
            borderRadius: 99,
            padding: '4px 12px',
            marginBottom: 16,
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--red)' }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--red)' }}>Access Denied</span>
        </div>

        <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>
          Access Denied
        </div>
        <div style={{ fontSize: 13, color: 'var(--text2)', lineHeight: 1.5, marginBottom: user?.email ? 6 : 24 }}>
          Your account does not have permission to access the Admin Portal.
        </div>
        {user?.email && (
          <div style={{ fontSize: 12, color: 'var(--muted)', fontFamily: 'var(--mono)', marginBottom: 24 }}>
            Signed in as {user.email}
          </div>
        )}

        <button
          type="button"
          onClick={onSignOut}
          style={{
            width: '100%',
            fontSize: 13,
            fontWeight: 600,
            padding: '9px 15px',
            border: '1px solid var(--border)',
            borderRadius: 8,
            background: 'transparent',
            color: 'var(--text2)',
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
