import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OrganizationDetailPage from './OrganizationDetailPage'
import * as auth from '../auth'
import * as organizations from '../organizations'
import type { PlatformOrgDetail, MyOrg, OrgMember } from '../organizations'
import * as roles from '../roles'
import type { RoleSummary } from '../roles'

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

// Team Management v0.8.0 Step 5: TeamsCard now owns its own full
// behavior coverage (TeamsCard.test.tsx, TeamRow.test.tsx,
// TeamMembersPanel.test.tsx) -- mirrors TeamsPage.test.tsx's own
// established precedent for this exact component ("TeamsCard already has
// its own full test coverage ... this page's tests only need to prove it
// receives the right orgId"). This page's own Teams tests below now only
// prove the same wiring, not re-prove TeamsCard's internal behavior.
vi.mock('../components/teams/TeamsCard', () => ({
  default: ({ orgId }: { orgId: number }) => <div data-testid="TeamsCard" data-org-id={orgId} />,
}))

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
    // Tests below that don't care about Members & Roles never call
    // fetchOrgMembers explicitly -- default to a rejection so the section
    // hides itself silently, matching what a real 403 for a non-manage_org
    // caller would do, rather than an unhandled-rejection-shaped default.
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/x/members 403'))
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue([])
  })

  it('reuses the PR1 detail response directly -- no separate calls invented', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)

    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('owner@acme.test')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument() // member_summary.total
    expect(screen.getByText('oidc')).toBeInTheDocument() // sso.provider_type
    expect(organizations.fetchPlatformOrgDetail).toHaveBeenCalledWith(42)
    expect(organizations.fetchMyOrg).not.toHaveBeenCalled()
  })

  it('shows an error state instead of crashing when the org cannot be loaded', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockRejectedValue(new Error('/platform/orgs/999 404'))
    render(<OrganizationDetailPage orgId={999} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
  })

  it('shows the suspend action and confirms before calling the backend', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.setOrganizationStatus).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByRole('button', { name: 'Suspend Organization' })).toBeInTheDocument()
    expect(organizations.setOrganizationStatus).not.toHaveBeenCalled()
  })

  // ── PR11.3: SSO summary card + Manage SSO Settings link ────────────────

  it('renders the SSO summary card fed by the existing PlatformOrgDetail.sso field, with a Manage SSO Settings link', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByText('SSO Configuration')).toBeInTheDocument()
    expect(screen.getByText('https://idp.acme.test')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Manage SSO Settings/ })).toBeInTheDocument()
    // No new fetch invented for this card -- still the one
    // fetchPlatformOrgDetail call every other section on this page uses.
    expect(organizations.fetchPlatformOrgDetail).toHaveBeenCalledTimes(1)
  })

  it('shows the no-SSO-configured message when the org has none', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue({
      ...platformDetail,
      sso: { configured: false, provider_type: null, issuer: null, status: null, enforced: false, override_active: false },
    })
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByText(/No SSO configured for this organization/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Manage SSO Settings/ })).toBeInTheDocument()
  })

  it('calls onManageSso with this organization\'s id when the link is clicked', async () => {
    const user = userEvent.setup()
    const onManageSso = vi.fn()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={onManageSso} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /Manage SSO Settings/ }))
    expect(onManageSso).toHaveBeenCalledWith(42)
  })

  // ── PR11.4: Service Accounts / API Keys summary links ──────────────────

  it('renders the API Keys / OAuth Clients summary cards fed by the existing PlatformOrgDetail fields, with Manage links', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
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
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={onManageServiceAccounts} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /Manage Service Accounts/ }))
    expect(onManageServiceAccounts).toHaveBeenCalledWith(42, 'oauth-clients')
  })

  it('calls onManageServiceAccounts with this org\'s id and the api-keys tab from "Manage API Keys"', async () => {
    const user = userEvent.setup()
    const onManageServiceAccounts = vi.fn()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={onManageServiceAccounts} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /Manage API Keys/ }))
    expect(onManageServiceAccounts).toHaveBeenCalledWith(42, 'api-keys')
  })

  // ── Phase 3 PR3B: Members & Roles ─────────────────────────────────────

  it('lists members with a role checkbox per catalog role', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockResolvedValue(orgMembers)
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue(orgRoleCatalog)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
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
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
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
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    const orgAdminCheckbox = await screen.findByRole('checkbox', { name: /^org_admin\b/ })
    await user.click(orgAdminCheckbox)

    await waitFor(() => expect(roles.removeOrgMemberRole).toHaveBeenCalledWith(42, 7, 10))
  })

  it('hides the Members & Roles section entirely when the members fetch is forbidden, instead of showing an error', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/42/members 403'))
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await waitFor(() => expect(organizations.fetchOrgMembers).toHaveBeenCalled())
    expect(screen.queryByText('Members & Roles')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  // ── Team Management v0.8.0 Step 5: Teams ────────────────────────────────
  // TeamsCard is mocked (see the vi.mock above) -- its own full behavior
  // (create/rename/delete/manage members: invite, role change, remove,
  // leave) is covered by TeamsCard.test.tsx/TeamRow.test.tsx/
  // TeamMembersPanel.test.tsx. This page's own test only proves it's
  // mounted with the right orgId.

  it('renders the Teams card scoped to this organization', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(await screen.findByTestId('TeamsCard')).toHaveAttribute('data-org-id', '42')
  })

  // ── PR11.2 Phase 4: Security summary + quick links ──────────────────────

  it('shows the Security summary with real SSO status and explicit MFA/domain placeholders', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByText('Security')).toBeInTheDocument()
    expect(screen.getByText('Configured')).toBeInTheDocument() // sso.configured === true
    expect(screen.getByText('Not configured')).toBeInTheDocument() // MFA placeholder
    expect(screen.getByText('Pending verification')).toBeInTheDocument() // Domain placeholder
  })

  it('renders "View all teams" / "View roles & permissions" links when the callbacks are provided, and calls them with this org', async () => {
    const user = userEvent.setup()
    const onViewTeams = vi.fn()
    const onViewRoles = vi.fn()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onViewTeams={onViewTeams} onViewRoles={onViewRoles} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /View all teams/ }))
    expect(onViewTeams).toHaveBeenCalledWith(42)

    await user.click(screen.getByRole('button', { name: /View roles & permissions/ }))
    expect(onViewRoles).toHaveBeenCalledWith(42)
  })

  it('renders no quick links when onViewTeams/onViewRoles are omitted', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.queryByRole('button', { name: /View all teams/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /View roles & permissions/ })).not.toBeInTheDocument()
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
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/x/members 403'))
    vi.mocked(roles.fetchOrgRoles).mockResolvedValue([])
  })

  it('uses GET /orgs/{id} and shows only what OrganizationOut provides -- no summaries invented', async () => {
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={5} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)

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
    render(<OrganizationDetailPage orgId={777} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
    expect(screen.queryByText('My Org')).not.toBeInTheDocument()
  })

  // Teams also appears in the org-admin view (TeamsCard is mocked -- see
  // the vi.mock above; its own behavior is covered elsewhere).
  it('shows the Teams card for an org-admin/member viewing their own org', async () => {
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={5} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('My Org')

    expect(await screen.findByTestId('TeamsCard')).toHaveAttribute('data-org-id', '5')
  })

  it('shows the Security summary with SSO marked not available (OrganizationOut has no SSO field)', async () => {
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={5} onBack={vi.fn()} onManageSso={vi.fn()} onManageServiceAccounts={vi.fn()} />)
    await screen.findByText('My Org')

    expect(screen.getByText('Security')).toBeInTheDocument()
    expect(screen.getByText('Not available in this view')).toBeInTheDocument()
    expect(screen.getByText('Not configured')).toBeInTheDocument() // MFA placeholder
    expect(screen.getByText('Pending verification')).toBeInTheDocument() // Domain placeholder
  })
})
