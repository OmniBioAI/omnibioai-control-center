import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import RolesPage from './RolesPage'
import * as auth from '../../auth'
import * as organizations from '../../organizations'
import * as roles from '../../roles'
import type { OrgMember, PlatformOrgListResponse, MyOrg } from '../../organizations'
import type { RoleSummary } from '../../roles'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn(), fetchMyOrgs: vi.fn(), fetchOrgMembers: vi.fn() }
})

vi.mock('../../roles', async () => {
  const actual = await vi.importActual<typeof import('../../roles')>('../../roles')
  return { ...actual, fetchOrgRoles: vi.fn() }
})

const platformOrgs = (): PlatformOrgListResponse => ({
  items: [
    { id: 1, name: 'Acme Corp', status: 'active', created_at: '2026-07-15T10:00:00', owner_email: null, member_count: 2, team_count: 1, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false },
  ],
  total: 1, page: 1, page_size: 100, total_pages: 1,
})

const roleCatalog: RoleSummary[] = [
  { id: 10, name: 'org_admin', description: 'Full control of the organization', permissions: ['manage_org', 'manage_teams'] },
  { id: 11, name: 'org_member', description: null, permissions: [] },
]

const orgMembers: OrgMember[] = [
  { user_id: 7, email: 'admin@acme.test', status: 'active', roles: ['org_admin'] },
  { user_id: 8, email: 'member@acme.test', status: 'active', roles: ['org_member'] },
]

describe('RolesPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset()
    vi.mocked(organizations.fetchMyOrgs).mockReset()
    vi.mocked(organizations.fetchOrgMembers).mockReset()
    vi.mocked(roles.fetchOrgRoles).mockReset()
  })

  // ── Role / permission rendering ─────────────────────────────────────────

  it('renders each role with its permission list', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(roleCatalog)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    render(<RolesPage />)

    expect(await screen.findByText('org_admin')).toBeInTheDocument()
    expect(screen.getByText('org_member')).toBeInTheDocument()
    expect(screen.getByText('Full control of the organization')).toBeInTheDocument()
    expect(screen.getByText('manage_org')).toBeInTheDocument()
    expect(screen.getByText('manage_teams')).toBeInTheDocument()
    expect(screen.getByText('No permissions granted.')).toBeInTheDocument()
  })

  it("computes each role's member count from the org roster", async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(roleCatalog)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    render(<RolesPage />)

    await screen.findByText('org_admin')
    // Both roles have exactly one holder in orgMembers above.
    expect(screen.getAllByText('1 member').length).toBe(2)
  })

  it('shows "—" for member counts when the org roster is forbidden, not an error', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(roleCatalog)
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/1/members 403'))
    render(<RolesPage />)

    await screen.findByText('org_admin')
    expect(screen.getAllByText('—').length).toBe(2)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('never renders role creation, editing, or assignment controls (read-only)', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(roleCatalog)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    render(<RolesPage />)

    await screen.findByText('org_admin')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /new role/i })).not.toBeInTheDocument()
  })

  // ── Organization switching ─────────────────────────────────────────────

  it('reloads the role catalog when the organization selector changes', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [
        ...platformOrgs().items,
        { id: 2, name: 'Beta Labs', status: 'active', created_at: '2026-07-16T10:00:00', owner_email: null, member_count: 0, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false },
      ],
      total: 2, page: 1, page_size: 100, total_pages: 1,
    })
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(roleCatalog)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue([])
    render(<RolesPage />)

    await screen.findByText('org_admin')
    vi.mocked(roles.fetchOrgRoles).mockClear()
    await user.selectOptions(screen.getByLabelText('Select organization'), '2')

    await waitFor(() => expect(roles.fetchOrgRoles).toHaveBeenCalledWith(2))
  })

  // ── Loading / empty / error states ─────────────────────────────────────

  it('shows the empty state when the organization has no roles defined', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue([])
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue([])
    render(<RolesPage />)
    expect(await screen.findByText('No roles defined for this organization.')).toBeInTheDocument()
  })

  it('shows an error state when the role catalog request fails', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrgRoles).mockRejectedValue(new Error('/orgs/1/roles 500'))
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue([])
    render(<RolesPage />)
    expect(await screen.findByText(/orgs\/1\/roles 500/)).toBeInTheDocument()
  })

  // ── Permission visibility / denied access ───────────────────────────────

  it('loads organizations via the org-scoped endpoint for a non-platform-admin viewer', async () => {
    const org: MyOrg = {
      id: 9, slug: 'my-org', name: 'My Org', plan: 'beta', status: 'active',
      status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
    }
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([org])
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue([])
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue([])
    render(<RolesPage />)

    await screen.findByText('No roles defined for this organization.')
    expect(organizations.fetchMyOrgs).toHaveBeenCalled()
    expect(organizations.fetchPlatformOrgs).not.toHaveBeenCalled()
    expect(roles.fetchOrgRoles).toHaveBeenCalledWith(9)
  })

  it('shows the empty state when the viewer belongs to no organizations', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([])
    render(<RolesPage />)
    expect(await screen.findByText("You don't belong to any organization yet.")).toBeInTheDocument()
  })
})
