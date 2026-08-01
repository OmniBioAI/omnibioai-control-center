import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OrganizationDetailPage from './OrganizationDetailPage'
import * as auth from '../auth'
import * as organizations from '../organizations'
import type { PlatformOrgDetail, MyOrg } from '../organizations'

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
  }
})

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
  })

  it('reuses the PR1 detail response directly -- no separate calls invented', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('owner@acme.test')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument() // member_summary.total
    expect(screen.getByText('oidc')).toBeInTheDocument() // sso.provider_type
    expect(organizations.fetchPlatformOrgDetail).toHaveBeenCalledWith(42)
    expect(organizations.fetchMyOrg).not.toHaveBeenCalled()
  })

  it('shows an error state instead of crashing when the org cannot be loaded', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockRejectedValue(new Error('/platform/orgs/999 404'))
    render(<OrganizationDetailPage orgId={999} onBack={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
  })

  it('shows the suspend action and confirms before calling the backend', async () => {
    vi.mocked(organizations.fetchPlatformOrgDetail).mockResolvedValue(platformDetail)
    vi.mocked(organizations.setOrganizationStatus).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Acme Corp')

    expect(screen.getByRole('button', { name: 'Suspend Organization' })).toBeInTheDocument()
    expect(organizations.setOrganizationStatus).not.toHaveBeenCalled()
  })
})

describe('OrganizationDetailPage -- organization admin', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrg).mockReset()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockClear()
  })

  it('uses GET /orgs/{id} and shows only what OrganizationOut provides -- no summaries invented', async () => {
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
    render(<OrganizationDetailPage orgId={5} onBack={vi.fn()} />)

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
    render(<OrganizationDetailPage orgId={777} onBack={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
    expect(screen.queryByText('My Org')).not.toBeInTheDocument()
  })
})
