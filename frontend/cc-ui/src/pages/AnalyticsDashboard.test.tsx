import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AnalyticsDashboard from './AnalyticsDashboard'
import * as analytics from '../analytics'
import type {
  AnalyticsOverview, AnalyticsPerformance, AnalyticsServices, AnalyticsUsers,
} from '../analytics'
import * as auth from '../auth'
import * as organizations from '../organizations'
import type { PlatformOrgSummary } from '../organizations'

vi.mock('../analytics', async () => {
  const actual = await vi.importActual<typeof import('../analytics')>('../analytics')
  return {
    ...actual,
    fetchAnalyticsOverview: vi.fn(),
    fetchAnalyticsUsers: vi.fn(),
    fetchAnalyticsServices: vi.fn(),
    fetchAnalyticsPerformance: vi.fn(),
    exportAnalyticsCsv: vi.fn(),
  }
})

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

const OVERVIEW: AnalyticsOverview = {
  total_queries: 128, active_users: 14, workflows_run: 6, error_rate: 0.05,
  from_date: '2026-07-12', to_date: '2026-08-11', org_id: null, team_id: null,
}

const EMPTY_OVERVIEW: AnalyticsOverview = {
  total_queries: 0, active_users: 0, workflows_run: 0, error_rate: 0,
  from_date: '2026-07-12', to_date: '2026-08-11', org_id: null, team_id: null,
}

const USERS: AnalyticsUsers = {
  daily: [{ date: '2026-08-10', count: 3 }, { date: '2026-08-11', count: 5 }],
  dau: 5, wau: 12, mau: 20, org_id: null, team_id: null,
}

const SERVICES: AnalyticsServices = {
  services: [{ service: 'rag', total_calls: 100, errors: 4, error_rate: 0.04, avg_latency_ms: null }],
  org_id: null, team_id: null,
}

const PERFORMANCE: AnalyticsPerformance = {
  scope: 'platform', org_id: null, team_id: null,
  p50_latency_ms: 45, p95_latency_ms: 210, p99_latency_ms: 480,
  error_rate: 0.02, throughput_per_day: 340, latency_source: 'events',
  from_date: '2026-07-12', to_date: '2026-08-11',
}

const ORG_OPTIONS: PlatformOrgSummary[] = [
  { id: 3, name: 'Acme Corp', status: 'active', owner_email: null, member_count: 1, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false, created_at: '2026-07-01T00:00:00' },
]

function mockAllEndpoints(overrides: Partial<{
  overview: AnalyticsOverview
  users: AnalyticsUsers
  services: AnalyticsServices
  performance: AnalyticsPerformance
}> = {}) {
  vi.mocked(analytics.fetchAnalyticsOverview).mockResolvedValue(overrides.overview ?? OVERVIEW)
  vi.mocked(analytics.fetchAnalyticsUsers).mockResolvedValue(overrides.users ?? USERS)
  vi.mocked(analytics.fetchAnalyticsServices).mockResolvedValue(overrides.services ?? SERVICES)
  vi.mocked(analytics.fetchAnalyticsPerformance).mockResolvedValue(overrides.performance ?? PERFORMANCE)
}

describe('AnalyticsDashboard', () => {
  beforeEach(() => {
    vi.mocked(analytics.fetchAnalyticsOverview).mockReset()
    vi.mocked(analytics.fetchAnalyticsUsers).mockReset()
    vi.mocked(analytics.fetchAnalyticsServices).mockReset()
    vi.mocked(analytics.fetchAnalyticsPerformance).mockReset()
    vi.mocked(analytics.exportAnalyticsCsv).mockReset()
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: ORG_OPTIONS, total: 1, page: 1, page_size: 100, total_pages: 1 })
  })

  it('loads and renders overview/users/services/performance data', async () => {
    mockAllEndpoints()
    render(<AnalyticsDashboard />)

    expect(await screen.findByText('128')).toBeInTheDocument() // Total Queries
    expect(screen.getByText('6')).toBeInTheDocument()          // Workflows Run
    expect(screen.getByText('5.0%')).toBeInTheDocument()       // Overview error rate
    expect(screen.getByText('rag')).toBeInTheDocument()        // service table row
    expect(screen.getByText('45 ms')).toBeInTheDocument()      // P50 latency
    expect(screen.getByText(/Platform-wide/)).toBeInTheDocument()
  })

  it('re-fetches with a new date range when a preset button is clicked', async () => {
    mockAllEndpoints()
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    await screen.findByText('128')

    vi.mocked(analytics.fetchAnalyticsOverview).mockClear()
    await user.click(screen.getByRole('button', { name: '7d' }))

    await waitFor(() => expect(analytics.fetchAnalyticsOverview).toHaveBeenCalled())
    const call = vi.mocked(analytics.fetchAnalyticsOverview).mock.calls[0][0]
    expect(call?.fromDate).toBeDefined()
  })

  it('shows an error state and allows retry when a call fails', async () => {
    vi.mocked(analytics.fetchAnalyticsOverview).mockRejectedValue(new Error('/analytics/overview 500'))
    vi.mocked(analytics.fetchAnalyticsUsers).mockResolvedValue(USERS)
    vi.mocked(analytics.fetchAnalyticsServices).mockResolvedValue(SERVICES)
    vi.mocked(analytics.fetchAnalyticsPerformance).mockResolvedValue(PERFORMANCE)

    render(<AnalyticsDashboard />)
    expect(await screen.findByText(/analytics\/overview 500/)).toBeInTheDocument()

    mockAllEndpoints()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('128')).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403 without a generic error box', async () => {
    vi.mocked(analytics.fetchAnalyticsOverview).mockRejectedValue(new Error('/analytics/overview 403'))
    vi.mocked(analytics.fetchAnalyticsUsers).mockResolvedValue(USERS)
    vi.mocked(analytics.fetchAnalyticsServices).mockResolvedValue(SERVICES)
    vi.mocked(analytics.fetchAnalyticsPerformance).mockResolvedValue(PERFORMANCE)

    render(<AnalyticsDashboard />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
  })

  it('renders an empty state for zero-data results, not fabricated numbers', async () => {
    mockAllEndpoints({
      overview: EMPTY_OVERVIEW,
      services: { services: [], org_id: null, team_id: null, note: 'No recorded service traffic for this range.' },
    })
    render(<AnalyticsDashboard />)

    await screen.findByText('No service activity')
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
  })

  it('renders "--" for null overview fields instead of fabricating a number', async () => {
    mockAllEndpoints({
      overview: { ...OVERVIEW, total_queries: null, active_users: null, workflows_run: null },
    })
    render(<AnalyticsDashboard />)
    await screen.findByText('rag')
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('exports CSV when the Export button is clicked', async () => {
    mockAllEndpoints()
    vi.mocked(analytics.exportAnalyticsCsv).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    await screen.findByText('128')

    await user.click(screen.getByRole('button', { name: /Export CSV/ }))
    await waitFor(() => expect(analytics.exportAnalyticsCsv).toHaveBeenCalledWith('overview', expect.any(Object)))
  })

  it('shows an inline error if CSV export fails, without blocking the rest of the page', async () => {
    mockAllEndpoints()
    vi.mocked(analytics.exportAnalyticsCsv).mockRejectedValue(new Error('/analytics/export 403'))
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    await screen.findByText('128')

    await user.click(screen.getByRole('button', { name: /Export CSV/ }))
    expect(await screen.findByText(/Export failed/)).toBeInTheDocument()
  })

  it('does not show an organization filter for a non-platform-admin', async () => {
    mockAllEndpoints()
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    render(<AnalyticsDashboard />)
    await screen.findByText('128')
    expect(screen.queryByLabelText('Filter by organization')).not.toBeInTheDocument()
  })

  it('shows an organization filter for a platform admin and re-fetches on change', async () => {
    mockAllEndpoints()
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(true)
    const user = userEvent.setup()
    render(<AnalyticsDashboard />)
    await screen.findByText('128')

    const select = await screen.findByLabelText('Filter by organization')
    vi.mocked(analytics.fetchAnalyticsOverview).mockClear()
    await user.selectOptions(select, '3')

    await waitFor(() => {
      const call = vi.mocked(analytics.fetchAnalyticsOverview).mock.calls.at(-1)?.[0]
      expect(call?.orgId).toBe(3)
    })
  })
})
