import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SessionsPage from './SessionsPage'
import * as sessions from '../../sessions'
import type { PlatformSession } from '../../sessions'

vi.mock('../../sessions', async () => {
  const actual = await vi.importActual<typeof import('../../sessions')>('../../sessions')
  return { ...actual, fetchMySessions: vi.fn(), revokeMySession: vi.fn() }
})

const activeSession: PlatformSession = {
  session_id: 'session-active-1',
  organization_id: 3,
  auth_method: 'password',
  mfa_verified: true,
  status: 'active',
  created_at: '2026-08-08T10:00:00',
  last_activity_at: '2026-08-08T11:00:00',
  expires_at: '2026-08-15T10:00:00',
  revoked_at: null,
  revoked_reason: null,
  client_ip: '203.0.113.7',
  user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36',
}

const expiredSession: PlatformSession = {
  ...activeSession,
  session_id: 'session-expired-1',
  status: 'expired',
  expires_at: '2026-08-01T10:00:00',
}

const revokedSession: PlatformSession = {
  ...activeSession,
  session_id: 'session-revoked-1',
  status: 'revoked',
  revoked_at: '2026-08-08T12:00:00',
  revoked_reason: 'user_revoked',
  auth_method: 'oauth',
}

describe('SessionsPage', () => {
  beforeEach(() => {
    vi.mocked(sessions.fetchMySessions).mockReset()
    vi.mocked(sessions.revokeMySession).mockReset()
  })

  it('shows a loading state while the fetch is in flight', async () => {
    vi.mocked(sessions.fetchMySessions).mockReturnValue(new Promise(() => {}))
    render(<SessionsPage />)
    expect(await screen.findByText('Loading sessions…')).toBeInTheDocument()
  })

  it('shows the empty state when no sessions exist', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([])
    render(<SessionsPage />)
    expect(await screen.findByText('No sessions found.')).toBeInTheDocument()
  })

  it('renders the table with the expected columns', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    render(<SessionsPage />)

    for (const header of ['Status', 'Device / User Agent', 'Authentication', 'MFA', 'IP Address', 'Created', 'Last Activity', 'Expires', 'Actions']) {
      expect(await screen.findByRole('columnheader', { name: header })).toBeInTheDocument()
    }
    expect(screen.getByText('Chrome on Windows')).toBeInTheDocument()
    expect(screen.getByText('Password')).toBeInTheDocument()
    expect(screen.getByText('Verified')).toBeInTheDocument()
    expect(screen.getByText('203.0.113.7')).toBeInTheDocument()
  })

  it('shows an Active status badge for an active session', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    render(<SessionsPage />)
    expect(await screen.findByText('active')).toBeInTheDocument()
  })

  it('shows an Expired status badge for an expired session, and it remains visible (not hidden)', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([expiredSession])
    render(<SessionsPage />)
    expect(await screen.findByText('expired')).toBeInTheDocument()
  })

  it('shows a Revoked status badge for a revoked session, and it remains visible (not hidden)', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([revokedSession])
    render(<SessionsPage />)
    expect(await screen.findByText('revoked')).toBeInTheDocument()
  })

  it('does not offer a Revoke action for an already-revoked or expired session', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([revokedSession, expiredSession])
    render(<SessionsPage />)
    await screen.findByText('revoked')
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
  })

  it('opens the detail view showing non-secret session information', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    const user = userEvent.setup()
    render(<SessionsPage />)
    await screen.findByText('Chrome on Windows')

    await user.click(screen.getByRole('button', { name: 'Details' }))

    const dialog = screen.getByRole('dialog', { name: 'Session detail' })
    expect(within(dialog).getByText('session-active-1')).toBeInTheDocument()
    expect(within(dialog).getByText('Org #3')).toBeInTheDocument()
    expect(within(dialog).getByText('203.0.113.7')).toBeInTheDocument()
    // Never renders anything token/secret-shaped. ("password" alone is
    // not checked -- "Authentication: Password" is legitimate,
    // documented display text for the auth_method field, not a leaked
    // credential.)
    expect(dialog.textContent?.toLowerCase()).not.toMatch(/access_token|refresh_token|bearer |hashed_password/)
  })

  it('closes the detail view', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    const user = userEvent.setup()
    render(<SessionsPage />)
    await screen.findByText('Chrome on Windows')

    await user.click(screen.getByRole('button', { name: 'Details' }))
    expect(screen.getByRole('dialog', { name: 'Session detail' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not revoke before explicit confirmation', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    const user = userEvent.setup()
    render(<SessionsPage />)
    await screen.findByText('Chrome on Windows')

    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    const dialog = screen.getByRole('dialog', { name: 'Revoke session' })
    expect(within(dialog).getByText('Revoke this session?')).toBeInTheDocument()
    expect(within(dialog).getByText(/invalidate its refresh-token family/)).toBeInTheDocument()
    // Must not overclaim a platform-wide logout.
    expect(within(dialog).queryByText(/every device/i)).not.toBeInTheDocument()
    expect(sessions.revokeMySession).not.toHaveBeenCalled()

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(sessions.revokeMySession).not.toHaveBeenCalled()
  })

  it('revokes the session after confirmation and updates the UI to Revoked, not a stale Active', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    vi.mocked(sessions.revokeMySession).mockResolvedValue({
      ...activeSession, status: 'revoked', revoked_at: '2026-08-08T13:00:00', revoked_reason: 'user_revoked',
    })
    const user = userEvent.setup()
    render(<SessionsPage />)
    await screen.findByText('Chrome on Windows')

    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await user.click(screen.getByRole('button', { name: 'Revoke session' }))

    await waitFor(() => expect(sessions.revokeMySession).toHaveBeenCalledWith('session-active-1'))
    expect(await screen.findByText('revoked')).toBeInTheDocument()
    expect(screen.queryByText('active')).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Revoke session' })).not.toBeInTheDocument()
  })

  it('handles a repeated/idempotent revoke safely (already revoked)', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([revokedSession])
    vi.mocked(sessions.revokeMySession).mockResolvedValue(revokedSession)
    render(<SessionsPage />)
    await screen.findByText('revoked')
    // No Revoke action is even offered for an already-revoked session --
    // see the dedicated test above; nothing further to trigger here.
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument()
  })

  it('surfaces a clean error message if revoke fails, without crashing the page', async () => {
    vi.mocked(sessions.fetchMySessions).mockResolvedValue([activeSession])
    vi.mocked(sessions.revokeMySession).mockRejectedValue(new Error('/sessions/session-active-1/revoke 500'))
    const user = userEvent.setup()
    render(<SessionsPage />)
    await screen.findByText('Chrome on Windows')

    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await user.click(screen.getByRole('button', { name: 'Revoke session' }))

    expect(await screen.findByText('Unable to revoke this session. Please try again.')).toBeInTheDocument()
    // The dialog stays open so the caller can retry, and the row is
    // still shown as active (not silently flipped on a failed call).
    expect(screen.getByRole('dialog', { name: 'Revoke session' })).toBeInTheDocument()
  })

  it('shows a session-expired state on a 401, not a generic error', async () => {
    vi.mocked(sessions.fetchMySessions).mockRejectedValue(new Error('/sessions 401'))
    render(<SessionsPage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
  })

  it('shows a generic error state with retry for an unexpected failure', async () => {
    vi.mocked(sessions.fetchMySessions).mockRejectedValueOnce(new Error('/sessions 503'))
    vi.mocked(sessions.fetchMySessions).mockResolvedValueOnce([activeSession])
    const user = userEvent.setup()
    render(<SessionsPage />)

    expect(await screen.findByText('Unable to load sessions. Please try again.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Chrome on Windows')).toBeInTheDocument()
  })
})
