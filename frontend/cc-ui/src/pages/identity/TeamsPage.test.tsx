import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TeamsPage from './TeamsPage'
import * as auth from '../../auth'
import * as organizations from '../../organizations'
import type { MyOrg, PlatformOrgListResponse } from '../../organizations'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn(), fetchMyOrgs: vi.fn() }
})

// TeamsCard already has its own full test coverage via
// OrganizationDetailPage.test.tsx (create/delete/edit-members, graceful
// hiding on a 403) -- this page's tests only need to prove it receives
// the right orgId as the organization selection changes, not re-prove
// TeamsCard's own behavior.
vi.mock('../../components/teams/TeamsCard', () => ({
  default: ({ orgId }: { orgId: number }) => <div data-testid="TeamsCard" data-org-id={orgId} />,
}))

const platformOrgs = (): PlatformOrgListResponse => ({
  items: [
    { id: 1, name: 'Acme Corp', status: 'active', created_at: '2026-07-15T10:00:00', owner_email: null, member_count: 1, team_count: 1, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false },
    { id: 2, name: 'Beta Labs', status: 'active', created_at: '2026-07-16T10:00:00', owner_email: null, member_count: 1, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false },
  ],
  total: 2, page: 1, page_size: 100, total_pages: 1,
})

const myOrgs = (): MyOrg[] => [
  { id: 9, slug: 'my-org', name: 'My Org', plan: 'beta', status: 'active', status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
]

describe('TeamsPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset()
    vi.mocked(organizations.fetchMyOrgs).mockReset()
  })

  // ── Permission visibility: which endpoint populates the org selector ──

  it('loads organizations via the platform-admin endpoint for a platform admin', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    render(<TeamsPage />)

    expect(await screen.findByTestId('TeamsCard')).toHaveAttribute('data-org-id', '1')
    expect(organizations.fetchPlatformOrgs).toHaveBeenCalled()
    expect(organizations.fetchMyOrgs).not.toHaveBeenCalled()
  })

  it('loads organizations via the org-scoped endpoint for a non-platform-admin viewer', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue(myOrgs())
    render(<TeamsPage />)

    expect(await screen.findByTestId('TeamsCard')).toHaveAttribute('data-org-id', '9')
    expect(organizations.fetchMyOrgs).toHaveBeenCalled()
    expect(organizations.fetchPlatformOrgs).not.toHaveBeenCalled()
  })

  // ── Loading / empty / error states ─────────────────────────────────────

  it('shows the loading state before organizations resolve', () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockReturnValue(new Promise(() => {}))
    render(<TeamsPage />)
    expect(screen.getByText(/Loading organizations/)).toBeInTheDocument()
  })

  it('shows the empty state when the viewer belongs to no organizations', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([])
    render(<TeamsPage />)
    expect(await screen.findByText("You don't belong to any organization yet.")).toBeInTheDocument()
  })

  it('shows an error state when the organization list request fails', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockRejectedValue(new Error('/platform/orgs 500'))
    render(<TeamsPage />)
    expect(await screen.findByText(/platform\/orgs 500/)).toBeInTheDocument()
  })

  // PR E2: this page's ErrorState previously omitted onRetry, unlike
  // every other page in this app that classifies/reports an error.
  it('offers a retry action that re-fetches the organization list', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockRejectedValueOnce(new Error('/platform/orgs 500'))
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValueOnce(platformOrgs())
    const user = userEvent.setup()
    render(<TeamsPage />)
    await screen.findByText(/platform\/orgs 500/)

    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByLabelText('Select organization')).toBeInTheDocument())
  })

  // ── Organization selection ─────────────────────────────────────────────

  it('lets the administrator switch organizations, re-scoping TeamsCard', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    render(<TeamsPage />)

    await screen.findByTestId('TeamsCard')
    await user.selectOptions(screen.getByLabelText('Select organization'), '2')

    expect(await screen.findByTestId('TeamsCard')).toHaveAttribute('data-org-id', '2')
  })

  it('pre-selects the organization passed via initialOrgId', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    render(<TeamsPage initialOrgId={2} />)

    expect(await screen.findByTestId('TeamsCard')).toHaveAttribute('data-org-id', '2')
  })

  it('falls back to the first organization when initialOrgId is not among the loaded orgs', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    render(<TeamsPage initialOrgId={999} />)

    await waitFor(() => expect(screen.getByTestId('TeamsCard')).toHaveAttribute('data-org-id', '1'))
  })
})
