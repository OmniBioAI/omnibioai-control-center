import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OrganizationsPage from './OrganizationsPage'
import * as auth from '../auth'
import * as organizations from '../organizations'

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn(), fetchMyOrgs: vi.fn(), createPlatformOrganization: vi.fn() }
})

const platformRow = (overrides: Partial<organizations.PlatformOrgSummary> = {}): organizations.PlatformOrgSummary => ({
  id: 1, name: 'Acme Corp', status: 'active', created_at: '2026-07-15T10:00:00',
  owner_email: 'owner@acme.test', member_count: 8, team_count: 3, api_key_count: 2,
  oauth_client_count: 1, license_count: 5, sso_enabled: true, mfa_policy_required: false, mfa_policy_configured: false, ...overrides,
})

describe('OrganizationsPage -- platform admin', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    vi.mocked(organizations.fetchPlatformOrgs).mockReset()
    vi.mocked(organizations.fetchMyOrgs).mockClear()
    vi.mocked(organizations.createPlatformOrganization).mockReset()
  })

  it('lists every organization via GET /platform/orgs, never the org-scoped endpoint', async () => {
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [platformRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<OrganizationsPage onSelect={vi.fn()} />)

    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('owner@acme.test')).toBeInTheDocument()
    expect(organizations.fetchPlatformOrgs).toHaveBeenCalled()
    expect(organizations.fetchMyOrgs).not.toHaveBeenCalled()
  })

  it('shows the loading state before data resolves', () => {
    vi.mocked(organizations.fetchPlatformOrgs).mockReturnValue(new Promise(() => {}))
    render(<OrganizationsPage onSelect={vi.fn()} />)
    expect(screen.getByText(/Loading organizations/)).toBeInTheDocument()
  })

  it('shows the empty state when no organizations exist', async () => {
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20, total_pages: 0,
    })
    render(<OrganizationsPage onSelect={vi.fn()} />)
    expect(await screen.findByText('No organizations exist yet.')).toBeInTheDocument()
  })

  it('shows the error state when the request fails', async () => {
    vi.mocked(organizations.fetchPlatformOrgs).mockRejectedValue(new Error('/platform/orgs 500'))
    render(<OrganizationsPage onSelect={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('/platform/orgs 500')
  })

  it('re-fetches with the search term on submit', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [platformRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await user.type(screen.getByLabelText('Search organizations'), 'acme')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() =>
      expect(organizations.fetchPlatformOrgs).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: 'acme', page: 1 })
      )
    )
  })

  it('paginates using the total_pages/page from the response', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [platformRow()], total: 40, page: 1, page_size: 20, total_pages: 2,
    })
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('button', { name: /Next/ }))

    await waitFor(() =>
      expect(organizations.fetchPlatformOrgs).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }))
    )
  })

  it('sorts by clicking a sortable column header', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [platformRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('Acme Corp')

    await user.click(screen.getByRole('columnheader', { name: /Name/ }))

    await waitFor(() =>
      expect(organizations.fetchPlatformOrgs).toHaveBeenLastCalledWith(
        expect.objectContaining({ sortBy: 'name', sortOrder: 'asc' })
      )
    )
  })

  it('invokes onSelect with the org id when a row is clicked', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [platformRow({ id: 99 })], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<OrganizationsPage onSelect={onSelect} />)
    await user.click(await screen.findByTestId('org-row-99'))
    expect(onSelect).toHaveBeenCalledWith(99)
  })

  it('creates a tenant through the platform API, confirms server success, and refreshes the list', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgs)
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 20, total_pages: 0 })
      .mockResolvedValueOnce({ items: [platformRow({ id: 3, name: 'New Tenant' })], total: 1, page: 1, page_size: 20, total_pages: 1 })
    let confirmCreated!: (tenant: organizations.MyOrg) => void
    vi.mocked(organizations.createPlatformOrganization).mockReturnValue(new Promise(resolve => { confirmCreated = resolve }))
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('No organizations exist yet.')

    await user.click(screen.getByRole('button', { name: '+ Create Tenant' }))
    await user.type(screen.getByLabelText('Tenant name'), 'New Tenant')
    await user.type(screen.getByLabelText('Tenant slug'), 'new-tenant')
    await user.click(screen.getByRole('button', { name: 'Create Tenant' }))

    await waitFor(() => expect(organizations.createPlatformOrganization).toHaveBeenCalledWith('New Tenant', 'new-tenant'))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(organizations.fetchPlatformOrgs).toHaveBeenCalledTimes(1)

    confirmCreated({
      id: 3, slug: 'new-tenant', name: 'New Tenant', plan: 'beta', status: 'active',
      status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Tenant “New Tenant” created successfully.')
    expect(await screen.findByText('New Tenant')).toBeInTheDocument()
    expect(organizations.fetchPlatformOrgs).toHaveBeenCalledTimes(2)
  })

  it('does not report success or refresh after a failed create', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, total_pages: 0 })
    vi.mocked(organizations.createPlatformOrganization).mockRejectedValue(new Error('Organization slug already exists'))
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('No organizations exist yet.')
    await user.click(screen.getByRole('button', { name: '+ Create Tenant' }))
    await user.type(screen.getByLabelText('Tenant name'), 'Duplicate')
    await user.type(screen.getByLabelText('Tenant slug'), 'duplicate')
    await user.click(screen.getByRole('button', { name: 'Create Tenant' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Organization slug already exists')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(organizations.fetchPlatformOrgs).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('Duplicate')).not.toBeInTheDocument()
  })

  it('validates trimmed required fields before sending a request', async () => {
    const user = userEvent.setup()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, total_pages: 0 })
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('No organizations exist yet.')
    await user.click(screen.getByRole('button', { name: '+ Create Tenant' }))
    await user.type(screen.getByLabelText('Tenant name'), '   ')
    await user.type(screen.getByLabelText('Tenant slug'), 'slug')
    await user.click(screen.getByRole('button', { name: 'Create Tenant' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Enter both a tenant name and a tenant slug.')
    expect(organizations.createPlatformOrganization).not.toHaveBeenCalled()
  })

  it('does not offer platform tenant creation in the organization-scoped view', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 5, slug: 'my-org', name: 'My Org', plan: 'beta', status: 'active',
        status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    render(<OrganizationsPage onSelect={vi.fn()} />)
    await screen.findByText('My Org')
    expect(screen.queryByRole('button', { name: '+ Create Tenant' })).not.toBeInTheDocument()
  })
})

describe('OrganizationsPage -- organization admin', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchMyOrgs).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockClear()
    vi.mocked(organizations.createPlatformOrganization).mockReset()
  })

  it('shows only organizations the caller belongs to, via GET /orgs, never the platform endpoint', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 5, slug: 'my-org', name: 'My Org', plan: 'beta', status: 'active',
        status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    render(<OrganizationsPage onSelect={vi.fn()} />)

    expect(await screen.findByText('My Org')).toBeInTheDocument()
    expect(organizations.fetchMyOrgs).toHaveBeenCalled()
    expect(organizations.fetchPlatformOrgs).not.toHaveBeenCalled()
    // Cross-tenant-only columns never render for this audience.
    expect(screen.queryByText(/Members/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Owner/)).not.toBeInTheDocument()
  })

  it('shows every organization the caller belongs to when there is more than one -- no separate switcher', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([
      { id: 5, slug: 'org-a', name: 'Org A', plan: 'beta', status: 'active',
        status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
      { id: 6, slug: 'org-b', name: 'Org B', plan: 'beta', status: 'active',
        status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null },
    ])
    render(<OrganizationsPage onSelect={vi.fn()} />)
    expect(await screen.findByText('Org A')).toBeInTheDocument()
    expect(screen.getByText('Org B')).toBeInTheDocument()
  })

  it('shows the empty state when the caller belongs to no organization', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockResolvedValue([])
    render(<OrganizationsPage onSelect={vi.fn()} />)
    expect(await screen.findByText("You don't belong to any organization yet.")).toBeInTheDocument()
  })

  it('shows the error state when the request fails', async () => {
    vi.mocked(organizations.fetchMyOrgs).mockRejectedValue(new Error('/orgs 500'))
    render(<OrganizationsPage onSelect={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('/orgs 500')
  })
})
