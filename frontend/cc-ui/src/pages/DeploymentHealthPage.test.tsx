import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DeploymentHealthPage from './DeploymentHealthPage'
import { fetchDeploymentHealth } from '../api'
import type { DeploymentServiceView } from '../api'

vi.mock('../api', () => ({ fetchDeploymentHealth: vi.fn() }))

function service(overrides: Partial<DeploymentServiceView> = {}): DeploymentServiceView {
  return {
    service_id: 'svc',
    display_name: 'Svc',
    category: 'execution',
    repository: 'omnibioai-svc',
    deployment: {
      image: {
        raw: 'omnibioai-svc:1.0', registry: null, repository: 'omnibioai-svc', tag: '1.0',
        digest: null, has_variable: false, is_untagged: false, is_latest_tag: false,
      },
      build_configured: true,
      healthcheck_configured: false,
      ports: [8080],
    },
    runtime: { present: true, running: true, docker_health: 'healthy', image: 'omnibioai-svc:1.0', match_evidence: null },
    health: {
      intrinsic: 'healthy',
      intrinsic_evidence: { source: 'docker_inspect', detail: 'docker healthcheck healthy' },
      effective: 'healthy',
      effective_evidence: [],
    },
    image_comparison: { status: 'match', configured: 'omnibioai-svc:1.0', running: 'omnibioai-svc:1.0' },
    dependencies: [],
    evidence: [{ source: 'compose_service', detail: "service 'svc' defined in compose" }],
    completeness: { repository_known: true, category_known: true, dependencies_known: true, missing_fields: [], is_complete: true },
    ...overrides,
  }
}

function response(services: DeploymentServiceView[] = [service()]) {
  const counts = { healthy: 0, degraded: 0, unhealthy: 0, unknown: 0 }
  for (const s of services) counts[s.health.effective]++
  return {
    generated_at: '2026-08-30T12:00:00Z',
    baseline: 'development',
    summary: { total: services.length, ...counts },
    services,
    regression_health: { availability: 'unavailable', phases: null, freshness: null },
    data_sources: { compose: 'available', docker: 'available', application_probe: 'available', prometheus: 'not_configured', regression_health: 'unavailable' },
    warnings: [],
  }
}

// StatusBadge renders the raw status string it's given (DH-2's own
// lowercase enum values, e.g. "healthy") -- text-transform: uppercase in
// its inline style is CSS-only presentation, not a DOM text change, so
// every assertion below matches DH-2's real lowercase values, not the
// visually-uppercased rendering.

describe('DeploymentHealthPage', () => {
  // Async, not a plain sync callback -- see the comment above the 401/
  // 403/503/network-error tests below for why this specific combination
  // (a beforeEach mock reset + a rejected mock + act()) needs the extra
  // hook-lifecycle synchronization point an async beforeEach provides.
  beforeEach(async () => { vi.mocked(fetchDeploymentHealth).mockReset() })

  it('shows a loading state, then the summary and data sources', async () => {
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response() as any)
    render(<DeploymentHealthPage />)
    expect(screen.getByText('Loading deployment health…')).toBeInTheDocument()
    expect(await screen.findByText('Total Services')).toBeInTheDocument()
    expect(screen.getByText('Evidence / Data Sources')).toBeInTheDocument()
    expect(screen.getByText('Application Probe')).toBeInTheDocument()
  })

  it('renders summary counts from the real API response, not hardcoded', async () => {
    const services = [
      service({ service_id: 'a', display_name: 'A', health: { intrinsic: 'healthy', intrinsic_evidence: { source: 'docker_inspect', detail: 'x' }, effective: 'healthy', effective_evidence: [] } }),
      service({ service_id: 'b', display_name: 'B', health: { intrinsic: 'degraded', intrinsic_evidence: { source: 'http_probe', detail: 'x' }, effective: 'degraded', effective_evidence: [] } }),
      service({ service_id: 'c', display_name: 'C', health: { intrinsic: 'unhealthy', intrinsic_evidence: { source: 'http_probe', detail: 'x' }, effective: 'unhealthy', effective_evidence: [] } }),
      service({ service_id: 'd', display_name: 'D', health: { intrinsic: 'unknown', intrinsic_evidence: { source: 'docker_inspect', detail: 'x' }, effective: 'unknown', effective_evidence: [] } }),
    ]
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response(services) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('Total Services')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
    // one of each count
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(4)
  })

  it('renders a healthy service', async () => {
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([service({ display_name: 'Auth' })]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('Auth')).toBeInTheDocument()
    expect(screen.getAllByText('healthy').length).toBeGreaterThan(0)
  })

  it('renders a degraded service', async () => {
    const svc = service({
      display_name: 'TES',
      health: { intrinsic: 'healthy', intrinsic_evidence: { source: 'http_probe', detail: 'up' }, effective: 'degraded', effective_evidence: [{ source: 'compose_depends_on', detail: 'hard dependency unhealthy: toolserver' }] },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('TES')).toBeInTheDocument()
    expect(screen.getByText('degraded')).toBeInTheDocument()
    expect(screen.getByText('hard dependency unhealthy: toolserver')).toBeInTheDocument()
  })

  it('renders an unhealthy service', async () => {
    const svc = service({
      display_name: 'ToolServer',
      health: { intrinsic: 'unhealthy', intrinsic_evidence: { source: 'http_probe', detail: 'application probe DOWN' }, effective: 'unhealthy', effective_evidence: [] },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('ToolServer')).toBeInTheDocument()
    expect(screen.getAllByText('unhealthy').length).toBeGreaterThan(0)
  })

  it('renders an unknown service without implying healthy or unhealthy', async () => {
    const svc = service({
      display_name: 'ControlCenter',
      health: { intrinsic: 'unknown', intrinsic_evidence: { source: 'docker_inspect', detail: 'container running, no healthcheck or probe evidence' }, effective: 'unknown', effective_evidence: [] },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('ControlCenter')).toBeInTheDocument()
    expect(screen.getAllByText('unknown').length).toBeGreaterThan(0)
    expect(screen.queryByText('healthy')).not.toBeInTheDocument()
    expect(screen.queryByText('unhealthy')).not.toBeInTheDocument()
  })

  it('keeps intrinsic and effective health visually distinct (hard requirement)', async () => {
    const svc = service({
      display_name: 'TES',
      health: {
        intrinsic: 'healthy',
        intrinsic_evidence: { source: 'http_probe', detail: 'application probe UP' },
        effective: 'degraded',
        effective_evidence: [{ source: 'compose_depends_on', detail: "hard dependency unhealthy: toolserver" }],
      },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    await screen.findByText('TES')
    // Both labels present -- never collapsed into one status.
    expect(screen.getByText('Intrinsic')).toBeInTheDocument()
    expect(screen.getByText('Effective')).toBeInTheDocument()
    expect(screen.getByText('healthy')).toBeInTheDocument()
    expect(screen.getByText('degraded')).toBeInTheDocument()
  })

  it('shows the hard-dependency degradation reason', async () => {
    const svc = service({
      display_name: 'TES',
      health: {
        intrinsic: 'healthy',
        intrinsic_evidence: { source: 'http_probe', detail: 'up' },
        effective: 'degraded',
        effective_evidence: [{ source: 'compose_depends_on', detail: 'hard dependency unhealthy: toolserver' }],
      },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('hard dependency unhealthy: toolserver')).toBeInTheDocument()
  })

  it('renders unknown ownership without implying the service is unhealthy', async () => {
    const svc = service({
      display_name: 'MySQL', repository: null,
      health: { intrinsic: 'healthy', intrinsic_evidence: { source: 'docker_inspect', detail: 'healthy' }, effective: 'healthy', effective_evidence: [] },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('Unknown ownership')).toBeInTheDocument()
    expect(screen.getAllByText('healthy').length).toBeGreaterThan(0)
  })

  it('renders metadata completeness', async () => {
    const complete = service({ service_id: 'a', display_name: 'Complete Svc' })
    const partial = service({
      service_id: 'b', display_name: 'Partial Svc', repository: null,
      completeness: { repository_known: false, category_known: true, dependencies_known: true, missing_fields: ['repository'], is_complete: false },
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([complete, partial]) as any)
    render(<DeploymentHealthPage />)
    await screen.findByText('Complete Svc')
    expect(screen.getByText('Complete')).toBeInTheDocument()
    expect(screen.getByText('Partial (repository)')).toBeInTheDocument()
  })

  it('renders evidence in the service detail panel', async () => {
    const svc = service({
      display_name: 'Auth',
      evidence: [
        { source: 'compose_service', detail: "service 'auth-service' defined in compose" },
        { source: 'compose_build_context', detail: "build context path segment matched 'omnibioai-auth'" },
      ],
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    fireEvent.click(await screen.findByText('Auth'))
    expect(await screen.findByText("build context path segment matched 'omnibioai-auth'")).toBeInTheDocument()
  })

  it('renders dependency visibility with relationship and target health', async () => {
    const svc = service({
      display_name: 'TES',
      dependencies: [{ to_service: 'toolserver', relationship: 'hard', target_intrinsic_health: 'unhealthy' }],
    })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    fireEvent.click(await screen.findByText('TES'))
    expect(await screen.findByText('toolserver')).toBeInTheDocument()
    expect(screen.getByText('hard')).toBeInTheDocument()
  })

  // These four use `await act(async () => render(...))` + a synchronous
  // getByText, not `findByText`'s own async polling -- findByText's
  // internal waitFor listens for globally-observed unhandled promise
  // rejections and can flag a rejection that a vi.mock()'d async
  // function settles one microtask turn later than expected, even
  // though this page's own .then().catch() does correctly handle it
  // (verified directly: the "ready"/ successful-response tests above,
  // and a standalone non-mocked reproduction, all resolve fine with
  // findByText). Wrapping render() in `act(async () => ...)` flushes
  // the effect's promise chain to completion before any assertion runs,
  // which sidesteps that polling-specific interaction entirely.
  it('handles a 401 as a session-expired state, not a permission error', async () => {
    vi.mocked(fetchDeploymentHealth).mockRejectedValue(new Error('/deployment-health/data 401'))
    await act(async () => { render(<DeploymentHealthPage />) })
    expect(screen.getByText('Session expired')).toBeInTheDocument()
  })

  it('handles a 403 as a permission-denied state', async () => {
    vi.mocked(fetchDeploymentHealth).mockRejectedValue(new Error('/deployment-health/data 403'))
    await act(async () => { render(<DeploymentHealthPage />) })
    expect(screen.getByText('You are not authorized to view deployment health.')).toBeInTheDocument()
  })

  it('handles a 503 as a safe unavailable state, never a default-healthy summary', async () => {
    vi.mocked(fetchDeploymentHealth).mockRejectedValue(new Error('/deployment-health/data 503'))
    await act(async () => { render(<DeploymentHealthPage />) })
    expect(screen.getByText('Deployment health data is unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('Total Services')).not.toBeInTheDocument()
  })

  it('handles an invalid response shape as unavailable', async () => {
    vi.mocked(fetchDeploymentHealth).mockResolvedValue({} as any)
    render(<DeploymentHealthPage />)
    await waitFor(() => expect(screen.getByText('Deployment health unavailable.')).toBeInTheDocument())
  })

  it('handles a network error as unavailable', async () => {
    vi.mocked(fetchDeploymentHealth).mockRejectedValue(new Error('Failed to fetch'))
    await act(async () => { render(<DeploymentHealthPage />) })
    expect(screen.getByText('Deployment health unavailable.')).toBeInTheDocument()
  })

  it('handles empty services with an explicit empty state, not an error', async () => {
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([]) as any)
    render(<DeploymentHealthPage />)
    expect(await screen.findByText('No services reported')).toBeInTheDocument()
    expect(screen.getByText('Total Services')).toBeInTheDocument()
  })

  it('contains no destructive or mutating controls', async () => {
    const svc = service({ display_name: 'Auth' })
    vi.mocked(fetchDeploymentHealth).mockResolvedValue(response([svc]) as any)
    render(<DeploymentHealthPage />)
    fireEvent.click(await screen.findByText('Auth'))
    await screen.findByText('Close')
    const forbidden = ['Restart', 'Stop', 'Start', 'Kill', 'Delete', 'Recreate', 'Deploy', 'Rollback', 'Scale', 'Cancel']
    for (const word of forbidden) {
      expect(screen.queryByText(word)).not.toBeInTheDocument()
    }
  })
})
