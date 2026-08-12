import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { act, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ControlApp from './ControlApp'
import * as auth from '../auth'
import type { SessionUser } from '../auth'

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return {
    ...actual,
    getToken: vi.fn(),
    clearToken: vi.fn(),
    ensureSession: vi.fn(),
    hasAdminAccess: vi.fn(),
  }
})

vi.mock('../api', () => ({
  fetchSummary: vi.fn().mockResolvedValue({ overall_status: 'UP' }),
  fetchReportStatus: vi.fn().mockResolvedValue({ report_exists: false, status: 'idle' }),
  triggerGenerate: vi.fn(),
}))

vi.mock('../pages/HealthPage', () => ({ default: () => <div data-testid="HealthPage" /> }))
vi.mock('../pages/DockerPage', () => ({ default: () => <div data-testid="DockerPage" /> }))
vi.mock('../pages/EcosystemPage', () => ({ default: () => <div data-testid="EcosystemPage" /> }))
vi.mock('../pages/ConfigPage', () => ({ default: () => <div data-testid="ConfigPage" /> }))
vi.mock('../pages/LlmPage', () => ({ default: () => <div data-testid="LlmPage" /> }))
vi.mock('../pages/CloudPage', () => ({ default: () => <div data-testid="CloudPage" /> }))

const admin: SessionUser = {
  userId: '1', email: 'admin@omnibioai.org', roles: ['admin'],
  permissions: ['manage_config'], orgId: null, orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
}
const nonAdmin: SessionUser = {
  userId: '2', email: 'no-perms@omnibioai.org', roles: ['user'],
  permissions: [], orgId: null, orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
}
const orgOnlyUser: SessionUser = {
  userId: '3', email: 'org-admin@acme.test', roles: ['user'],
  permissions: ['manage_org'], orgId: '9', orgRoles: ['org_admin'], teamId: null, teamRole: null, schemaVersion: 2,
}

describe('ControlApp auth gate (existing behavior, unchanged)', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    vi.mocked(auth.ensureSession).mockReset()
    vi.mocked(auth.hasAdminAccess).mockReset()
    window.history.pushState(null, '', '/')
  })

  it('shows the login screen when there is no token', async () => {
    vi.mocked(auth.getToken).mockReturnValue(null)
    render(<ControlApp />)
    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  it('shows Access Denied for an authenticated non-admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-123')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)

    render(<ControlApp />)
    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
  })

  it('denies an org-only user with no global admin role -- ControlApp has no ops-adjacent audience for them', async () => {
    // Unlike AdminApp (which widens the gate to hasOrganizationsAccess()),
    // ControlApp's audience is hasAdminAccess() alone -- an org_admin has
    // nothing to see in an ops-only build.
    vi.mocked(auth.getToken).mockReturnValue('token-org')
    vi.mocked(auth.ensureSession).mockResolvedValue(orgOnlyUser)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)

    render(<ControlApp />)

    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
  })

  it('renders the ops dashboard for an authenticated admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
  })

  it('drops back to the login screen when a gated request reports 401', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-789')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())

    act(() => {
      window.dispatchEvent(new Event(auth.UNAUTHORIZED_EVENT))
    })

    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })
})

describe('ControlApp does not expose enterprise console functionality', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    vi.mocked(auth.ensureSession).mockReset()
    vi.mocked(auth.hasAdminAccess).mockReset()
    window.history.pushState(null, '', '/')
  })

  it('shows only ops tabs in the nav -- no Organizations or Users tab', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())

    expect(screen.getByText('Health Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Docker Images')).toBeInTheDocument()
    expect(screen.queryByText('Organizations')).not.toBeInTheDocument()
    expect(screen.queryByText('Users')).not.toBeInTheDocument()
  })

  it('never renders Organizations/Users page content, even navigating to those deep-link URLs', async () => {
    // ControlApp has no deep-link handling for /organizations or /users
    // at all (that logic lives only in AdminApp) -- visiting those paths
    // must still land on the ops dashboard, not attempt to render
    // enterprise content this build doesn't have.
    window.history.pushState(null, '', '/organizations/42')
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<ControlApp />)

    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())
    expect(screen.queryByTestId('OrganizationsPage')).not.toBeInTheDocument()
    expect(screen.queryByTestId('OrganizationDetailPage')).not.toBeInTheDocument()
  })

  it('source contains no reference to Organizations/Users/Roles/Teams modules', () => {
    // The render tests above prove nothing renders; they can't prove the
    // code isn't bundled (vi.mock would intercept an import even if one
    // existed). This is the actual "genuinely absent from the module
    // graph" check -- a static source-text assertion that ControlApp.tsx
    // never imports the enterprise-console modules at all, which is what
    // lets Rollup's dead-code elimination exclude them from dist-control.
    // See docs/admin-console-build.md for the real-build verification
    // this test's assumption is checked against.
    // Only the import statements matter for what actually ships in the
    // bundle -- explanatory prose in this file's own doc comment
    // necessarily *names* these modules to say they're absent, so
    // scanning the whole file text would trip on its own documentation.
    const thisFile = fileURLToPath(import.meta.url)
    const source = readFileSync(join(dirname(thisFile), 'ControlApp.tsx'), 'utf-8')
    const importLines = source
      .split('\n')
      .filter((line: string) => /^\s*import\b.*\bfrom\s+['"]/.test(line))
      .join('\n')

    for (const forbidden of [
      'OrganizationsPage', 'OrganizationDetailPage', 'UsersPage', 'UserDetailPage',
      'components/organizations', 'components/roles', 'components/teams',
    ]) {
      expect(importLines).not.toContain(forbidden)
    }
  })
})
