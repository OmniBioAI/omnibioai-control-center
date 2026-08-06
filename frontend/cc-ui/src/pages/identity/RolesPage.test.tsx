import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import RolesPage from './RolesPage'
import * as auth from '../../auth'
import * as organizations from '../../organizations'
import * as roles from '../../roles'
import * as serviceAccounts from '../../serviceAccounts'
import type { OrgMember, PlatformOrgListResponse, MyOrg } from '../../organizations'
import type { RoleSummary } from '../../roles'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn(), hasOrgManageAccess: vi.fn() }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn(), fetchMyOrgs: vi.fn(), fetchOrgMembers: vi.fn() }
})

vi.mock('../../roles', async () => {
  const actual = await vi.importActual<typeof import('../../roles')>('../../roles')
  return {
    ...actual,
    fetchOrganizationRoles: vi.fn(),
    fetchOrganizationPermissions: vi.fn(),
    createPlatformRole: vi.fn(),
    updatePlatformRole: vi.fn(),
    deletePlatformRole: vi.fn(),
    createOrganizationRole: vi.fn(),
    updateOrganizationRole: vi.fn(),
    deleteOrganizationRole: vi.fn(),
  }
})

vi.mock('../../serviceAccounts', async () => {
  const actual = await vi.importActual<typeof import('../../serviceAccounts')>('../../serviceAccounts')
  return { ...actual, fetchPermissionRegistry: vi.fn() }
})

const platformOrgs = (): PlatformOrgListResponse => ({
  items: [
    { id: 1, name: 'Acme Corp', status: 'active', created_at: '2026-07-15T10:00:00', owner_email: null, member_count: 2, team_count: 1, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false },
  ],
  total: 1, page: 1, page_size: 100, total_pages: 1,
})

const roleCatalog: RoleSummary[] = [
  { id: 10, name: 'org_admin', description: 'Full control of the organization', permissions: ['manage_org', 'manage_teams'], organization_id: null },
  { id: 11, name: 'org_member', description: null, permissions: [], organization_id: null },
]

const customRole: RoleSummary = {
  id: 20, name: 'reviewer', description: 'QA reviewer', permissions: ['dataset.read'], organization_id: 1,
}

const orgMembers: OrgMember[] = [
  { user_id: 7, email: 'admin@acme.test', status: 'active', roles: ['org_admin'] },
  { user_id: 8, email: 'member@acme.test', status: 'active', roles: ['org_member'] },
]

function mockDefaults() {
  vi.mocked(auth.hasPlatformAdminAccess).mockReset().mockReturnValue(false)
  vi.mocked(auth.hasOrgManageAccess).mockReset().mockReturnValue(false)
  vi.mocked(organizations.fetchPlatformOrgs).mockReset()
  vi.mocked(organizations.fetchMyOrgs).mockReset()
  vi.mocked(organizations.fetchOrgMembers).mockReset().mockResolvedValue(orgMembers)
  vi.mocked(roles.fetchOrganizationRoles).mockReset().mockResolvedValue(roleCatalog)
  vi.mocked(roles.fetchOrganizationPermissions).mockReset().mockResolvedValue([])
  vi.mocked(serviceAccounts.fetchPermissionRegistry).mockReset().mockResolvedValue([])
}

describe('RolesPage', () => {
  beforeEach(mockDefaults)

  // ── Role / permission rendering ─────────────────────────────────────────

  it('renders each role with its permission list', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
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
    render(<RolesPage />)

    await screen.findByText('org_admin')
    expect(screen.getAllByText('1 member').length).toBe(2)
  })

  it('shows "—" for member counts when the org roster is forbidden, not an error', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/1/members 403'))
    render(<RolesPage />)

    await screen.findByText('org_admin')
    expect(screen.getAllByText('—').length).toBe(2)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('marks an org-owned custom role as "Custom", not a platform-wide one', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrganizationRoles).mockResolvedValue([...roleCatalog, customRole])
    render(<RolesPage />)

    await screen.findByText('reviewer')
    expect(screen.getByText('Custom')).toBeInTheDocument()
  })

  // ── Authorization-gated CRUD controls (PR13) ────────────────────────────

  it('offers no create/edit/delete controls for a viewer with neither platform-admin nor manage_org', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 1, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active', status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    render(<RolesPage />)

    await screen.findByText('org_admin')
    expect(screen.queryByRole('button', { name: /create platform role/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /create custom role/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument()
  })

  it('offers "Create platform role" only for a Platform Admin, and it can edit platform-wide roles', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    render(<RolesPage />)

    await screen.findByText('org_admin')
    expect(screen.getByRole('button', { name: /create platform role/i })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^edit$/i }).length).toBe(2) // both platform-wide roles
  })

  it('offers "Create custom role" and edit/delete on org-owned roles for an org manager, but not on platform-wide roles', async () => {
    vi.mocked(auth.hasOrgManageAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 1, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active', status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    vi.mocked(roles.fetchOrganizationRoles).mockResolvedValue([...roleCatalog, customRole])
    render(<RolesPage />)

    await screen.findByText('reviewer')
    expect(screen.getByRole('button', { name: /create custom role/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /create platform role/i })).not.toBeInTheDocument()
    // Only the custom role ("reviewer") is editable/deletable -- the two
    // platform-wide roles (org_admin/org_member) are not, from this side.
    expect(screen.getAllByRole('button', { name: /^edit$/i }).length).toBe(1)
    expect(screen.getAllByRole('button', { name: /^delete$/i }).length).toBe(1)
  })

  it('creating a custom role calls createOrganizationRole with the selected permissions', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasOrgManageAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 1, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active', status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    vi.mocked(roles.fetchOrganizationPermissions).mockResolvedValue([
      { name: 'dataset.read', resource: 'dataset', action: 'read', scope: 'both', category: 'dataset', description: 'Read datasets', legacy: false, deprecated: false, deprecated_reason: null },
    ])
    vi.mocked(roles.createOrganizationRole).mockResolvedValue(customRole)
    render(<RolesPage />)

    await screen.findByText('org_admin')
    await user.click(screen.getByRole('button', { name: /create custom role/i }))
    await user.type(screen.getByLabelText('Name'), 'reviewer')
    await user.click(await screen.findByRole('checkbox'))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^create/i }))

    await waitFor(() => expect(roles.createOrganizationRole).toHaveBeenCalledWith(
      1, expect.objectContaining({ name: 'reviewer', permissions: ['dataset.read'] }),
    ))
  })

  it('deleting a custom role calls deleteOrganizationRole after confirmation', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasOrgManageAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 1, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active', status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    vi.mocked(roles.fetchOrganizationRoles).mockResolvedValue([...roleCatalog, customRole])
    vi.mocked(roles.deleteOrganizationRole).mockResolvedValue(undefined)
    render(<RolesPage />)

    await screen.findByText('reviewer')
    await user.click(screen.getByRole('button', { name: /^delete$/i }))
    await user.click(screen.getByRole('button', { name: /^confirm$/i }))

    await waitFor(() => expect(roles.deleteOrganizationRole).toHaveBeenCalledWith(1, 20))
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
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue([])
    render(<RolesPage />)

    await screen.findByText('org_admin')
    vi.mocked(roles.fetchOrganizationRoles).mockClear()
    await user.selectOptions(screen.getByLabelText('Select organization'), '2')

    await waitFor(() => expect(roles.fetchOrganizationRoles).toHaveBeenCalledWith(2))
  })

  // ── Loading / empty / error states ─────────────────────────────────────

  it('shows the empty state when the organization has no roles defined', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrganizationRoles).mockResolvedValue([])
    render(<RolesPage />)
    expect(await screen.findByText('No roles defined for this organization.')).toBeInTheDocument()
  })

  it('shows an error state when the role catalog request fails', async () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue(platformOrgs())
    vi.mocked(roles.fetchOrganizationRoles).mockRejectedValue(new Error('/organizations/1/roles 500'))
    render(<RolesPage />)
    expect(await screen.findByText(/organizations\/1\/roles 500/)).toBeInTheDocument()
  })

  // ── Permission visibility / denied access ───────────────────────────────

  it('loads organizations via the org-scoped endpoint for a non-platform-admin viewer', async () => {
    const org: MyOrg = {
      id: 9, slug: 'my-org', name: 'My Org', plan: 'beta', status: 'active',
      status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
    }
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([org])
    vi.mocked(roles.fetchOrganizationRoles).mockResolvedValue([])
    render(<RolesPage />)

    await screen.findByText('No roles defined for this organization.')
    expect(organizations.fetchMyOrgs).toHaveBeenCalled()
    expect(organizations.fetchPlatformOrgs).not.toHaveBeenCalled()
    expect(roles.fetchOrganizationRoles).toHaveBeenCalledWith(9)
  })

  it('shows the empty state when the viewer belongs to no organizations', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([])
    render(<RolesPage />)
    expect(await screen.findByText("You don't belong to any organization yet.")).toBeInTheDocument()
  })
})
