import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as auth from '../../auth'
import GlobalSearch, { matchPages, searchablePages } from './GlobalSearch'

vi.mock('../../auth', async (orig) => {
  const actual = await orig<typeof import('../../auth')>()
  return { ...actual, hasPlatformAdminAccess: vi.fn(() => true), hasOrganizationsAccess: vi.fn(() => true), hasAdminAccess: vi.fn(() => true) }
})

describe('GlobalSearch', () => {
  beforeEach(() => vi.clearAllMocks())

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
    expect(screen.getByText(/No pages match/)).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Search pages' }), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
