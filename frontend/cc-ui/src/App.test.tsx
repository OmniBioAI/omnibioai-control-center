import { act, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import App from './App'
import * as auth from './auth'
import type { SessionUser } from './auth'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return {
    ...actual,
    getToken: vi.fn(),
    clearToken: vi.fn(),
    ensureSession: vi.fn(),
    hasAdminAccess: vi.fn(),
    // Phase 3 PR2: explicitly mocked (not left to the real
    // implementation's internal cachedUser, which ensureSession's mock
    // never populates) so tests below can independently control "can
    // this session see the Organizations tab" from "can it see the ops
    // tabs" -- the whole point of the widened gate this PR introduces.
    hasOrganizationsAccess: vi.fn(),
    // Phase 3 PR3A: same reasoning as hasOrganizationsAccess above --
    // explicitly mocked so tests can control Users-tab visibility
    // (platform_admin only) independently of the broader Organizations
    // gate and the ops-tabs gate.
    hasPlatformAdminAccess: vi.fn(),
  }
})

vi.mock('./api', () => ({
  fetchSummary: vi.fn().mockResolvedValue({ overall_status: 'UP' }),
  fetchReportStatus: vi.fn().mockResolvedValue({ report_exists: false, status: 'idle' }),
  triggerGenerate: vi.fn(),
}))

// Dashboard's page components do their own network fetching / chart
// rendering (recharts needs a ResizeObserver jsdom doesn't provide) --
// irrelevant to what this file is testing, which is the auth gate above
// Dashboard, not Dashboard's contents. vi.mock calls are hoisted above
// this module's own code, so each target must be a static string literal
// (no loop over a runtime array of names).
vi.mock('./pages/HealthPage', () => ({ default: () => <div data-testid="HealthPage" /> }))
vi.mock('./pages/DockerPage', () => ({ default: () => <div data-testid="DockerPage" /> }))
vi.mock('./pages/EcosystemPage', () => ({ default: () => <div data-testid="EcosystemPage" /> }))
vi.mock('./pages/ConfigPage', () => ({ default: () => <div data-testid="ConfigPage" /> }))
vi.mock('./pages/LlmPage', () => ({ default: () => <div data-testid="LlmPage" /> }))
vi.mock('./pages/CloudPage', () => ({ default: () => <div data-testid="CloudPage" /> }))
vi.mock('./pages/OrganizationsPage', () => ({ default: () => <div data-testid="OrganizationsPage" /> }))
vi.mock('./pages/OrganizationDetailPage', () => ({
  default: ({ orgId }: { orgId: number }) => <div data-testid="OrganizationDetailPage" data-org-id={orgId} />,
}))
vi.mock('./pages/UsersPage', () => ({ default: () => <div data-testid="UsersPage" /> }))
vi.mock('./pages/UserDetailPage', () => ({
  default: ({ userId }: { userId: number }) => <div data-testid="UserDetailPage" data-user-id={userId} />,
}))

const admin: SessionUser = {
  userId: '1', email: 'admin@omnibioai.org', roles: ['admin'],
  permissions: ['manage_config'], orgId: null, orgRoles: [], schemaVersion: 2,
}
const nonAdmin: SessionUser = {
  userId: '2', email: 'no-perms@omnibioai.org', roles: ['user'],
  permissions: [], orgId: null, orgRoles: [], schemaVersion: 2,
}

describe('App auth gate', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    vi.mocked(auth.ensureSession).mockReset()
    vi.mocked(auth.hasAdminAccess).mockReset()
    vi.mocked(auth.hasOrganizationsAccess).mockReset()
    vi.mocked(auth.hasPlatformAdminAccess).mockReset()
    window.history.pushState(null, '', '/')
  })

  it('shows the login screen when there is no token', async () => {
    vi.mocked(auth.getToken).mockReturnValue(null)
    render(<App />)
    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  it('shows Access Denied for an authenticated non-admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-123')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)

    render(<App />)
    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
    expect(screen.getByText(/no-perms@omnibioai\.org/)).toBeInTheDocument()
  })

  it('renders the dashboard for an authenticated admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<App />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
  })

  it('drops back to the login screen when a gated request reports 401', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-789')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<App />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())

    act(() => {
      window.dispatchEvent(new Event(auth.UNAUTHORIZED_EVENT))
    })

    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  // ── Phase 3 PR2: the widened gate + deep linking ──────────────────────────

  const orgOnlyUser: SessionUser = {
    userId: '3', email: 'org-admin@acme.test', roles: ['user'],
    permissions: ['manage_org'], orgId: '9', orgRoles: ['org_admin'], schemaVersion: 2,
  }

  it('grants console access to an org-only user with no global admin role', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-org')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<App />)

    expect(await screen.findByTestId('OrganizationsPage')).toBeInTheDocument()
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
    // The ops pages must never render for this audience -- they were
    // never authorized to see them, only Organizations.
    expect(screen.queryByTestId('HealthPage')).not.toBeInTheDocument()
  })

  it('still denies a user with neither admin nor organizational access', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-none')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(false)

    render(<App />)

    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
  })

  it('deep-links directly to an organization detail page on initial load', async () => {
    window.history.pushState(null, '', '/organizations/42')
    vi.mocked(auth.getToken).mockReturnValue('token-admin')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<App />)

    const detail = await screen.findByTestId('OrganizationDetailPage')
    expect(detail.getAttribute('data-org-id')).toBe('42')
    expect(screen.queryByTestId('OrganizationsPage')).not.toBeInTheDocument()
    expect(screen.queryByTestId('HealthPage')).not.toBeInTheDocument()
  })

  it('deep-links to the organizations list (no id) on initial load', async () => {
    window.history.pushState(null, '', '/organizations')
    vi.mocked(auth.getToken).mockReturnValue('token-admin2')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<App />)

    expect(await screen.findByTestId('OrganizationsPage')).toBeInTheDocument()
    expect(screen.queryByTestId('OrganizationDetailPage')).not.toBeInTheDocument()
  })

  // ── Phase 3 PR3A: Users tab (platform-admin only) + deep linking ──────────

  it('shows the Users tab for a platform admin, even with no global admin role', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-pa')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)

    render(<App />)

    expect(await screen.findByText('Users')).toBeInTheDocument()
  })

  it('hides the Users tab for an org-only user who is not a platform admin', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-org2')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)

    render(<App />)

    await screen.findByTestId('OrganizationsPage')
    expect(screen.queryByText('Users')).not.toBeInTheDocument()
  })

  it('deep-links directly to a user detail page on initial load', async () => {
    window.history.pushState(null, '', '/users/17')
    vi.mocked(auth.getToken).mockReturnValue('token-admin3')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)

    render(<App />)

    const detail = await screen.findByTestId('UserDetailPage')
    expect(detail.getAttribute('data-user-id')).toBe('17')
    expect(screen.queryByTestId('UsersPage')).not.toBeInTheDocument()
    expect(screen.queryByTestId('HealthPage')).not.toBeInTheDocument()
  })

  it('deep-links to the users list (no id) on initial load', async () => {
    window.history.pushState(null, '', '/users')
    vi.mocked(auth.getToken).mockReturnValue('token-admin4')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)

    render(<App />)

    expect(await screen.findByTestId('UsersPage')).toBeInTheDocument()
    expect(screen.queryByTestId('UserDetailPage')).not.toBeInTheDocument()
  })
})
