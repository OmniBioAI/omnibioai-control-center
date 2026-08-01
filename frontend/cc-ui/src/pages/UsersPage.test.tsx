import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UsersPage from './UsersPage'
import * as users from '../users'

vi.mock('../users', async () => {
  const actual = await vi.importActual<typeof import('../users')>('../users')
  return { ...actual, fetchPlatformUsers: vi.fn() }
})

const userRow = (overrides: Partial<users.PlatformUserSummary> = {}): users.PlatformUserSummary => ({
  id: 1, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [], org_count: 2, ...overrides,
})

describe('UsersPage', () => {
  beforeEach(() => {
    vi.mocked(users.fetchPlatformUsers).mockReset()
  })

  it('lists users via GET /platform/users', async () => {
    vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
      items: [userRow()], total: 1, page: 1, page_size: 20, total_pages: 1,
    })
    render(<UsersPage onSelect={vi.fn()} />)
    expect(await screen.findByText('someone@acme.test')).toBeInTheDocument()
    expect(users.fetchPlatformUsers).toHaveBeenCalled()
  })

  it('shows the loading state before data resolves', () => {
    vi.mocked(users.fetchPlatformUsers).mockReturnValue(new Promise(() => {}))
    render(<UsersPage onSelect={vi.fn()} />)
    expect(screen.getByText(/Loading users/)).toBeInTheDocument()
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
})
