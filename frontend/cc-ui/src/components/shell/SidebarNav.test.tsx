import { fireEvent, render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SidebarNav from './SidebarNav'
import * as auth from '../../auth'

// PR-B7: regression coverage for the Infrastructure parent nav item.
// navigation.ts's 'infrastructure' entry is a navigation *group* (it has
// `children`), not a page -- AdminApp.tsx's renderPage() only has cases
// for its six children (health/docker/ecosystem/config/llms/cloud), none
// for 'infrastructure' itself. Before this fix, SidebarNav treated the
// group row exactly like any leaf row, so clicking it called
// onNavigate('infrastructure') and AdminApp's default case rendered
// <ComingSoon />. Uses the real NAVIGATION tree (same convention as
// navigation.test.ts) with only the auth gates this suite touches
// mocked, same pattern as apps/AdminApp.test.tsx.
vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return {
    ...actual,
    hasAdminAccess: vi.fn(),
    hasOrganizationsAccess: vi.fn(),
    hasPlatformAdminAccess: vi.fn(),
  }
})

function renderSidebar() {
  const onNavigate = vi.fn()
  render(<SidebarNav active="overview" onNavigate={onNavigate} mobileOpen={false} onCloseMobile={() => {}} />)
  return onNavigate
}

describe('SidebarNav: Infrastructure parent group', () => {
  beforeEach(() => {
    vi.mocked(auth.hasAdminAccess).mockReset().mockReturnValue(true)
    vi.mocked(auth.hasOrganizationsAccess).mockReset().mockReturnValue(false)
    vi.mocked(auth.hasPlatformAdminAccess).mockReset().mockReturnValue(false)
  })

  it('does not navigate when the Infrastructure parent row is clicked', () => {
    const onNavigate = renderSidebar()

    fireEvent.click(screen.getByText('Infrastructure'))

    expect(onNavigate).not.toHaveBeenCalled()
  })

  it.each([
    ['Health', 'health'],
    ['Docker', 'docker'],
    ['Ecosystem Report', 'ecosystem'],
    ['Config', 'config'],
    ['LLMs', 'llms'],
    ['Cloud', 'cloud'],
  ])('still navigates to %s when its child row is clicked', (label, key) => {
    const onNavigate = renderSidebar()

    fireEvent.click(screen.getByText(label))

    expect(onNavigate).toHaveBeenCalledWith(key)
    expect(onNavigate).toHaveBeenCalledTimes(1)
  })

  it('renders all six Infrastructure children alongside the inert parent', () => {
    renderSidebar()

    expect(screen.getByText('Infrastructure')).toBeInTheDocument()
    for (const label of ['Health', 'Docker', 'Ecosystem Report', 'Config', 'LLMs', 'Cloud']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })
})
