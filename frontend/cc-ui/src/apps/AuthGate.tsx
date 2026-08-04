import { useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import { getToken, logout, ensureSession, UNAUTHORIZED_EVENT } from '../auth'
import type { SessionUser } from '../auth'
import LoginScreen from '../components/LoginScreen'
import AccessDenied from '../components/AccessDenied'

type AuthState = 'resolving' | 'anonymous' | 'denied' | 'admin'

interface Props {
  /** Evaluated once a session resolves (and again after a fresh login) to
   * decide whether this build's audience check passes. AdminApp and
   * ControlApp each pass their own -- this module doesn't know or care
   * which. */
  hasAccess: () => boolean
  children: ReactNode
}

/**
 * Admin Console dual build architecture: the session/auth-gate state
 * machine (resolving -> anonymous -> denied -> authorized), extracted
 * unchanged from the pre-split App.tsx so AdminApp and ControlApp share
 * one implementation instead of each reimplementing it. Behavior is
 * identical to what App.tsx did before this PR -- this is a relocation,
 * not a rewrite.
 *
 * The build split (which app bundle a request even reaches) is a
 * deployment/UX concern only -- this component, like everything it reads
 * from ../auth, is exactly the same authorization check either build
 * runs. The actual security boundary remains the backend's
 * require_permission/require_admin checks, unchanged by this PR.
 */
export default function AuthGate({ hasAccess, children }: Props) {
  const [state, setState] = useState<AuthState>('resolving')
  const [user, setUser] = useState<SessionUser | null>(null)

  const resolve = useCallback(async () => {
    if (!getToken()) {
      setState('anonymous')
      return
    }
    const resolved = await ensureSession()
    setUser(resolved)
    setState(resolved && hasAccess() ? 'admin' : resolved ? 'denied' : 'anonymous')
  }, [hasAccess])

  useEffect(() => {
    resolve()
  }, [resolve])

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null)
      setState('anonymous')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  if (state === 'resolving') {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg)', color: 'var(--muted)', fontFamily: 'var(--mono)', fontSize: 13,
      }}>
        Authenticating…
      </div>
    )
  }

  if (state === 'anonymous') {
    return (
      <LoginScreen
        onSuccess={(loggedInUser) => {
          setUser(loggedInUser)
          setState(loggedInUser && hasAccess() ? 'admin' : loggedInUser ? 'denied' : 'anonymous')
        }}
      />
    )
  }

  if (state === 'denied') {
    return (
      <AccessDenied
        user={user}
        onSignOut={() => {
          // SSO Phase 2 PR5: logout() also revokes the refresh token and
          // blacklists the access token server-side (POST /auth/logout)
          // before doing the same local clear this already did --
          // fire-and-forget, matches workbench's own sign-out.
          void logout()
          setUser(null)
          setState('anonymous')
        }}
      />
    )
  }

  return <>{children}</>
}
