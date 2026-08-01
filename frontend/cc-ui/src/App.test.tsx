import { act, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import App from './App'
import * as auth from './auth'
import type { SessionUser } from './auth'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return {
    ...actual,
    getToken: vi.fn(),
    clearToken: vi.fn(),
    ensureSession: vi.fn(),
    hasAdminAccess: vi.fn(),
  }
})

vi.mock('./api', () => ({
  fetchSummary: vi.fn().mockResolvedValue({ overall_status: 'UP' }),
  fetchReportStatus: vi.fn().mockResolvedValue({ report_exists: false, status: 'idle' }),
  triggerGenerate: vi.fn(),
}))

// Dashboard's page components do their own network fetching / chart
// rendering (recharts needs a ResizeObserver jsdom doesn't provide) --
// irrelevant to what this file is testing, which is the auth gate above
// Dashboard, not Dashboard's contents. vi.mock calls are hoisted above
// this module's own code, so each target must be a static string literal
// (no loop over a runtime array of names).
vi.mock('./pages/HealthPage', () => ({ default: () => <div data-testid="HealthPage" /> }))
vi.mock('./pages/DockerPage', () => ({ default: () => <div data-testid="DockerPage" /> }))
vi.mock('./pages/EcosystemPage', () => ({ default: () => <div data-testid="EcosystemPage" /> }))
vi.mock('./pages/ConfigPage', () => ({ default: () => <div data-testid="ConfigPage" /> }))
vi.mock('./pages/LlmPage', () => ({ default: () => <div data-testid="LlmPage" /> }))
vi.mock('./pages/CloudPage', () => ({ default: () => <div data-testid="CloudPage" /> }))

const admin: SessionUser = {
  userId: '1', email: 'admin@omnibioai.org', roles: ['admin'],
  permissions: ['manage_config'], orgId: null, orgRoles: [], schemaVersion: 2,
}
const nonAdmin: SessionUser = {
  userId: '2', email: 'no-perms@omnibioai.org', roles: ['user'],
  permissions: [], orgId: null, orgRoles: [], schemaVersion: 2,
}

describe('App auth gate', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    vi.mocked(auth.ensureSession).mockReset()
    vi.mocked(auth.hasAdminAccess).mockReset()
  })

  it('shows the login screen when there is no token', async () => {
    vi.mocked(auth.getToken).mockReturnValue(null)
    render(<App />)
    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })

  it('shows Access Denied for an authenticated non-admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-123')
    vi.mocked(auth.ensureSession).mockResolvedValue(nonAdmin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)

    render(<App />)
    expect(
      await screen.findByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
    expect(screen.getByText(/no-perms@omnibioai\.org/)).toBeInTheDocument()
  })

  it('renders the dashboard for an authenticated admin user', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-456')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<App />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
  })

  it('drops back to the login screen when a gated request reports 401', async () => {
    vi.mocked(auth.getToken).mockReturnValue('token-789')
    vi.mocked(auth.ensureSession).mockResolvedValue(admin)
    vi.mocked(auth.hasAdminAccess).mockReturnValue(true)

    render(<App />)
    await waitFor(() => expect(screen.getByTestId('HealthPage')).toBeInTheDocument())

    act(() => {
      window.dispatchEvent(new Event(auth.UNAUTHORIZED_EVENT))
    })

    expect(await screen.findByText(/Ecosystem Management Console/)).toBeInTheDocument()
  })
})
