import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as auth from '../../auth'
import * as orgs from '../../organizations'
import * as users from '../../users'
import GlobalSearch, { matchPages, searchablePages } from './GlobalSearch'

vi.mock('../../organizations', () => ({ fetchPlatformOrgs: vi.fn() }))
vi.mock('../../users', () => ({ fetchPlatformUsers: vi.fn() }))

vi.mock('../../auth', async (orig) => {
  const actual = await orig<typeof import('../../auth')>()
  return { ...actual, hasPlatformAdminAccess: vi.fn(() => true), hasOrganizationsAccess: vi.fn(() => true), hasAdminAccess: vi.fn(() => true) }
})

describe('GlobalSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
  })

  it('ranks name matches before section matches', () => {
    const results = matchPages(searchablePages(), 'hipaa').map(r => r.label)
    expect(results.slice(0, 2)).toEqual(['HIPAA Readiness', 'HIPAA Audit Report'])
    const security = matchPages(searchablePages(), 'security').map(r => r.label)
    expect(security).toContain('MFA Policy')   // matched by its section
  })

  it('only offers pages the session can see', () => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    const labels = searchablePages().map(r => r.label)
    expect(labels).not.toContain('HIPAA Readiness')
    expect(labels).toContain('Sessions')
  })

  it('opens with Ctrl+K, filters as you type, and opens the page on Enter', () => {
    const onNavigate = vi.fn()
    render(<GlobalSearch onNavigate={onNavigate} />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const input = screen.getByRole('combobox', { name: 'Search pages' })
    fireEvent.change(input, { target: { value: 'llm' } })
    expect(screen.getByRole('option', { name: /LLMs/ })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onNavigate).toHaveBeenCalledWith('llms')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('moves with arrow keys, says when nothing matches, and closes on Escape', () => {
    const onNavigate = vi.fn()
    render(<GlobalSearch onNavigate={onNavigate} />)
    fireEvent.click(screen.getByRole('button', { name: /Search/ }))
    const input = screen.getByRole('combobox', { name: 'Search pages' })
    fireEvent.change(input, { target: { value: 'audit' } })
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onNavigate).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: /Search/ }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Search pages' }), { target: { value: 'zzzz' } })
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Search pages' }), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  describe('organizations and users', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      vi.mocked(orgs.fetchPlatformOrgs).mockResolvedValue({
        items: [{ id: 7, name: 'KUMC Research', member_count: 12 }], total: 1, page: 1, page_size: 5, total_pages: 1,
      } as never)
      vi.mocked(users.fetchPlatformUsers).mockResolvedValue({
        items: [{ id: 42, email: 'kumar@kumc.edu', status: 'active' }], total: 1, page: 1, page_size: 5, total_pages: 1,
      } as never)
    })
    afterEach(() => vi.useRealTimers())

    async function typeAndSettle(value: string) {
      fireEvent.change(screen.getByRole('combobox', { name: 'Search pages' }), { target: { value } })
      await act(async () => { await vi.advanceTimersByTimeAsync(300) })
    }

    it('finds organizations and users by name/email and opens their detail page', async () => {
      const onOpenRecord = vi.fn()
      render(<GlobalSearch onNavigate={vi.fn()} onOpenRecord={onOpenRecord} />)
      fireEvent.click(screen.getByRole('button', { name: /Search/ }))
      await typeAndSettle('kum')

      expect(orgs.fetchPlatformOrgs).toHaveBeenCalledWith(expect.objectContaining({ search: 'kum', pageSize: 5 }))
      expect(users.fetchPlatformUsers).toHaveBeenCalledWith(expect.objectContaining({ search: 'kum', pageSize: 5 }))
      expect(screen.getByText('Organizations & users')).toBeInTheDocument()
      expect(screen.getByRole('option', { name: /KUMC Research/ })).toBeInTheDocument()

      fireEvent.mouseDown(screen.getByRole('option', { name: /kumar@kumc.edu/ }))
      expect(onOpenRecord).toHaveBeenCalledWith('user', 42)
    })

    it('waits for two characters and debounces typing into one request', async () => {
      render(<GlobalSearch onNavigate={vi.fn()} onOpenRecord={vi.fn()} />)
      fireEvent.click(screen.getByRole('button', { name: /Search/ }))
      await typeAndSettle('k')
      expect(orgs.fetchPlatformOrgs).not.toHaveBeenCalled()

      fireEvent.change(screen.getByRole('combobox', { name: 'Search pages' }), { target: { value: 'ku' } })
      fireEvent.change(screen.getByRole('combobox', { name: 'Search pages' }), { target: { value: 'kum' } })
      await act(async () => { await vi.advanceTimersByTimeAsync(300) })
      expect(orgs.fetchPlatformOrgs).toHaveBeenCalledTimes(1)
    })

    it('does not search records for non-platform admins or without a handler', async () => {
      vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
      const { unmount } = render(<GlobalSearch onNavigate={vi.fn()} onOpenRecord={vi.fn()} />)
      fireEvent.click(screen.getByRole('button', { name: /Search/ }))
      await typeAndSettle('kum')
      unmount()

      vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
      render(<GlobalSearch onNavigate={vi.fn()} />)
      fireEvent.click(screen.getByRole('button', { name: /Search/ }))
      await typeAndSettle('kum')
      expect(orgs.fetchPlatformOrgs).not.toHaveBeenCalled()
      expect(users.fetchPlatformUsers).not.toHaveBeenCalled()
    })
  })
})
