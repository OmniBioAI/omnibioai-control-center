import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AppShell from './AppShell'

describe('AppShell content area', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  function renderShell(children: React.ReactNode) {
    return render(
      <AppShell active="overview" onNavigate={() => {}} user={null} onSignOut={() => {}}>
        {children}
      </AppShell>,
    )
  }

  it('pads every page from the sidebar and top bar in one place', () => {
    renderShell(<h1>Some page</h1>)
    const main = screen.getByRole('main')
    expect(main).toContainElement(screen.getByRole('heading', { name: 'Some page' }))
    expect(main.style.padding).toBe('24px 32px 48px')
    expect(main.style.maxWidth).toBe('')   // full width, not a centered box
  })

  it('keeps the shell when a page throws', () => {
    function Broken(): never { throw new Error('boom') }
    renderShell(<Broken />)
    expect(screen.getByRole('main')).toHaveTextContent(/This page couldn't be displayed/)
    expect(screen.getAllByText('Overview').length).toBeGreaterThan(0)   // sidebar still rendered
  })
})
