import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AdminApp from './AdminApp'
import * as auth from '../auth'
import type { SessionUser } from '../auth'

// Admin Console Phase 2: this file is App.test.tsx / the pre-Phase-2
// AdminApp.test.tsx, updated for the new shell -- the auth-gate behavior
// itself (login/denied/401-drop/deep-linking) is unchanged and asserted
// exactly as before; what changed is (a) the default landing page is now
// Overview (DashboardPage, mocked below like every other page) instead
// of Health, an intentional Phase 2 behavior change, and (b) navigating
// to a page now means clicking a SidebarNav item instead of a Header
// tab -- same underlying handleNavigate, different UI to drive it.

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return {
    ...actual,
    getToken: vi.fn(),
    clearToken: vi.fn(),
    ensureSession: vi.fn(),
    getSessionUser: vi.fn(),
    hasAdminAccess: vi.fn(),
    hasOrganizationsAccess: vi.fn(),
    hasPlatformAdminAccess: vi.fn(),
  }
})

vi.mock('../api', () => ({
  fetchSummary: vi.fn().mockResolvedValue({ overall_status: 'UP', services: [] }),
  fetchReportStatus: vi.fn().mockResolvedValue({ report_exists: false, status: 'idle' }),
  triggerGenerate: vi.fn(),
}))

// Every page this shell can render is mocked, same rationale as before
// Phase 2: this file tests the auth gate + navigation shell, not each
// page's own contents. DashboardPage is mocked for the same reason --
// its real StatCard labels ("Users", "Organizations", ...) would
// otherwise collide with the nav-visibility assertions below.
vi.mock('../pages/DashboardPage', () => ({ default: () => <div data-testid="DashboardPage" /> }))
vi.mock('../pages/HealthPage', () => ({ default: () => <div data-testid="HealthPage" /> }))
vi.mock('../pages/DockerPage', () => ({ default: () => <div data-testid="DockerPage" /> }))
vi.mock('../pages/EcosystemPage', () => ({ default: () => <div data-testid="EcosystemPage" /> }))
vi.mock('../pages/ConfigPage', () => ({ default: () => <div data-testid="ConfigPage" /> }))
vi.mock('../pages/LlmPage', () => ({ default: () => <div data-testid="LlmPage" /> }))
vi.mock('../pages/CloudPage', () => ({ default: () => <div data-testid="CloudPage" /> }))
// OrganizationsPage's onSelect is exercised (not just its presence) --
// PR11.3 reuses this exact component as the org picker for the 'iam'
// destination too, so the mock exposes a button to drive that selection
// from either the 'organizations' or 'iam' routing tests below.
vi.mock('../pages/OrganizationsPage', () => ({
  default: ({ onSelect }: { onSelect: (id: number) => void }) => (
    <div data-testid="OrganizationsPage">
      <button onClick={() => onSelect(7)}>pick-org-7</button>
    </div>
  ),
}))
vi.mock('../pages/OrganizationDetailPage', () => ({
  default: ({ orgId, onViewTeams, onViewRoles, onManageSso }: {
    orgId: number
    onViewTeams?: (id: number) => void
    onViewRoles?: (id: number) => void
    onManageSso: (id: number) => void
  }) => (
    <div data-testid="OrganizationDetailPage" data-org-id={orgId}>
      {onViewTeams && <button onClick={() => onViewTeams(orgId)}>View all teams</button>}
      {onViewRoles && <button onClick={() => onViewRoles(orgId)}>View roles & permissions</button>}
      <button onClick={() => onManageSso(orgId)}>manage-sso-link</button>
    </div>
  ),
}))
vi.mock('../pages/UsersPage', () => ({ default: () => <div data-testid="UsersPage" /> }))
vi.mock('../pages/UserDetailPage', () => ({
  default: ({ userId }: { userId: number }) => <div data-testid="UserDetailPage" data-user-id={userId} />,
}))
// PR11.2: standalone Teams / Roles & Permissions pages -- mocked like
// every other page this shell can render (see this file's own module
// docstring); TeamsPage.test.tsx/RolesPage.test.tsx cover their real
// contents, this file only proves the shell reaches and gates them.
vi.mock('../pages/identity/TeamsPage', () => ({
  default: ({ initialOrgId }: { initialOrgId: number | null }) => <div data-testid="TeamsPage" data-initial-org-id={String(initialOrgId)} />,
}))
vi.mock('../pages/identity/RolesPage', () => ({
  default: ({ initialOrgId }: { initialOrgId: number | null }) => <div data-testid="RolesPage" data-initial-org-id={String(initialOrgId)} />,
}))
// PR11.3.
vi.mock('../pages/identity/SSOSettingsPage', () => ({
  default: ({ orgId }: { orgId: number }) => <div data-testid="SSOSettingsPage" data-org-id={orgId} />,
}))

const admin: SessionUser = {
  userId: '1', email: 'admin@omnibioai.org', roles: ['admin'],
  permissions: ['manage_config'], orgId: null, orgRoles: [], schemaVersion: 2,
}
const nonAdmin: SessionUser = {
  userId: '2', email: 'no-perms@omnibioai.org', roles: ['user'],
  permissions: [], orgId: null, orgRoles: [], schemaVersion: 2,
}
const orgOnlyUser: SessionUser = {
  userId: '3', email: 'org-admin@acme.test', roles: ['user'],
  permissions: ['manage_org'], orgId: '9', orgRoles: ['org_admin'], schemaVersion: 2,
}

/** Clicks a SidebarNav item by its visible label -- the click lands on
 * the label span, which bubbles to the enclosing nav button exactly as
 * a real user's click would. */
function clickNav(label: string) {
  fireEvent.click(screen.getByText(label))
}

describe('AdminApp auth gate', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    vi.mocked(auth.ensureSession).mockReset()
    vi.mocked(auth.getSessionUser).mockReset().mockReturnValue(null)
    vi.mocked(auth.hasAdminAccess).mockReset()
    vi.mocked(auth.hasOrganizationsAccess).mockReset()
    vi.mocked(auth.hasPlatformAdminAccess).mockReset()
    window.history.pushState(null, '', '/')
  })

  it('shows the login screen when there is no token', async () => {
    vi.mocked(auth.getToken).mockReturnValue(null)
    render(<AdminApp />)
    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  it('shows Access Denied for an authenticated non-admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-123')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(false)

    render(<AdminApp />)
    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
    expect(screen.getByText(/no-perms@omnibioai\.org/)).toBeInTheDocument()
  })

  it('renders the Overview dashboard by default for an authenticated admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
  })

  it('reaches Health via the sidebar (Operations > Infrastructure > Health)', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    clickNav('Health')

    expect(await screen.findByTestId('HealthPage')).toBeInTheDocument()
    expect(screen.queryByTestId('DashboardPage')).not.toBeInTheDocument()
  })

  it('drops back to the login screen when a gated request reports 401', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-789')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    act(() => {
      window.dispatchEvent(new Event(auth.UNAUTHORIZED_EVENT))
    })

    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  // ── Phase 3 PR2: the widened gate + deep linking ──────────────────────────

  it('grants console access to an org-only user with no global admin role', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-org')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.getSessionUser).mockReturnValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)

    // Overview by default (no ops-page assumption for this audience).
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()

    // Organizations is reachable via the sidebar...
    clickNav('Organizations')
    expect(await screen.findByTestId('OrganizationsPage')).toBeInTheDocument()

    // ...but no Infrastructure/ops section is offered to this audience at all.
    expect(screen.queryByText('Infrastructure')).not.toBeInTheDocument()
    expect(screen.queryByText('Health')).not.toBeInTheDocument()
  })

  it('still denies a user with neither admin nor organizational access', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-none')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(false)

    render(<AdminApp />)

    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
  })

  it('deep-links directly to an organization detail page on initial load', async () => {
    window.history.pushState(null, '', '/organizations/42')
    vi.mocked(auth.getToken).mockReturnValue('token-admin')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)

    const detail = await screen.findByTestId('OrganizationDetailPage')
    expect(detail.getAttribute('data-org-id')).toBe('42')
    expect(screen.queryByTestId('OrganizationsPage')).not.toBeInTheDocument()
    expect(screen.queryByTestId('DashboardPage')).not.toBeInTheDocument()
  })

  it('deep-links to the organizations list (no id) on initial load', async () => {
    window.history.pushState(null, '', '/organizations')
    vi.mocked(auth.getToken).mockReturnValue('token-admin2')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)

    expect(await screen.findByTestId('OrganizationsPage')).toBeInTheDocument()
    expect(screen.queryByTestId('OrganizationDetailPage')).not.toBeInTheDocument()
  })

  // ── Phase 3 PR3A: Users nav item (platform-admin only) + deep linking ─────

  it('shows the Users nav item for a platform admin, even with no global admin role', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-pa')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.getSessionUser).mockReturnValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    expect(screen.getByText('Users')).toBeInTheDocument()
  })

  it('hides the Users nav item for an org-only user who is not a platform admin', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-org2')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.getSessionUser).mockReturnValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    expect(screen.queryByText('Users')).not.toBeInTheDocument()
  })

  it('deep-links directly to a user detail page on initial load', async () => {
    window.history.pushState(null, '', '/users/17')
    vi.mocked(auth.getToken).mockReturnValue('token-admin3')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)

    render(<AdminApp />)

    const detail = await screen.findByTestId('UserDetailPage')
    expect(detail.getAttribute('data-user-id')).toBe('17')
    expect(screen.queryByTestId('UsersPage')).not.toBeInTheDocument()
    expect(screen.queryByTestId('DashboardPage')).not.toBeInTheDocument()
  })

  it('deep-links to the users list (no id) on initial load', async () => {
    window.history.pushState(null, '', '/users')
    vi.mocked(auth.getToken).mockReturnValue('token-admin4')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)

    render(<AdminApp />)

    expect(await screen.findByTestId('UsersPage')).toBeInTheDocument()
    expect(screen.queryByTestId('UserDetailPage')).not.toBeInTheDocument()
  })

  // ── Phase 2: new shell-specific coverage ──────────────────────────────────

  it('renders Coming Soon for an unimplemented module (e.g. Billing)', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-admin5')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    clickNav('Billing')

    expect(await screen.findByText('Coming soon')).toBeInTheDocument()
  })

  // ── PR11.3: IAM / SSO Management nav item + routing ────────────────────

  it('shows "IAM / SSO Management" as a real nav destination, not Coming Soon', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-iam1')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    clickNav('IAM / SSO Management')

    expect(await screen.findByTestId('OrganizationsPage')).toBeInTheDocument()
    expect(screen.queryByText('Coming soon')).not.toBeInTheDocument()
  })

  it('hides the IAM / SSO Management nav item for a user with no organizational access', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-iam2')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.getSessionUser).mockReturnValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(false)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    expect(screen.queryByText('IAM / SSO Management')).not.toBeInTheDocument()
  })

  it('reuses the Organizations picker to select an org, then reaches SSOSettingsPage for it', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-iam3')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    clickNav('IAM / SSO Management')
    await screen.findByTestId('OrganizationsPage')
    fireEvent.click(screen.getByText('pick-org-7'))

    const settings = await screen.findByTestId('SSOSettingsPage')
    expect(settings.getAttribute('data-org-id')).toBe('7')
    expect(screen.queryByTestId('OrganizationsPage')).not.toBeInTheDocument()
  })

  it('deep-links directly to a specific organization\'s SSO settings on initial load', async () => {
    window.history.pushState(null, '', '/iam/9')
    vi.mocked(auth.getToken).mockReturnValue('token-iam4')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)

    const settings = await screen.findByTestId('SSOSettingsPage')
    expect(settings.getAttribute('data-org-id')).toBe('9')
    expect(screen.queryByTestId('OrganizationsPage')).not.toBeInTheDocument()
  })

  it('deep-links to the org picker (no id) on initial load', async () => {
    window.history.pushState(null, '', '/iam')
    vi.mocked(auth.getToken).mockReturnValue('token-iam5')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)

    expect(await screen.findByTestId('OrganizationsPage')).toBeInTheDocument()
    expect(screen.queryByTestId('SSOSettingsPage')).not.toBeInTheDocument()
  })

  it('navigates straight from an organization\'s detail page to its SSO settings via Manage SSO Settings', async () => {
    window.history.pushState(null, '', '/organizations/42')
    vi.mocked(auth.getToken).mockReturnValue('token-iam6')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    const detail = await screen.findByTestId('OrganizationDetailPage')
    expect(detail.getAttribute('data-org-id')).toBe('42')

    fireEvent.click(screen.getByText('manage-sso-link'))

    const settings = await screen.findByTestId('SSOSettingsPage')
    expect(settings.getAttribute('data-org-id')).toBe('42')
    expect(screen.queryByTestId('OrganizationDetailPage')).not.toBeInTheDocument()
  })

  it('signing out via the profile menu returns to the login screen', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-admin6')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    fireEvent.click(screen.getByText(admin.email))
    fireEvent.click(screen.getByText('Sign out'))

    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  // ── PR11.2: Teams / Roles & Permissions nav items ──────────────────────

  it('reaches Teams and Roles & Permissions via the sidebar, no longer Coming Soon', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-teams')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    clickNav('Teams')
    expect(await screen.findByTestId('TeamsPage')).toBeInTheDocument()
    expect(screen.queryByText('Coming soon')).not.toBeInTheDocument()

    clickNav('Roles & Permissions')
    expect(await screen.findByTestId('RolesPage')).toBeInTheDocument()
    expect(screen.queryByText('Coming soon')).not.toBeInTheDocument()
  })

  it('hides Teams and Roles & Permissions for a user without organizational access', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-noorg')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(false)

    render(<AdminApp />)
    await waitFor(() => expect(screen.getByTestId('DashboardPage')).toBeInTheDocument())

    expect(screen.queryByText('Teams')).not.toBeInTheDocument()
    expect(screen.queryByText('Roles & Permissions')).not.toBeInTheDocument()
  })

  it('navigates from an organization detail page to Teams/Roles pre-scoped to that organization', async () => {
    window.history.pushState(null, '', '/organizations/42')
    vi.mocked(auth.getToken).mockReturnValue('token-quicklink')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.getSessionUser).mockReturnValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReturnValue(true)

    render(<AdminApp />)
    const detail = await screen.findByTestId('OrganizationDetailPage')
    expect(detail.getAttribute('data-org-id')).toBe('42')

    fireEvent.click(screen.getByText('View all teams'))
    expect(await screen.findByTestId('TeamsPage')).toHaveAttribute('data-initial-org-id', '42')
  })
})
