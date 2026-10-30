import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import SidebarNav from './SidebarNav'

vi.mock('../../auth', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../auth')>(),
  hasPlatformAdminAccess: () => true,
}))

it('shows one Users item and no Tenant management item', () => {
  render(<SidebarNav active="users" onNavigate={() => {}} mobileOpen={false} onCloseMobile={() => {}} />)
  expect(screen.getAllByRole('button', { name: 'Users' })).toHaveLength(1)
  expect(screen.queryByRole('button', { name: 'Tenant management' })).not.toBeInTheDocument()
})
