import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SecurityDashboardPage from './SecurityDashboardPage'
import * as users from '../../users'
import type { PlatformUserSummary } from '../../users'
import * as organizations from '../../organizations'
import type { PlatformOrgSummary } from '../../organizations'
import * as audit from '../../audit'
import type { AuditEvent } from '../../audit'

vi.mock('../../users', async () => {
  const actual = await vi.importActual<typeof import('../../users')>('../../users')
  return { ...actual, fetchPlatformUsers: vi.fn() }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

vi.mock('../../audit', async () => {
  const actual = await vi.importActual<typeof import('../../audit')>('../../audit')
  return { ...actual, fetchAuditEvents: vi.fn() }
})

const userRow = (overrides: Partial<PlatformUserSummary> = {}): PlatformUserSummary => ({
  id: 1, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [], org_count: 1, last_login_at: null, authentication_method: null,
  mfa_enabled: false, ...overrides,
})

const orgRow = (overrides: Partial<PlatformOrgSummary> = {}): PlatformOrgSummary => ({
  id: 1, name: 'Acme Corp', status: 'active', created_at: '2026-07-15T10:00:00',
  owner_email: 'owner@acme.test', member_count: 1, team_count: 0, api_key_count: 0,
  oauth_client_count: 0, license_count: 0, sso_enabled: false,
  mfa_policy_required: false, mfa_policy_configured: false, ...overrides,
})

const mfaEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1, event_type: 'mfa_enabled', actor_user_id: 1, actor_email: 'someone@acme.test',
  target_user_id: null, target_email: null, organization_id: null, organization_name: null,
  resource_type: null, resource_id: null, before_state: null, after_state: null,
  metadata: null, created_at: '2026-08-01T12:00:00', ...overrides,
})

function mockEmptyPages() {
  vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
    items: [], total: 0, page: 1, page_size: 100, total_pages: 0,
  })
  vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
    items: [], total: 0, page: 1, page_size: 100, total_pages: 0,
  })
  vi.mocked(audit.fetchAuditEvents).mockResolvedValue({
    items: [], total: 0, page: 1, page_size: 50, total_pages: 0,
  })
}

describe('SecurityDashboardPage', () => {
  beforeEach(() => {
    vi.mocked(users.fetchPlatformUsers).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset()
    vi.mocked(audit.fetchAuditEvents).mockReset()
  })

  it('shows a loading state while data is in flight', async () => {
    vi.mocked(users.fetchPlatformUsers).mockReturnValue(new Promise(() => {}))
    vi.mocked(organizations.fetchPlatformOrgs).mockReturnValue(new Promise(() => {}))
    vi.mocked(audit.fetchAuditEvents).mockReturnValue(new Promise(() => {}))
    render(<SecurityDashboardPage />)
    expect(await screen.findByText('Loading security overview…')).toBeInTheDocument()
  })

  it('shows the empty state when there are no users yet', async () => {
    mockEmptyPages()
    render(<SecurityDashboardPage />)
    expect(await screen.findByText('No users yet')).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403, not stale stats', async () => {
    vi.mocked(users.fetchPlatformUsers).mockRejectedValue(new Error('/platform/users 403'))
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, total_pages: 0 })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 })
    render(<SecurityDashboardPage />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(users.fetchPlatformUsers).mockRejectedValueOnce(new Error('/platform/users 500'))
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, total_pages: 0 })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 })
    render(<SecurityDashboardPage />)
    expect(await screen.findByText('Error')).toBeInTheDocument()

    mockEmptyPages()
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('No users yet')).toBeInTheDocument()
  })

  it('renders MFA adoption statistics computed from the users list', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow({ id: 1, mfa_enabled: true }), userRow({ id: 2, mfa_enabled: false }), userRow({ id: 3, mfa_enabled: false })],
      total: 3, page: 1, page_size: 100, total_pages: 1,
    })
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, total_pages: 0 })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 })

    render(<SecurityDashboardPage />)

    expect(await screen.findByText('MFA Adoption')).toBeInTheDocument()
    expect(screen.getByText('Total Users')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('MFA Enabled')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('MFA Disabled')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('Enrollment')).toBeInTheDocument()
    expect(screen.getByText('33%')).toBeInTheDocument()
  })

  it('renders organization policy statistics computed from the orgs list', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 100, total_pages: 1,
    })
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [
        orgRow({ id: 1, mfa_policy_required: true, mfa_policy_configured: true }),
        orgRow({ id: 2, mfa_policy_required: false, mfa_policy_configured: false }),
      ],
      total: 2, page: 1, page_size: 100, total_pages: 1,
    })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 })

    render(<SecurityDashboardPage />)

    expect(await screen.findByText('Organization Policies')).toBeInTheDocument()
    expect(screen.getByText('Organizations Requiring MFA')).toBeInTheDocument()
    expect(screen.getByText('Organizations Without a Policy')).toBeInTheDocument()
  })

  it('renders recent security events, filtered to MFA event types only', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({ items: [userRow()], total: 1, page: 1, page_size: 100, total_pages: 1 })
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, total_pages: 0 })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({
      items: [
        mfaEvent({ id: 1, event_type: 'mfa_enabled' }),
        mfaEvent({ id: 2, event_type: 'login_success' }),
        mfaEvent({ id: 3, event_type: 'mfa_policy_enabled' }),
      ],
      total: 3, page: 1, page_size: 50, total_pages: 1,
    })

    render(<SecurityDashboardPage />)

    expect(await screen.findByText('Recent Security Events')).toBeInTheDocument()
    expect(screen.getByText('Mfa Enabled')).toBeInTheDocument()
    expect(screen.getByText('Mfa Policy Enabled')).toBeInTheDocument()
    // login_success is not an MFA event type -- filtered out of this tile.
    expect(screen.queryByText('Login Success')).not.toBeInTheDocument()
  })

  it('walks every page of the users list to compute totals, not just the first page', async () => {
    vi.mocked(users.fetchPlatformUsers).mockImplementation(async ({ page } = {}) => {
      if (page === 1) return { items: [userRow({ id: 1, mfa_enabled: true })], total: 2, page: 1, page_size: 100, total_pages: 2 }
      return { items: [userRow({ id: 2, mfa_enabled: false })], total: 2, page: 2, page_size: 100, total_pages: 2 }
    })
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, total_pages: 0 })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 })

    render(<SecurityDashboardPage />)

    await waitFor(() => expect(users.fetchPlatformUsers).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('MFA Adoption')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
  })

  it('never renders a secret, recovery code, or token anywhere on this page', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({ items: [userRow({ mfa_enabled: true })], total: 1, page: 1, page_size: 100, total_pages: 1 })
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100, total_pages: 0 })
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue({
      items: [mfaEvent({ metadata: { reason: 'compliance rollout' } })],
      total: 1, page: 1, page_size: 50, total_pages: 1,
    })

    const { container } = render(<SecurityDashboardPage />)
    await screen.findByText('MFA Adoption')

    const text = container.textContent ?? ''
    expect(text).not.toMatch(/otpauth:\/\//i)
    expect(text).not.toMatch(/recovery.code.*[A-Z0-9]{4,}-[A-Z0-9]{4,}/i)
    expect(text).not.toMatch(/challenge_token/i)
  })
})
