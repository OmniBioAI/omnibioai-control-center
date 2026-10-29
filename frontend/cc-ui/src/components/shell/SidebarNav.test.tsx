import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import SidebarNav from './SidebarNav'

vi.mock('../../auth', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../auth')>(),
  hasPlatformAdminAccess: () => true,
}))

it('renders the tenant management icon with the same sizing and stroke as Users', () => {
  render(<SidebarNav active="tenants" onNavigate={() => {}} mobileOpen={false} onCloseMobile={() => {}} />)
  const tenantIcon = screen.getByRole('button', { name: 'Tenant management' }).querySelector('svg')
  const usersIcon = screen.getByRole('button', { name: 'Users' }).querySelector('svg')
  expect(tenantIcon).toHaveClass('lucide', 'lucide-user-cog')
  expect(tenantIcon).toHaveAttribute('width', '15')
  expect(tenantIcon).toHaveAttribute('aria-hidden', 'true')
  for (const attr of ['width', 'height', 'stroke', 'stroke-width']) {
    expect(tenantIcon?.getAttribute(attr)).toBe(usersIcon?.getAttribute(attr))
  }
})
