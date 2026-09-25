import { render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PublicOverviewPage from './PublicOverviewPage'

// recharts' ResponsiveContainer measures its parent, which jsdom can't do.
vi.mock('recharts', async (orig) => {
  const actual = await orig<typeof import('recharts')>()
  return { ...actual, ResponsiveContainer: ({ children }: { children: unknown }) => <div>{children as never}</div> }
})

vi.mock('../api', () => ({ fetchHealth: vi.fn() }))

vi.mock('../publicOverview', async (orig) => {
  const actual = await orig<typeof import('../publicOverview')>()
  return {
    ...actual,
    fetchPublicStats: vi.fn(),
    fetchUsage: vi.fn(),
    fetchAiAndWorkflow: vi.fn(),
    fetchReferenceStatus: vi.fn(),
    fetchBackends: vi.fn(),
    fetchOpenIssues: vi.fn(),
    fetchUptime: vi.fn(),
    fetchKnowledgeBase: vi.fn(),
  }
})

async function mocks() {
  const api = await import('../api')
  const po = await import('../publicOverview')
  vi.mocked(api.fetchHealth).mockResolvedValue({ status: 'ok' } as never)
  vi.mocked(po.fetchPublicStats).mockResolvedValue({
    generated_at: '2026-09-24T10:00:00Z', total_lines: 5_123_456, total_files: 40_000,
    ecosystem_coverage_percent: 90.1, repos_measured: 33,
  })
  vi.mocked(po.fetchUsage).mockResolvedValue({
    runs_by_day: [{ date: '2026-09-23', count: 4 }, { date: '2026-09-24', count: 6 }],
    top_plugins: [{ name: 'deseq2', runs_30d: 7 }, { name: 'seurat', runs_30d: 3 }],
    workflow_success_rate_pct: 92.5,
    success_rate_caveat: 'computed across individual plugin-step runs',
  })
  vi.mocked(po.fetchAiAndWorkflow).mockResolvedValue({
    ai_platform: { registered_models: 12, active_models: 5, embedding_models: 2, llm_providers: 3 },
    workflow: { workflow_bundles: 869 },
  })
  vi.mocked(po.fetchReferenceStatus).mockResolvedValue({
    available: true,
    organisms: [{ organism: 'human', assembly: 'GRCh38', indexes: { star: true, bwa: false } }],
  })
  vi.mocked(po.fetchBackends).mockResolvedValue({
    local: { label: 'Local Docker', configured: true },
    aws: { label: 'AWS Batch', configured: false },
  })
  vi.mocked(po.fetchKnowledgeBase).mockResolvedValue({
    rag_status: 'running',
    abstracts: { total: 28_131_100, domains_with_abstracts: 282 },
    faiss_index: { domains_indexed: 282, size_gb: 67.1 },
    readiness: { expected_dimension: 1024, domains_total: 282, domains_ready: 7,
      domains_by_dimension: { '768': 275, '1024': 7 }, missing_map: 4, unreadable: 0 },
  })
  vi.mocked(po.fetchUptime).mockResolvedValue({
    window_days: 3, sample_seconds: 300,
    services: [{ label: 'Workbench', overall_pct: 99.8, days: [
      { date: '2026-09-23', availability_pct: null },
      { date: '2026-09-24', availability_pct: 100 },
      { date: '2026-09-25', availability_pct: 96.5 },
    ] }],
  })
  vi.mocked(po.fetchOpenIssues).mockResolvedValue([
    { id: '1', title: 'RAG re-indexing in progress', severity: 'medium', status: 'open', area: 'rag', opened_at: '2026-09-18T00:00:00Z' },
  ])
  return po
}

describe('PublicOverviewPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders every section from the public endpoints', async () => {
    await mocks()
    render(<PublicOverviewPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Control center online')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('5.1M')).toBeInTheDocument())
    expect(screen.getByText('Workbench plugins')).toBeInTheDocument()   // catalog snapshot
    expect(screen.getByText('10')).toBeInTheDocument()                  // runs in 30 days
    expect(screen.getByText('92.5%')).toBeInTheDocument()
    expect(screen.getByText('deseq2')).toBeInTheDocument()
    expect(screen.getByText('869')).toBeInTheDocument()                 // workflow bundles
    expect(screen.getByText('GRCh38')).toBeInTheDocument()
    expect(screen.getByText('STAR')).toBeInTheDocument()
    expect(screen.getByText('Local Docker · configured')).toBeInTheDocument()
    expect(screen.getByText('AWS Batch · not configured')).toBeInTheDocument()
    expect(screen.getByText('RAG re-indexing in progress')).toBeInTheDocument()
  })

  it('shows per-service uptime bars with a day-by-day breakdown', async () => {
    await mocks()
    render(<PublicOverviewPage refreshKey={0} />)
    expect(await screen.findByText('99.8% available')).toBeInTheDocument()
    const bar = screen.getByRole('img', { name: 'Workbench: daily availability over 3 days' })
    expect(bar.children).toHaveLength(3)
    expect(screen.getByTitle('2026-09-23: no data')).toBeInTheDocument()
    expect(screen.getByTitle('2026-09-25: 96.5%')).toBeInTheDocument()
    expect(screen.getByText(/Sampled every 5 minutes/)).toBeInTheDocument()
  })

  it('says uptime is not published yet when no services are allowlisted', async () => {
    const po = await mocks()
    vi.mocked(po.fetchUptime).mockResolvedValue({ window_days: 90, sample_seconds: 300, services: [] })
    render(<PublicOverviewPage refreshKey={0} />)
    expect(await screen.findByText('Uptime history is not being published yet.')).toBeInTheDocument()
  })

  it('shows Literature AI re-indexing progress honestly', async () => {
    await mocks()
    render(<PublicOverviewPage refreshKey={0} />)
    expect(await screen.findByText('Re-indexing: 7 of 282 domains ready to query')).toBeInTheDocument()
    expect(screen.getByText('28.1M')).toBeInTheDocument()
    expect(screen.getByText('28,131,100 abstracts')).toBeInTheDocument()
    expect(screen.getByText('Online')).toBeInTheDocument()
    const bar = screen.getByRole('progressbar', { name: 'Domains ready to query' })
    expect(bar).toHaveAttribute('aria-valuenow', '7')
    expect(screen.getByText('2%')).toBeInTheDocument()
    expect(screen.getByText(/rebuilt with 1024-dimension embeddings/)).toBeInTheDocument()
  })

  it('says all domains are ready once re-indexing completes', async () => {
    const po = await mocks()
    vi.mocked(po.fetchKnowledgeBase).mockResolvedValue({
      rag_status: 'degraded', abstracts: { total: 10, domains_with_abstracts: 2 },
      faiss_index: { domains_indexed: 2, size_gb: 1 },
      readiness: { expected_dimension: 1024, domains_total: 2, domains_ready: 2,
        domains_by_dimension: { '1024': 2 }, missing_map: 0, unreadable: 0 },
    })
    render(<PublicOverviewPage refreshKey={0} />)
    expect(await screen.findByText('All 2 domains ready to query')).toBeInTheDocument()
    expect(screen.getByText('Degraded')).toBeInTheDocument()
    expect(screen.queryByText(/rebuilt with/)).not.toBeInTheDocument()
  })

  it('does not show a coverage percentage', async () => {
    await mocks()
    render(<PublicOverviewPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('5.1M')).toBeInTheDocument())
    expect(screen.queryByText(/90\.1/)).not.toBeInTheDocument()
  })

  it('isolates a failing section instead of blanking the page', async () => {
    const po = await mocks()
    vi.mocked(po.fetchUsage).mockRejectedValue(new Error('/usage 500'))
    render(<PublicOverviewPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Usage data is unavailable right now.')).toBeInTheDocument())
    expect(await screen.findByText('869')).toBeInTheDocument()
  })

  it('shows honest empty states', async () => {
    const po = await mocks()
    const api = await import('../api')
    vi.mocked(api.fetchHealth).mockRejectedValue(new Error('down'))
    vi.mocked(po.fetchOpenIssues).mockResolvedValue([])
    vi.mocked(po.fetchReferenceStatus).mockResolvedValue({ available: true, organisms: [] })
    vi.mocked(po.fetchPublicStats).mockResolvedValue({
      generated_at: null, total_lines: null, total_files: null, ecosystem_coverage_percent: null, repos_measured: 0,
    })
    render(<PublicOverviewPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Control center unreachable')).toBeInTheDocument())
    expect(await screen.findByText('No open known issues.')).toBeInTheDocument()
    expect(screen.getByText('No reference genomes installed yet.')).toBeInTheDocument()
    expect(screen.getByText('Codebase statistics is unavailable right now.')).toBeInTheDocument()
  })

  it('labels the catalog figures as a dated, registered-in-source snapshot', async () => {
    await mocks()
    render(<PublicOverviewPage refreshKey={0} />)
    const section = screen.getByText('Platform at a glance').closest('section') as HTMLElement
    expect(within(section).getByText(/snapshot 2026-09-19/)).toBeInTheDocument()
    expect(within(section).getByText(/not the same as tested or deployed/)).toBeInTheDocument()
  })
})

describe('publicOverview fetchers', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('never sends an Authorization header, and hides resolved issues and descriptions', async () => {
    const { fetchOpenIssues } = await vi.importActual<typeof import('../publicOverview')>('../publicOverview')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ issues: [
        { id: 'a', title: 'Open one', description: 'internal notes', severity: 'low', status: 'open', area: null, opened_at: null },
        { id: 'b', title: 'Fixed one', description: null, severity: 'high', status: 'resolved', area: null, opened_at: null },
      ] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const issues = await fetchOpenIssues()
    expect(issues).toEqual([{ id: 'a', title: 'Open one', severity: 'low', status: 'open', area: null, opened_at: null }])
    expect(fetchMock).toHaveBeenCalledWith('/known-issues')
    vi.unstubAllGlobals()
  })

  it('rejects on a non-OK response', async () => {
    const { fetchUsage } = await vi.importActual<typeof import('../publicOverview')>('../publicOverview')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    await expect(fetchUsage()).rejects.toThrow('/usage 503')
    vi.unstubAllGlobals()
  })
})
