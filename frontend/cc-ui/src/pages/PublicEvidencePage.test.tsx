import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PublicEvidencePage from './PublicEvidencePage'
import type { Showcase } from '../publicOverview'

vi.mock('../publicOverview', async (orig) => {
  const actual = await orig<typeof import('../publicOverview')>()
  return { ...actual, fetchShowcase: vi.fn() }
})

const EMPTY: Showcase = {
  available: true, as_of: null, releases: [], benchmarks: [], example_runs: [], tool_versions: [],
  publications: [], test_evidence: [], repo_coverage: [], ci_repos: [], security_controls: [],
  data_handling: [], limitations: [], regression: null,
}

const FULL: Showcase = {
  ...EMPTY,
  as_of: '2026-09-25',
  releases: [{ version: 'v0.7.1-beta', date: '2026-09-01', url: 'https://github.com/o/r/releases/tag/v0.7.1-beta' }],
  benchmarks: [{ pipeline: 'Germline SNVs', dataset: 'GIAB HG002', metrics: { precision: 0.998, recall: 0.995 }, date: '2026-09-10', url: null }],
  example_runs: [{ title: 'PBMC 3k single-cell', dataset: '10x PBMC 3k', description: 'QC to clusters.', report_url: 'https://r', inputs_url: null }],
  tool_versions: [{ name: 'STAR', version: '2.7.11b', category: 'aligner' }],
  publications: [{ year: 2018, title: 'Metabolic QTLs', venue: 'Nature Communications', url: 'https://n' }],
  test_evidence: [{ suite: 'Release candidate', date: '2026-09-15', passed: 140, failed: 0, skipped: 13, blocked: 6, url: null }],
  repo_coverage: [{ repo: 'omnibioai-auth', coverage_pct: 96.4, date: '2026-09-20' }],
  ci_repos: [{ repo: 'OmniBioAI/omnibioai-docs', workflow: 'ci.yml', label: 'Documentation' }],
  security_controls: [
    { area: 'Identity', status: 'implemented', summary: 'Short-lived tokens.' },
    { area: 'Tenant isolation', status: 'partial', summary: 'Not yet uniform.' },
  ],
  data_handling: ['HIPAA-aligned controls.'],
  limitations: [{ title: 'Indexes being rebuilt', detail: 'Partial corpus.', url: 'https://docs.omnibioai.org/x/' }],
  regression: {
    generated_at: '2026-09-20T00:00:00Z', freshness: 'FRESH',
    phases: { p0: { status: 'complete', certification_status: 'certified' }, p1: { status: 'partial', certification_status: 'not_certified' } },
    capabilities_total: 3, capabilities_by_certification: { certified: 2, not_certified: 1 },
  },
}

describe('PublicEvidencePage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders every evidence section from /showcase', async () => {
    const po = await import('../publicOverview')
    vi.mocked(po.fetchShowcase).mockResolvedValue(FULL)
    render(<PublicEvidencePage refreshKey={0} />)
    expect(await screen.findByText('GIAB HG002')).toBeInTheDocument()
    expect(screen.getByText('precision 0.998 · recall 0.995')).toBeInTheDocument()
    expect(screen.getByText('PBMC 3k single-cell')).toBeInTheDocument()
    expect(screen.getByText('2.7.11b')).toBeInTheDocument()
    expect(screen.getByAltText('Documentation CI status')).toHaveAttribute(
      'src', 'https://github.com/OmniBioAI/omnibioai-docs/actions/workflows/ci.yml/badge.svg')
    expect(screen.getByText('P0: certified')).toBeInTheDocument()
    expect(screen.getByText('P1: not certified')).toBeInTheDocument()
    expect(screen.getByText(/3 capabilities tracked: 2 certified, 1 not certified/)).toBeInTheDocument()
    expect(screen.getByText('140')).toBeInTheDocument()
    expect(screen.getByText('96.4%')).toBeInTheDocument()
    expect(screen.getByText('Implemented')).toBeInTheDocument()
    expect(screen.getByText('Partial')).toBeInTheDocument()
    expect(screen.getByText('HIPAA-aligned controls.')).toBeInTheDocument()
    expect(screen.getByText('Indexes being rebuilt ↗')).toBeInTheDocument()
    expect(screen.getByText('v0.7.1-beta')).toBeInTheDocument()
    expect(screen.getByText('Metabolic QTLs')).toBeInTheDocument()
    expect(screen.getByText(/Reviewed 2026-09-25/)).toBeInTheDocument()
  })

  it('renders only sections that have content -- no placeholder cards', async () => {
    const po = await import('../publicOverview')
    vi.mocked(po.fetchShowcase).mockResolvedValue({ ...EMPTY, publications: FULL.publications, limitations: FULL.limitations })
    render(<PublicEvidencePage refreshKey={0} />)
    expect(await screen.findByText('Publications')).toBeInTheDocument()
    expect(screen.getByText('Known limitations')).toBeInTheDocument()
    for (const hidden of ['Benchmarks', 'Example analyses', 'Tool and database versions', 'Continuous integration',
      'End-to-end certification', 'Test runs', 'Test coverage by repository', 'Security controls', 'Data handling', 'Releases']) {
      expect(screen.queryByText(hidden)).not.toBeInTheDocument()
    }
    expect(screen.queryByText(/being prepared/)).not.toBeInTheDocument()
  })

  it('shows one short note when nothing is published yet', async () => {
    const po = await import('../publicOverview')
    vi.mocked(po.fetchShowcase).mockResolvedValue(EMPTY)
    render(<PublicEvidencePage refreshKey={0} />)
    expect(await screen.findByText('Evidence is being prepared and will appear here as it is published.')).toBeInTheDocument()
    expect(screen.queryByText('Benchmarks')).not.toBeInTheDocument()
  })

  it('flags unavailable curated content and a failed request', async () => {
    const po = await import('../publicOverview')
    vi.mocked(po.fetchShowcase).mockResolvedValueOnce({ ...EMPTY, available: false })
    const { unmount } = render(<PublicEvidencePage refreshKey={0} />)
    expect(await screen.findByText(/Curated content is temporarily unavailable/)).toBeInTheDocument()
    unmount()
    vi.mocked(po.fetchShowcase).mockRejectedValueOnce(new Error('/showcase 500'))
    render(<PublicEvidencePage refreshKey={0} />)
    expect(await screen.findByText('Evidence content is unavailable right now.')).toBeInTheDocument()
  })
})
