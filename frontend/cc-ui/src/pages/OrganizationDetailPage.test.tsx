import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OrganizationDetailPage from './OrganizationDetailPage'
import * as auth from '../auth'
import * as organizations from '../organizations'
import type { PlatformOrgDetail, MyOrg, OrgMember } from '../organizations'
import * as roles from '../roles'
import type { RoleSummary } from '../roles'
import * as teams from '../teams'
import type { Team } from '../teams'

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return {
    ...actual,
    fetchPlatformOrgDetail: vi.fn(),
    fetchMyOrg: vi.fn(),
    setOrganizationStatus: vi.fn(),
    fetchOrgMembers: vi.fn(),
  }
})

vi.mock('../roles', async () => {
  const actual = await vi.importActual<typeof import('../roles')>('../roles')
  return {
    ...actual,
    fetchOrgRoles: vi.fn(),
    assignOrgMemberRole: vi.fn(),
    removeOrgMemberRole: vi.fn(),
  }
})

vi.mock('../teams', async () => {
  const actual = await vi.importActual<typeof import('../teams')>('../teams')
  return {
    ...actual,
    listTeams: vi.fn(),
    createTeam: vi.fn(),
    updateTeamMembers: vi.fn(),
    deleteTeam: vi.fn(),
  }
})

const orgRoleCatalog: RoleSummary[] = [
  { id: 10, name: 'org_admin', description: null, permissions: ['manage_org'] },
  { id: 11, name: 'org_member', description: null, permissions: [] },
]

const orgMembers: OrgMember[] = [
  // Deliberately a different email than platformDetail.owner_email --
  // both render on the same page (General Information's "Owner" field and
  // this Members & Roles row), and reusing the same string would make
  // queries for either ambiguous, not a defect in the page itself.
  { user_id: 7, email: 'member-seven@acme.test', status: 'active', roles: ['org_admin'] },
]

const platformDetail: PlatformOrgDetail = {
  id: 42, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active',
  created_at: '2026-07-15T10:00:00', owner_user_id: 7, owner_email: 'owner@acme.test',
  member_summary: { total: 8, active: 7, invited: 1, revoked: null, most_recent_at: null },
  team_summary: { total: 3, active: null, invited: null, revoked: null, most_recent_at: null },
  api_key_summary: { total: 2, active: 2, invited: null, revoked: 0, most_recent_at: null },
  oauth_client_summary: { total: 1, active: 1, invited: null, revoked: 0, most_recent_at: null },
  license_summary: { total: 5, active: 5, invited: null, revoked: 0, most_recent_at: null },
  sso: { configured: true, provider_type: 'oidc', issuer: 'https://idp.acme.test', status: 'active', enforced: true, override_active: false },
  recent_activity: { org_created_at: '2026-07-15T10:00:00', most_recent_member_joined_at: null, most_recent_api_key_created_at: null, most_recent_oauth_client_created_at: null },
  status_changed_at: null, status_changed_reason: null, status_changed_by_email: null,
}

const orgTeams: Team[] = [
  { id: 1, organization_id: 42, name: 'Genomics', member_user_ids: [7] },
]

const myOrg: MyOrg = {
  id: 5, slug: 'my-org', name: 'My Org', plan: 'beta', status: 'active',
  status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
}

describe('OrganizationDetailPage -- platform admin', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgDetail).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockClear()
    vi.mocked(organizations.fetchOrgMembers).mockReset()
    vi.mocked(roles.fetchOrgRoles).mockReset()
    vi.mocked(roles.assignOrgMemberRole).mockReset()
    vi.mocked(roles.removeOrgMemberRole).mockReset()
    vi.mocked(teams.listTeams).mockReset()
    vi.mocked(teams.createTeam).mockReset()
    vi.mocked(teams.updateTeamMembers).mockReset()
    vi.mocked(teams.deleteTeam).mockReset()
    // Tests below that don't care about Members & Roles never call
    // fetchOrgMembers explicitly -- default to a rejection so the section
    // hides itself silently, matching what a real 403 for a non-manage_org
    // caller would do, rather than an unhandled-rejection-shaped default.
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/x/members 403'))
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue([])
    // Same reasoning for Teams -- default to an empty list so tests that
    // don't care about it see "No teams yet." rather than a permanently
    // pending fetch.
    vi.mocked(teams.listTeams).mockResolvedValue([])
  })

  it('reuses the PR1 detail response directly -- no separate calls invented', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)

    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('owner@acme.test')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument() // member_summary.total
    expect(screen.getByText('oidc')).toBeInTheDocument() // sso.provider_type
    expect(organizations.fetchPlatformOrgDetail).toHaveBeenCalledWith(42)
    expect(organizations.fetchMyOrg).not.toHaveBeenCalled()
  })

  it('shows an error state instead of crashing when the org cannot be loaded', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockRejectedValue(new Error('/platform/orgs/999 404'))
    render(<OrganizationDetailPage orgId={999} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
  })

  it('shows the suspend action and confirms before calling the backend', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.setOrganizationStatus).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByRole('button', { name: 'Suspend Organization' })).toBeInTheDocument()
    expect(organizations.setOrganizationStatus).not.toHaveBeenCalled()
  })

  // ── PR11.4: Service Accounts / API Keys summary links ──────────────────

  it('renders the API Keys / OAuth Clients summary cards fed by the existing PlatformOrgDetail fields, with Manage links', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByText('API Keys')).toBeInTheDocument()
    expect(screen.getByText('OAuth Clients')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Manage Service Accounts/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Manage API Keys/ })).toBeInTheDocument()
    // No new fetch invented for these links -- still the one
    // fetchPlatformOrgDetail call every other section on this page uses.
    expect(organizations.fetchPlatformOrgDetail).toHaveBeenCalledTimes(1)
  })

  it('calls onManageServiceAccounts with this org\'s id and the oauth-clients tab from "Manage Service Accounts"', async () => {
    const user = userEvent.setup()
    const onManageServiceAccounts = vi.fn()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={onManageServiceAccounts} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /Manage Service Accounts/ }))
    expect(onManageServiceAccounts).toHaveBeenCalledWith(42, 'oauth-clients')
  })

  it('calls onManageServiceAccounts with this org\'s id and the api-keys tab from "Manage API Keys"', async () => {
    const user = userEvent.setup()
    const onManageServiceAccounts = vi.fn()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={onManageServiceAccounts} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /Manage API Keys/ }))
    expect(onManageServiceAccounts).toHaveBeenCalledWith(42, 'api-keys')
  })

  // ── Phase 3 PR3B: Members & Roles ─────────────────────────────────────

  it('lists members with a role checkbox per catalog role', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(orgRoleCatalog)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(await screen.findByText('member-seven@acme.test')).toBeInTheDocument()
    const orgAdminCheckbox = await screen.findByRole('checkbox', { name: /^org_admin\b/ })
    const orgMemberCheckbox = screen.getByRole('checkbox', { name: /^org_member\b/ })
    expect(orgAdminCheckbox).toBeChecked()
    expect(orgMemberCheckbox).not.toBeChecked()
  })

  it('assigns an org role to a member and refreshes the member list', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(orgRoleCatalog)
    vi.mocked(roles.assignOrgMemberRole).mockResolvedValue({ organization_id: 42, user_id: 7, roles: ['org_admin', 'org_member'] })
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    const orgMemberCheckbox = await screen.findByRole('checkbox', { name: /^org_member\b/ })
    // Phase 3 PR3C's TeamsCard also independently fetches org members on
    // mount (its own, separate card, same page) -- so the absolute call
    // count here is no longer just MembersRolesCard's. Assert the count
    // increases after the assignment (proving MembersRolesCard refreshed),
    // not an exact total tied to how many sibling cards happen to exist.
    const callsBeforeAssign = vi.mocked(organizations.fetchOrgMembers).mock.calls.length
    await user.click(orgMemberCheckbox)

    await waitFor(() => expect(roles.assignOrgMemberRole).toHaveBeenCalledWith(42, 7, 'org_member'))
    await waitFor(() =>
      expect(vi.mocked(organizations.fetchOrgMembers).mock.calls.length).toBeGreaterThan(callsBeforeAssign)
    )
  })

  it('removes an org role from a member', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(orgRoleCatalog)
    vi.mocked(roles.removeOrgMemberRole).mockResolvedValue(undefined)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    const orgAdminCheckbox = await screen.findByRole('checkbox', { name: /^org_admin\b/ })
    await user.click(orgAdminCheckbox)

    await waitFor(() => expect(roles.removeOrgMemberRole).toHaveBeenCalledWith(42, 7, 10))
  })

  it('hides the Members & Roles section entirely when the members fetch is forbidden, instead of showing an error', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/42/members 403'))
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await waitFor(() => expect(organizations.fetchOrgMembers).toHaveBeenCalled())
    expect(screen.queryByText('Members & Roles')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // ── Phase 3 PR3C: Teams ─────────────────────────────────────────────────

  it('renders the Teams card with resolved member emails', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    vi.mocked(teams.listTeams).mockResolvedValue(orgTeams)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(await screen.findByText('Genomics')).toBeInTheDocument()
    // member-seven@acme.test renders twice on this page -- once as
    // MembersRolesCard's own row heading, once as TeamRow's resolved
    // member email -- both are correct, so assert presence, not a single
    // match.
    expect(screen.getAllByText('member-seven@acme.test').length).toBeGreaterThan(0)
  })

  it('creates a team via the create form and refreshes the list', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(teams.listTeams).mockResolvedValue([])
    vi.mocked(teams.createTeam).mockResolvedValue({ id: 2, organization_id: 42, name: 'Proteomics', member_user_ids: [] })
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')
    await screen.findByText('No teams yet.')

    await user.type(screen.getByLabelText('New team name'), 'Proteomics')
    await user.click(screen.getByRole('button', { name: 'Create Team' }))

    await waitFor(() => expect(teams.createTeam).toHaveBeenCalledWith(42, { name: 'Proteomics' }))
    await waitFor(() => expect(teams.listTeams).toHaveBeenCalledTimes(2))
  })

  it('deletes a team after confirmation, not before', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    vi.mocked(teams.listTeams).mockResolvedValue(orgTeams)
    vi.mocked(teams.deleteTeam).mockResolvedValue(undefined)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Genomics')

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    await user.click(deleteButtons[deleteButtons.length - 1])
    expect(teams.deleteTeam).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm delete' }))
    await waitFor(() => expect(teams.deleteTeam).toHaveBeenCalledWith(42, 1))
  })

  it('edits team members via the member selector, full-replacing the list', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue([
      ...orgMembers,
      { user_id: 9, email: 'second-member@acme.test', status: 'active', roles: ['org_member'] },
    ])
    vi.mocked(teams.listTeams).mockResolvedValue(orgTeams)
    vi.mocked(teams.updateTeamMembers).mockResolvedValue({ ...orgTeams[0], member_user_ids: [7, 9] })
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Genomics')

    await user.click(screen.getByRole('button', { name: 'Edit Members' }))
    await user.click(screen.getByRole('checkbox', { name: 'second-member@acme.test' }))

    await waitFor(() => expect(teams.updateTeamMembers).toHaveBeenCalledWith(42, 1, [7, 9]))
  })

  it('hides the Teams card entirely when the teams fetch itself is forbidden', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(teams.listTeams).mockRejectedValue(new Error('/orgs/42/teams 403'))
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await waitFor(() => expect(teams.listTeams).toHaveBeenCalled())
    // Not 'Teams' -- OrganizationSummaryCard already renders that exact
    // text as its own, unrelated summary-tile title (org.team_summary),
    // regardless of whether TeamsCard renders at all. "New team name" is
    // unique to TeamsCard's own create form.
    expect(screen.queryByLabelText('New team name')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('falls back to raw user ids and disables member editing when the org roster is unavailable', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/42/members 403'))
    vi.mocked(teams.listTeams).mockResolvedValue(orgTeams)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Genomics')

    expect(await screen.findByText('User #7')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit Members' })).not.toBeInTheDocument()
  })
})

describe('OrganizationDetailPage -- organization admin', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrg).mockReset()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockClear()
    vi.mocked(organizations.fetchOrgMembers).mockReset()
    vi.mocked(roles.fetchOrgRoles).mockReset()
    vi.mocked(roles.assignOrgMemberRole).mockReset()
    vi.mocked(roles.removeOrgMemberRole).mockReset()
    vi.mocked(teams.listTeams).mockReset()
    vi.mocked(teams.createTeam).mockReset()
    vi.mocked(teams.updateTeamMembers).mockReset()
    vi.mocked(teams.deleteTeam).mockReset()
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/x/members 403'))
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue([])
    vi.mocked(teams.listTeams).mockResolvedValue([])
  })

  it('uses GET /orgs/{id} and shows only what OrganizationOut provides -- no summaries invented', async () => {
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={5} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)

    expect(await screen.findByText('My Org')).toBeInTheDocument()
    expect(organizations.fetchMyOrg).toHaveBeenCalledWith(5)
    expect(organizations.fetchPlatformOrgDetail).not.toHaveBeenCalled()
    // No owner/summaries/SSO -- OrganizationOut has none of this.
    expect(screen.queryByText('owner@acme.test')).not.toBeInTheDocument()
    expect(screen.queryByText('SSO Configuration')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Suspend/ })).not.toBeInTheDocument()
  })

  it('shows an error, not another organization, when the backend rejects the request', async () => {
    // Simulates a non-member manually changing the URL to another org's
    // id -- get_org_membership_or_platform_admin's 404 is what actually
    // stops them; this proves the page renders that rejection, not a
    // blank/wrong-org screen.
    vi.mocked(organizations.fetchMyOrg).mockRejectedValue(new Error('/orgs/777 404'))
    render(<OrganizationDetailPage orgId={777} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
    expect(screen.queryByText('My Org')).not.toBeInTheDocument()
  })

  // Phase 3 PR3C: Teams also appears in the org-admin view -- listing
  // teams only requires org membership, not manage_org, unlike Members &
  // Roles above (which does require it, and stays absent for a plain
  // member -- see MyOrgDetailView's own note in the page component).
  it('shows the Teams card for an org-admin/member viewing their own org', async () => {
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
    vi.mocked(teams.listTeams).mockResolvedValue(orgTeams)
    render(<OrganizationDetailPage orgId={5} onBack={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('My Org')

    expect(await screen.findByText('Genomics')).toBeInTheDocument()
    expect(teams.listTeams).toHaveBeenCalledWith(5)
  })
})
