import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UserDetailPage from './UserDetailPage'
import * as users from '../users'
import type { PlatformUserDetail } from '../users'

vi.mock('../users', async () => {
  const actual = await vi.importActual<typeof import('../users')>('../users')
  return { ...actual, fetchPlatformUserDetail: vi.fn(), setUserStatus: vi.fn() }
})

const detail: PlatformUserDetail = {
  id: 42, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [],
  memberships: [
    { organization_id: 1, organization_name: 'Acme Corp', organization_slug: 'acme', roles: ['org_admin'], status: 'active', joined_at: '2026-07-16T09:00:00' },
    { organization_id: 2, organization_name: 'Beta Inc', organization_slug: 'beta', roles: ['org_member'], status: 'invited', joined_at: null },
  ],
  status_changed_at: null, status_changed_reason: null, status_changed_by_email: null,
}

describe('UserDetailPage', () => {
  beforeEach(() => {
    vi.mocked(users.fetchPlatformUserDetail).mockReset()
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
})
