import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UsersPage from './UsersPage'
import * as users from '../users'
import * as organizations from '../organizations'
import * as roles from '../roles'

vi.mock('../users', async () => {
  const actual = await vi.importActual<typeof import('../users')>('../users')
  return { ...actual, fetchPlatformUsers: vi.fn() }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

vi.mock('../roles', async () => {
  const actual = await vi.importActual<typeof import('../roles')>('../roles')
  return { ...actual, fetchPlatformRoles: vi.fn() }
})

const userRow = (overrides: Partial<users.PlatformUserSummary> = {}): users.PlatformUserSummary => ({
  id: 1, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [], org_count: 2, last_login_at: '2026-08-01T14:20:00Z', authentication_method: 'password',
  ...overrides,
})

describe('UsersPage', () => {
  beforeEach(() => {
    vi.mocked(users.fetchPlatformUsers).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset()
    vi.mocked(roles.fetchPlatformRoles).mockReset()
    // Most tests don't care about the filter dropdowns' own contents --
    // default to a small resolved catalog of each so those dropdowns
    // render without every test needing to mock this itself. Tests that
    // DO care about the dropdowns override these explicitly.
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [{ id: 9, name: 'Acme Corp', status: 'active', created_at: '2026-01-01T00:00:00', owner_email: null, member_count: 1, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false }],
      total: 1, page: 1, page_size: 100, total_pages: 1,
    })
    vi.mocked(roles.fetchPlatformRoles).mockResolvedValue([
      { id: 1, name: 'org_admin', description: null, permissions: [] },
    ])
  })

  it('lists users via GET /platform/users', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('someone@acme.test')).toBeInTheDocument()
    expect(users.fetchPlatformUsers).toHaveBeenCalled()
  })

  it('shows the loading state before data resolves', async () => {
    vi.mocked(users.fetchPlatformUsers).mockReturnValue(new Promise(() => {}))
    render(<UsersPage onSelect={vi.fn()} />)
    expect(screen.getByText(/Loading users/)).toBeInTheDocument()
    // Flushes the (resolved) org/role filter-catalog fetches before the
    // test ends, so their state updates land inside this async test
    // rather than warning after teardown.
    await waitFor(() => expect(organizations.fetchPlatformOrgs).toHaveBeenCalled())
  })

  it('shows the empty state when no users exist', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20, total_pages: 0,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('No users exist yet.')).toBeInTheDocument()
  })

  it('shows the error state when the request fails', async () => {
    vi.mocked(users.fetchPlatformUsers).mockRejectedValue(new Error('/platform/users 500'))
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('/platform/users 500')
  })

  it('re-fetches with the search term on submit', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.type(screen.getByLabelText('Search users'), 'acme')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() =>
      expect(users.fetchPlatformUsers).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'acme', page: 1 }))
    )
  })

  it('paginates using the total_pages/page from the response', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 40, page: 1, page_size: 20, total_pages: 2,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.click(screen.getByRole('button', { name: /Next/ }))

    await waitFor(() => expect(users.fetchPlatformUsers).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })))
  })

  it('sorts by clicking a sortable column header', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.click(screen.getByRole('columnheader', { name: /Email/ }))

    await waitFor(() =>
      expect(users.fetchPlatformUsers).toHaveBeenLastCalledWith(
        expect.objectContaining({ sortBy: 'email', sortOrder: 'asc' })
      )
    )
  })

  it('invokes onSelect with the user id when a row is clicked', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow({ id: 77 })], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={onSelect} />)
    await user.click(await screen.findByTestId('user-row-77'))
    expect(onSelect).toHaveBeenCalledWith(77)
  })

  it('shows org_count and global roles as lightweight summaries, not nested membership details', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow({ global_roles: ['platform_admin'], org_count: 3 })],
      total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('platform_admin')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  // ── PR11.1: filters + last login / auth method columns ────────────────

  it('shows the last login and authentication method columns', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow({ authentication_method: 'oidc' })], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')
    expect(screen.getByText('OIDC')).toBeInTheDocument()
  })

  it('shows "Not available" for a user with no login metadata yet', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow({ last_login_at: null, authentication_method: null })],
      total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')
    expect(screen.getAllByText('Not available')).toHaveLength(2)
  })

  it('re-fetches with organization_id when the organization filter changes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.selectOptions(await screen.findByLabelText('Filter by organization'), '9')

    await waitFor(() =>
      expect(users.fetchPlatformUsers).toHaveBeenLastCalledWith(expect.objectContaining({ organizationId: 9, page: 1 }))
    )
  })

  it('re-fetches with status when the status filter changes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'suspended')

    await waitFor(() =>
      expect(users.fetchPlatformUsers).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'suspended', page: 1 }))
    )
  })

  it('re-fetches with role when the role filter changes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.selectOptions(await screen.findByLabelText('Filter by role'), 'org_admin')

    await waitFor(() =>
      expect(users.fetchPlatformUsers).toHaveBeenLastCalledWith(expect.objectContaining({ role: 'org_admin', page: 1 }))
    )
  })

  it('omits organizationId/status/role entirely when no filter is selected (backward compatible)', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    const call = vi.mocked(users.fetchPlatformUsers).mock.calls[0][0]
    expect(call?.organizationId).toBeUndefined()
    expect(call?.status).toBeUndefined()
    expect(call?.role).toBeUndefined()
  })

  it('does not render the organization/role filter dropdowns when their catalogs fail to load', async () => {
    vi.mocked(organizations.fetchPlatformOrgs).mockRejectedValue(new Error('/platform/orgs 503'))
    vi.mocked(roles.fetchPlatformRoles).mockRejectedValue(new Error('/platform/roles 503'))
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    expect(screen.queryByLabelText('Filter by organization')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Filter by role')).not.toBeInTheDocument()
    // Status is a fixed, always-available list -- unaffected by either failure.
    expect(screen.getByLabelText('Filter by status')).toBeInTheDocument()
  })

  it('shows a filter-aware empty state when filters exclude everyone', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20, total_pages: 0,
    })
    const user = userEvent.setup()
    render(<UsersPage onSelect={vi.fn()} />)
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'suspended')
    expect(await screen.findByText('No users match these filters')).toBeInTheDocument()
  })
})
