import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UserDetailPage from './UserDetailPage'
import * as users from '../users'
import type { PlatformUserDetail } from '../users'
import * as roles from '../roles'
import type { RoleSummary } from '../roles'

vi.mock('../users', async () => {
  const actual = await vi.importActual<typeof import('../users')>('../users')
  return { ...actual, fetchPlatformUserDetail: vi.fn(), setUserStatus: vi.fn() }
})

vi.mock('../roles', async () => {
  const actual = await vi.importActual<typeof import('../roles')>('../roles')
  return {
    ...actual,
    fetchPlatformRoles: vi.fn(),
    assignUserRole: vi.fn(),
    removeUserRole: vi.fn(),
  }
})

const roleCatalog: RoleSummary[] = [
  { id: 1, name: 'user', description: null, permissions: [] },
  { id: 2, name: 'admin', description: 'Global admin', permissions: ['manage_roles'] },
  { id: 3, name: 'platform_admin', description: null, permissions: ['manage_all_orgs'] },
]

const detail: PlatformUserDetail = {
  id: 42, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [],
  memberships: [
    { organization_id: 1, organization_name: 'Acme Corp', organization_slug: 'acme', roles: ['org_admin'], status: 'active', joined_at: '2026-07-16T09:00:00' },
    { organization_id: 2, organization_name: 'Beta Inc', organization_slug: 'beta', roles: ['org_member'], status: 'invited', joined_at: null },
  ],
  status_changed_at: null, status_changed_reason: null, status_changed_by_email: null,
  last_login_at: '2026-08-01T14:20:00Z', authentication_method: 'oidc',
  mfa_enabled: false, mfa_status: 'disabled', mfa_primary_method: null,
  mfa_enabled_at: null, mfa_last_verified_at: null, mfa_devices: [], mfa_recovery_codes_remaining: 0,
}

describe('UserDetailPage', () => {
  beforeEach(() => {
    vi.mocked(users.fetchPlatformUserDetail).mockReset()
    vi.mocked(roles.fetchPlatformRoles).mockReset()
    vi.mocked(roles.assignUserRole).mockReset()
    vi.mocked(roles.removeUserRole).mockReset()
    // Most tests in this file don't care about Global Roles -- default to
    // a resolved, empty-ish catalog so those tests don't have to mock it
    // themselves. Tests that DO care override this explicitly.
    vi.mocked(roles.fetchPlatformRoles).mockResolvedValue(roleCatalog)
  })

  it('reuses the PR3A detail response directly and displays org memberships', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue(detail)
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: 'someone@acme.test' })).toBeInTheDocument()
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('Beta Inc')).toBeInTheDocument()
    expect(screen.getByText('org_admin')).toBeInTheDocument()
    expect(screen.getByText('org_member')).toBeInTheDocument()
    expect(users.fetchPlatformUserDetail).toHaveBeenCalledWith(42)
  })

  it('shows an error state instead of crashing when the user cannot be loaded', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockRejectedValue(new Error('/platform/users/999 404'))
    render(<UserDetailPage userId={999} onBack={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('404')
  })

  it('shows a message instead of a table when the user has no memberships', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({ ...detail, memberships: [] })
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    expect(await screen.findByText('Not a member of any organization.')).toBeInTheDocument()
  })

  it('shows the suspend action and does not call the backend until confirmed', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue(detail)
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    expect(screen.getByRole('button', { name: 'Suspend User' })).toBeInTheDocument()
    expect(users.setUserStatus).not.toHaveBeenCalled()
  })

  // ── Phase 3 PR3B: Global Roles ────────────────────────────────────────

  it('shows a checkbox per catalog role, checked for roles the user already holds', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({ ...detail, global_roles: ['user'] })
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    const userCheckbox = await screen.findByRole('checkbox', { name: /^user\b/ })
    const adminCheckbox = screen.getByRole('checkbox', { name: /^admin\b/ })
    expect(userCheckbox).toBeChecked()
    expect(adminCheckbox).not.toBeChecked()
  })

  it('assigns a role when its checkbox is checked, then refreshes', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({ ...detail, global_roles: ['user'] })
    vi.mocked(roles.assignUserRole).mockResolvedValue([])
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    const adminCheckbox = await screen.findByRole('checkbox', { name: /^admin\b/ })
    await user.click(adminCheckbox)

    await waitFor(() => expect(roles.assignUserRole).toHaveBeenCalledWith(42, 'admin'))
    // Refreshes the whole detail via load() -- same onChanged pattern
    // UserStatusAction already established.
    await waitFor(() => expect(users.fetchPlatformUserDetail).toHaveBeenCalledTimes(2))
  })

  it('removes a role when its checkbox is unchecked', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({ ...detail, global_roles: ['user', 'admin'] })
    vi.mocked(roles.removeUserRole).mockResolvedValue(undefined)
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    const adminCheckbox = await screen.findByRole('checkbox', { name: /^admin\b/ })
    expect(adminCheckbox).toBeChecked()
    await user.click(adminCheckbox)

    await waitFor(() => expect(roles.removeUserRole).toHaveBeenCalledWith(42, 2))
  })

  it('shows an inline error and does not crash when a role assignment is rejected', async () => {
    const user = userEvent.setup()
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({ ...detail, global_roles: ['user'] })
    vi.mocked(roles.assignUserRole).mockRejectedValue(new Error('/platform/users/42/roles 403'))
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    const adminCheckbox = await screen.findByRole('checkbox', { name: /^admin\b/ })
    await user.click(adminCheckbox)

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
  })

  // ── PR11.1: login metadata (Identity Information + Security Summary) ──

  it('shows last login and authentication method, mapped to a display label', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue(detail)
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    const expectedLastLogin = new Date(detail.last_login_at!).toLocaleString(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
    // Rendered twice: once in General Information, once in the
    // Authentication (Security Summary) card.
    expect(screen.getAllByText('OIDC')).toHaveLength(2)
    expect(screen.getAllByText(expectedLastLogin)).toHaveLength(2)
  })

  it('shows "Not available" for a user who has never logged in since the migration', async () => {
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({
      ...detail, last_login_at: null, authentication_method: null,
    })
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    // Rendered twice each: General Information + the Authentication card,
    // plus 3 more from the MFA Status card (Primary Method/Enabled At/
    // Last Verified, all null on the shared `detail` fixture -- PR11.5.6).
    expect(screen.getAllByText('Not available')).toHaveLength(7)
  })

  it('falls back to a read-only role list when the role catalog fails to load', async () => {
    vi.mocked(roles.fetchPlatformRoles).mockRejectedValue(new Error('/platform/roles 503'))
    vi.mocked(users.fetchPlatformUserDetail).mockResolvedValue({ ...detail, global_roles: ['user'] })
    render(<UserDetailPage userId={42} onBack={vi.fn()} />)
    await screen.findByRole('heading', { name: 'someone@acme.test' })

    await waitFor(() => expect(screen.queryAllByRole('checkbox')).toHaveLength(0))
    expect(screen.getByText('user')).toBeInTheDocument()
  })
})
