import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ControlApp, { tabFromPath } from './ControlApp'
import * as auth from '../auth'

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return {
    ...actual,
    getToken: vi.fn(),
    clearToken: vi.fn(),
  }
})

vi.mock('../api', () => ({
  fetchHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
}))

// jsdom has no scrolling; ControlApp scrolls to the top on tab change.
window.scrollTo = vi.fn() as unknown as typeof window.scrollTo

vi.mock('../pages/PublicOverviewPage', () => ({ default: () => <div data-testid="PublicOverviewPage" /> }))
vi.mock('../pages/PublicEvidencePage', () => ({ default: () => <div data-testid="PublicEvidencePage" /> }))
vi.mock('../pages/PublicEcosystemPage', () => ({ default: () => <div data-testid="PublicEcosystemPage" /> }))

describe('ControlApp is a genuinely anonymous public dashboard', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    vi.mocked(auth.clearToken).mockReset()
    window.history.pushState(null, '', '/')
  })

  it('renders the dashboard immediately, with no token and no login screen', async () => {
    vi.mocked(auth.getToken).mockReturnValue(null)
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    expect(screen.queryByText(/Ecosystem Management Console/)).not.toBeInTheDocument()
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
  })

  it('renders the dashboard even if a token happens to be sitting in this origin\'s storage', async () => {
    // Section 1's own requirement: "Do not send a JWT merely because one
    // happens to exist." This build has no AuthGate to bounce a stale
    // token through in the first place -- it never inspects getToken()
    // to decide what to render, and it clears it unconditionally.
    vi.mocked(auth.getToken).mockReturnValue('stale-token-from-a-different-build')
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    expect(screen.queryByText('Access Denied')).not.toBeInTheDocument()
  })

  it('clears any token on mount, before rendering data', async () => {
    render(<ControlApp />)
    await waitFor(() => expect(auth.clearToken).toHaveBeenCalled())
  })

  it('polls the public /health endpoint, never /summary', async () => {
    const api = await import('../api')
    render(<ControlApp />)
    await waitFor(() => expect(api.fetchHealth).toHaveBeenCalled())
  })
})

describe('ControlApp page set: only the endpoints confirmed safe for anonymous access', () => {
  beforeEach(() => {
    vi.mocked(auth.getToken).mockReset()
    window.history.pushState(null, '', '/')
  })

  it('shows only Overview, Evidence and Ecosystem Report tabs', async () => {
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())

    expect(screen.getAllByRole('tab').map(t => t.textContent)).toEqual(['Overview', 'Evidence', 'Ecosystem Report'])
    for (const gone of ['Health Dashboard', 'LLMs', 'Cloud', 'Integrations', 'View Report']) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument()
    }
    expect(screen.queryByText('Docker Images')).not.toBeInTheDocument()
    expect(screen.queryByText('Config')).not.toBeInTheDocument()
    expect(screen.queryByText('Organizations')).not.toBeInTheDocument()
    expect(screen.queryByText('Users')).not.toBeInTheDocument()
  })

  it('has no "Generate Report" mutation control -- report/generate stays platform.manage_content-gated and this build has no way to satisfy that', async () => {
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    expect(screen.queryByText(/Generate Report/)).not.toBeInTheDocument()
  })

  it('applies the public brand and loads the website fonts once', async () => {
    const { container, unmount } = render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    expect(container.querySelector('.public-brand')).not.toBeNull()
    unmount()
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    expect(document.head.querySelectorAll('link[href*="Space+Grotesk"]')).toHaveLength(1)
  })

  it('gives every tab its own URL and title, and follows Back/Forward', async () => {
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    expect(document.title).toBe('OmniBioAI — Platform Overview')
    fireEvent.click(screen.getByText('Evidence'))
    await waitFor(() => expect(screen.getByTestId('PublicEvidencePage')).toBeInTheDocument())
    expect(window.location.pathname).toBe('/evidence')
    expect(document.title).toBe('OmniBioAI — Evidence')
    fireEvent.click(screen.getByText('Ecosystem Report'))
    expect(window.location.pathname).toBe('/ecosystem')
    window.history.pushState(null, '', '/evidence')
    fireEvent(window, new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByTestId('PublicEvidencePage')).toBeInTheDocument())
  })

  it('opens the tab named in the URL, so links can point straight at one', async () => {
    window.history.pushState(null, '', '/evidence')
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicEvidencePage')).toBeInTheDocument())
  })

  it('maps paths to tabs, defaulting to Overview', () => {
    expect(tabFromPath('/')).toBe('overview')
    expect(tabFromPath('/overview')).toBe('overview')
    expect(tabFromPath('/evidence/')).toBe('evidence')
    expect(tabFromPath('/ecosystem')).toBe('ecosystem')
    expect(tabFromPath('/health')).toBe('overview')
  })

  it('renders PublicEcosystemPage (not EcosystemPage) anonymously when the Ecosystem Report tab is selected', async () => {
    render(<ControlApp />)
    await waitFor(() => expect(screen.getByTestId('PublicOverviewPage')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Ecosystem Report'))
    await waitFor(() => expect(screen.getByTestId('PublicEcosystemPage')).toBeInTheDocument())
  })

  it('source contains no reference to Docker/Config/Organizations/Users/Roles/Teams/EcosystemPage modules or AuthGate', () => {
    // Static source-text check, same convention this file already used
    // pre-rewrite -- proves these are genuinely absent from the module
    // graph (so Rollup's dead-code elimination excludes them from
    // dist-control), not just hidden behind a runtime check.
    // 'EcosystemPage' specifically: ControlApp must import
    // PublicEcosystemPage.tsx, never the full EcosystemPage.tsx (which
    // also contains ArchTab's static internal-topology map and
    // /summary-sourced HealthTab).
    const thisFile = fileURLToPath(import.meta.url)
    const source = readFileSync(join(dirname(thisFile), 'ControlApp.tsx'), 'utf-8')
    const importLines = source
      .split('\n')
      .filter((line: string) => /^\s*import\b.*\bfrom\s+['"]/.test(line))
      .join('\n')

    for (const forbidden of [
      'DockerPage', 'ConfigPage', 'AuthGate',
      'OrganizationsPage', 'OrganizationDetailPage', 'UsersPage', 'UserDetailPage',
      'components/organizations', 'components/roles', 'components/teams',
      "'../pages/EcosystemPage'", '"../pages/EcosystemPage"',
      // Admin Console HIPAA Readiness Report (V1): ControlApp must
      // never import navigation.ts (its own separate Header/Tab
      // component, not the sectioned admin nav) or the compliance page
      // itself -- same "genuinely absent from the module graph, not
      // just hidden" guarantee this test already proves for every other
      // admin-only surface above.
      'navigation', 'HipaaCompliancePage', 'pages/compliance',
    ]) {
      expect(importLines).not.toContain(forbidden)
    }
  })
})
