import { useEffect, useState } from 'react'
import {
  fetchMySessions, revokeMySession, formatAuthMethod, formatUserAgent,
  type PlatformSession,
} from '../../sessions'
import {
  Card, SectionHeader, LoadingState, ErrorState, ActionToolbar, Button, DataTable, SessionExpiredState,
} from '../../components/ui'
import StatusBadge from '../../components/StatusBadge'
import { formatDate, classifyAuthError } from '../../format'

// PR-C (Control Center Sessions Integration). Reads omnibioai-auth's
// self-service /sessions endpoints (Phase 4 PR-A) via
// routes_sessions_proxy.py -- every session shown here already belongs
// to the caller; there is no organization/platform-wide session
// administration in this page (see this PR's own scope notes), so
// unlike AuditLogsPage there is no org/actor filter bar and no
// pagination -- a device list is small by nature.
//
// "Current session" is deliberately NOT indicated anywhere on this page:
// PR-A's SessionOut has no field correlating back to the access token
// the browser is using right now (the JWT itself carries no
// session_id/family_id claim -- confirmed by reading both the token
// payload shape and SessionOut directly), and guessing from IP/user-
// agent/recency would be exactly the invented heuristic this PR was
// told not to build. See this PR's own implementation report.

// ── Detail modal -- same page-local Modal shape AuditLogsPage.tsx's
// EventDetailModal / ServiceAccountsPage.tsx's Modal already established
// (no shared components/ui modal exists to reuse). ──────────────────────
function SessionDetailModal({ session, onClose }: { session: PlatformSession; onClose: () => void }) {
  return (
    <div
      role="dialog"
      aria-label="Session detail"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 480, maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>Session detail</span>
          <button onClick={onClose} aria-label="Close" style={{ fontSize: 18, color: 'var(--muted)', lineHeight: 1, cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14 }}>
          <Field title="Session ID"><code style={{ fontSize: 11 }}>{session.session_id}</code></Field>
          <Field title="Status"><StatusBadge status={session.status} /></Field>
          <Field title="Authentication">{formatAuthMethod(session.auth_method)}</Field>
          <Field title="MFA verified">{session.mfa_verified ? 'Yes' : 'No'}</Field>
          <Field title="Organization">{session.organization_id != null ? `Org #${session.organization_id}` : '—'}</Field>
          <Field title="Client IP">{session.client_ip ?? '—'}</Field>
          <Field title="User agent"><span style={{ wordBreak: 'break-word' }}>{session.user_agent ?? '—'}</span></Field>
          <Field title="Created">{formatDate(session.created_at)}</Field>
          <Field title="Last activity">{formatDate(session.last_activity_at)}</Field>
          <Field title="Expires">{formatDate(session.expires_at)}</Field>
          {session.revoked_at && <Field title="Revoked at">{formatDate(session.revoked_at)}</Field>}
          {session.revoked_reason && <Field title="Revocation reason">{session.revoked_reason}</Field>}
        </div>
      </div>
    </div>
  )
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 13, color: 'var(--text)' }}>{children}</div>
    </div>
  )
}

// ── Revoke confirmation -- a small dialog (not the inline two-button
// toggle ServiceAccountsPage.tsx's RevokeAction uses) because this
// action needs real explanatory copy: revoking a session is scoped to
// that one session only, and the task this PR implements explicitly
// warns against implying a "log out everywhere" effect that doesn't
// exist yet (that's a separate, not-yet-built capability -- see PR-A's
// own report). ───────────────────────────────────────────────────────
function RevokeConfirmModal({ onConfirm, onClose }: { onConfirm: () => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleConfirm = async () => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
    } catch (e: unknown) {
      setError('Unable to revoke this session. Please try again.')
      setBusy(false)
      void e
    }
  }

  return (
    <div
      role="dialog"
      aria-label="Revoke session"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget && !busy) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '22px 24px', width: 420, maxWidth: '90vw', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)', marginBottom: 10 }}>
          Revoke this session?
        </div>
        <p style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 4 }}>
          This will sign out this session and invalidate its refresh-token family.
        </p>
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 18 }}>
          Only this session is affected -- your other sessions stay signed in.
        </p>
        {error && <p style={{ fontSize: 12, color: 'var(--red)', marginBottom: 14 }}>{error}</p>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button
            onClick={handleConfirm}
            disabled={busy}
            style={{ background: 'var(--red)', color: '#fff', border: 'none' }}
          >
            {busy ? 'Revoking…' : 'Revoke session'}
          </Button>
        </div>
      </div>
    </div>
  )
}

type LoadState =
  | { status: 'loading' }
  | { status: 'session' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: PlatformSession[] }

export default function SessionsPage() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [selected, setSelected] = useState<PlatformSession | null>(null)
  const [revoking, setRevoking] = useState<PlatformSession | null>(null)

  const load = () => {
    setState({ status: 'loading' })
    fetchMySessions()
      .then(items => setState({ status: 'ready', items }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (classifyAuthError(message) === 'session') setState({ status: 'session' })
        else setState({ status: 'error', message: 'Unable to load sessions. Please try again.' })
      })
  }

  useEffect(load, [])

  const handleRevoke = async (session: PlatformSession) => {
    const updated = await revokeMySession(session.session_id)
    // Patch the row in place from the response rather than re-fetching
    // the whole list -- avoids a visible flash back to a loading state
    // for what is, from the caller's point of view, a single-row
    // update; also makes the idempotent-revoke case (row already
    // 'revoked') a no-op re-render with the same data, not a spinner.
    setState(prev => prev.status === 'ready'
      ? { status: 'ready', items: prev.items.map(s => s.session_id === updated.session_id ? updated : s) }
      : prev)
    setRevoking(null)
  }

  if (state.status === 'session') return <SessionExpiredState />

  return (
    <div>
      <SectionHeader
        title="Sessions"
        description="Your active and past login sessions across devices. Revoking a session signs it out and invalidates its refresh-token family."
        actions={
          <ActionToolbar>
            <Button variant="secondary" onClick={load} disabled={state.status === 'loading'}>Refresh</Button>
          </ActionToolbar>
        }
      />

      {state.status === 'loading' && <LoadingState label="Loading sessions…" />}
      {state.status === 'error' && <ErrorState message={state.message} onRetry={load} />}

      {state.status === 'ready' && (
        <Card>
          <DataTable
            rowKey={s => s.session_id}
            emptyLabel="No sessions found."
            rows={state.items}
            columns={[
              { key: 'status', header: 'Status', render: s => <StatusBadge status={s.status} /> },
              { key: 'device', header: 'Device / User Agent', render: s => formatUserAgent(s.user_agent) },
              { key: 'auth', header: 'Authentication', render: s => formatAuthMethod(s.auth_method) },
              { key: 'mfa', header: 'MFA', render: s => s.mfa_verified ? 'Verified' : '—' },
              { key: 'ip', header: 'IP Address', render: s => s.client_ip ?? '—' },
              { key: 'created', header: 'Created', render: s => formatDate(s.created_at) },
              { key: 'last-activity', header: 'Last Activity', render: s => formatDate(s.last_activity_at) },
              { key: 'expires', header: 'Expires', render: s => formatDate(s.expires_at) },
              {
                key: 'actions', header: 'Actions', render: s => (
                  <span style={{ display: 'inline-flex', gap: 12, alignItems: 'center' }}>
                    <button
                      onClick={() => setSelected(s)}
                      style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    >
                      Details
                    </button>
                    {s.status === 'active' && (
                      <button
                        onClick={() => setRevoking(s)}
                        style={{ fontSize: 12, fontWeight: 600, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      >
                        Revoke
                      </button>
                    )}
                  </span>
                ),
              },
            ]}
          />
        </Card>
      )}

      {selected && <SessionDetailModal session={selected} onClose={() => setSelected(null)} />}
      {revoking && (
        <RevokeConfirmModal
          onConfirm={() => handleRevoke(revoking)}
          onClose={() => setRevoking(null)}
        />
      )}
    </div>
  )
}
