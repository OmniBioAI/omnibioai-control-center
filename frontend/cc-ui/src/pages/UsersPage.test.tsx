import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UsersPage from './UsersPage'
import * as users from '../users'
import * as organizations from '../organizations'
import * as roles from '../roles'

vi.mock('../users', async () => {
  const actual = await vi.importActual<typeof import('../users')>('../users')
  return { ...actual, fetchManagedUsers: vi.fn() }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

vi.mock('../roles', async () => {
  const actual = await vi.importActual<typeof import('../roles')>('../roles')
  return { ...actual, fetchPlatformRoles: vi.fn() }
})

vi.mock('../tenants', async (original) => ({
  ...await original<typeof import('../tenants')>(), fetchTenantSummary: vi.fn().mockResolvedValue({
    tenants_total: 1, per_plan: { free: 0, plus: 1, pro: 0 }, allocated_sum_bytes: 20e9,
    used_sum_bytes: 2e9, pool_capacity_bytes: 100e9, expiring_7d: 0, past_due: 0,
    over_allocation: 0, promos_active: 0, promos_expiring_7d: 0,
  }),
}))
const tenantRow: import('../tenants').TenantRow = {
  tenant_id: '1', username: 'someone', email: 'someone@acme.test', plan_id: 'plus', membership_status: 'active', effective_plan_id: 'plus', plan_source: 'stripe', promo_expires_at: null,
  valid_from: null, valid_until: null, auto_renew: true, days_remaining: null,
  allocated_bytes: 20e9, allocation_source: 'plan', used_bytes: 2e9, reserved_bytes: 0,
  pct: 10, storage_status: 'ok', last_plan_change: null, last_activity_at: null,
}
const userRow = (overrides: Partial<users.ManagedUser> = {}): users.ManagedUser => ({
  ...tenantRow, id: 1, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [], org_count: 2, last_login_at: '2026-08-01T14:20:00Z', authentication_method: 'password',
  mfa_enabled: false,
  ...overrides,
})

describe('UsersPage', () => {
  beforeEach(() => {
    vi.mocked(users.fetchManagedUsers).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset()
    vi.mocked(roles.fetchPlatformRoles).mockReset()
    // Most tests don't care about the filter dropdowns' own contents --
    // default to a small resolved catalog of each so those dropdowns
    // render without every test needing to mock this itself. Tests that
    // DO care about the dropdowns override these explicitly.
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({
      items: [{ id: 9, name: 'Acme Corp', status: 'active', created_at: '2026-01-01T00:00:00', owner_email: null, member_count: 1, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false }],
      total: 1, page: 1, page_size: 100, total_pages: 1,
    })
    vi.mocked(roles.fetchPlatformRoles).mockResolvedValue([
      { id: 1, name: 'org_admin', description: null, permissions: [] },
    ])
  })

  it('lists users via Control Center aggregation', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('someone@acme.test')).toBeInTheDocument()
    expect(users.fetchManagedUsers).toHaveBeenCalled()
  })

  it('shows the loading state before data resolves', async () => {
    vi.mocked(users.fetchManagedUsers).mockReturnValue(new Promise(() => {}))
    render(<UsersPage onSelect={vi.fn()} />)
    expect(screen.getByText(/Loading users/)).toBeInTheDocument()
    // Flushes the (resolved) org/role filter-catalog fetches before the
    // test ends, so their state updates land inside this async test
    // rather than warning after teardown.
    await waitFor(() => expect(organizations.fetchPlatformOrgs).toHaveBeenCalled())
  })

  it('shows the empty state when no users exist', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20, total_pages: 0,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('No users exist yet.')).toBeInTheDocument()
  })

  it('shows the error state when the request fails', async () => {
    vi.mocked(users.fetchManagedUsers).mockRejectedValue(new Error('/platform/users 500'))
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('/platform/users 500')
  })

  it('re-fetches with the search term on submit', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.type(screen.getByLabelText('Search users'), 'acme')
    await user.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() =>
      expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'acme', page: 1 }))
    )
  })

  it('paginates using the total_pages/page from the response', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 40, page: 1, page_size: 20, total_pages: 2,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.click(screen.getByRole('button', { name: /Next/ }))

    await waitFor(() => expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })))
  })

  it('sorts by clicking a sortable column header', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.click(screen.getByRole('button', { name: /Email/ }))

    await waitFor(() =>
      expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(
        expect.objectContaining({ sortBy: 'email', sortOrder: 'asc' })
      )
    )
  })

  it('invokes onSelect with the user id when a row is clicked', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow({ id: 77 })], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={onSelect} />)
    await user.click(await screen.findByTestId('user-row-77'))
    expect(onSelect).toHaveBeenCalledWith(77)
  })

  // PR E2: rows were mouse-only before (no role, no tabIndex, no key
  // handler) -- this proves the keyboard-equivalent path actually works,
  // not just that the attributes are present.
  it('invokes onSelect when a row is focused and Enter is pressed', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow({ id: 77 })], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={onSelect} />)
    const row = await screen.findByTestId('user-row-77')
    row.focus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(77)
  })

  it('shows org_count and global roles as lightweight summaries, not nested membership details', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow({ global_roles: ['platform_admin'], org_count: 3 })],
      total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('platform_admin')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  // ── PR11.1: filters + last login / auth method columns ────────────────

  it('shows the last login and authentication method columns', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow({ authentication_method: 'oidc' })], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')
    expect(screen.getByText('OIDC')).toBeInTheDocument()
  })

  it('shows "Not available" for a user with no login metadata yet', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow({ last_login_at: null, authentication_method: null })],
      total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')
    expect(screen.getAllByText('Not available')).toHaveLength(2)
  })

  it('re-fetches with organization_id when the organization filter changes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.selectOptions(await screen.findByLabelText('Filter by organization'), '9')

    await waitFor(() =>
      expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(expect.objectContaining({ organizationId: 9, page: 1 }))
    )
  })

  it('re-fetches with status when the status filter changes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'suspended')

    await waitFor(() =>
      expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'suspended', page: 1 }))
    )
  })

  it('re-fetches with role when the role filter changes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    await user.selectOptions(await screen.findByLabelText('Filter by role'), 'org_admin')

    await waitFor(() =>
      expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(expect.objectContaining({ role: 'org_admin', page: 1 }))
    )
  })

  it('omits organizationId/status/role entirely when no filter is selected (backward compatible)', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')

    const call = vi.mocked(users.fetchManagedUsers).mock.calls[0][0]
    expect(call?.organizationId).toBeUndefined()
    expect(call?.status).toBeUndefined()
    expect(call?.role).toBeUndefined()
  })

  it('does not render the organization/role filter dropdowns when their catalogs fail to load', async () => {
    vi.mocked(organizations.fetchPlatformOrgs).mockRejectedValue(new Error('/platform/orgs 503'))
    vi.mocked(roles.fetchPlatformRoles).mockRejectedValue(new Error('/platform/roles 503'))
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
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
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 20, total_pages: 0,
    })
    const user = userEvent.setup()
    render(<UsersPage onSelect={vi.fn()} />)
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'suspended')
    expect(await screen.findByText('No users match these filters')).toBeInTheDocument()
  })
  it('sends all plan filters and exports the same filter in pages of at most 200', async () => {
    vi.mocked(users.fetchManagedUsers).mockResolvedValue({ items: [userRow()], total: 1, page: 1, page_size: 50, total_pages: 1 })
    const user = userEvent.setup()
    render(<UsersPage onSelect={vi.fn()} />)
    await screen.findByText('someone@acme.test')
    for (const [label, value] of [['Plan', 'pro'], ['Plan source', 'promo'], ['Membership', 'active'], ['Validity', 'expiring_7d'], ['Storage', 'near']]) {
      await user.selectOptions(screen.getByLabelText(label), value)
    }
    const tenant = { plan: 'pro', plan_source: 'promo', status: 'active', validity: 'expiring_7d', storage_status: 'near' }
    await waitFor(() => expect(users.fetchManagedUsers).toHaveBeenLastCalledWith(expect.objectContaining({ tenant, page: 1, pageSize: 50 })))
    const create = vi.fn(() => 'blob:test')
    const revoke = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: create })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoke })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.mocked(users.fetchManagedUsers).mockClear()
    vi.mocked(users.fetchManagedUsers).mockResolvedValueOnce({ items: [userRow()], total: 201, page: 1, page_size: 200, total_pages: 2 })
      .mockResolvedValueOnce({ items: [userRow({ id: 2 })], total: 201, page: 2, page_size: 200, total_pages: 2 })
    await user.click(screen.getByRole('button', { name: 'Export current filter' }))
    await waitFor(() => expect(click).toHaveBeenCalledOnce())
    expect(users.fetchManagedUsers).toHaveBeenNthCalledWith(1, expect.objectContaining({ tenant, page: 1, pageSize: 200 }))
    expect(users.fetchManagedUsers).toHaveBeenNthCalledWith(2, expect.objectContaining({ tenant, page: 2, pageSize: 200 }))
    expect(revoke).toHaveBeenCalledWith('blob:test')
    click.mockRestore()
  })

})
