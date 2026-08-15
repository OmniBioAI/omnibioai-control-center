import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import PublicEcosystemPage from './PublicEcosystemPage'
import type { ReportData } from '../api'

vi.mock('../api', () => ({
  fetchReportData: vi.fn(),
  fetchReportStatus: vi.fn(),
}))

const REPORT_DATA: ReportData = {
  projects: [
    { name: 'omnibioai-auth', full: 'OmniBioAI/omnibioai-auth', cat: 'sec', catLabel: 'security', files: 10, code: 5000, comment: 100, blank: 200, pct: 40 },
  ] as any,
  languages: [
    { name: 'Python', type: 'backend', typeLabel: 'backend', files: 10, code: 4000, comment: 90, blank: 150, pct: 80 },
  ] as any,
  coverage: [
    { repo: 'omnibioai-auth', status: 'ok', pct: 97.2, stmts: 500, missed: 14, branches: 80, failUnder: 90 },
  ] as any,
  gitStatus: [
    { repo: 'omnibioai-auth', branch: 'main', clean: true, nonMain: false, details: '' },
  ] as any,
  grand: { code: 5000, comment: 100, blank: 200 } as any,
  generated_at: '2026-08-14T00:00:00Z',
}

describe('PublicEcosystemPage', () => {
  beforeEach(async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportData).mockReset()
    vi.mocked(api.fetchReportStatus).mockReset()
  })

  it('never calls fetchSummary / GET /summary -- only fetchReportData and fetchReportStatus', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportData).mockResolvedValue(REPORT_DATA)
    vi.mocked(api.fetchReportStatus).mockResolvedValue({ report_exists: true, status: 'idle' } as any)
    render(<PublicEcosystemPage refreshKey={0} />)
    await waitFor(() => expect(api.fetchReportData).toHaveBeenCalled())
    expect(api.fetchReportStatus).toHaveBeenCalled()
    // fetchSummary is not even exported by the mocked module -- if this
    // component ever imported and called it, the import itself would
    // throw, failing this test.
    expect('fetchSummary' in api).toBe(false)
  })

  it('shows Projects/Languages/Coverage/Ecosystem Status tabs -- no Architecture, no Health Status', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportData).mockResolvedValue(REPORT_DATA)
    vi.mocked(api.fetchReportStatus).mockResolvedValue({ report_exists: true, status: 'idle' } as any)
    render(<PublicEcosystemPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Projects')).toBeInTheDocument())
    expect(screen.getByText('Languages')).toBeInTheDocument()
    expect(screen.getByText('Code Coverage')).toBeInTheDocument()
    expect(screen.getByText('Ecosystem Status')).toBeInTheDocument()
    expect(screen.queryByText('Architecture')).not.toBeInTheDocument()
    expect(screen.queryByText('Health Status')).not.toBeInTheDocument()
  })

  it('renders no internal service names, ports, or topology strings from LANES', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportData).mockResolvedValue(REPORT_DATA)
    vi.mocked(api.fetchReportStatus).mockResolvedValue({ report_exists: true, status: 'idle' } as any)
    const { container } = render(<PublicEcosystemPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('Projects')).toBeInTheDocument())
    const text = container.textContent ?? ''
    for (const marker of ['auth-service', 'security-audit', 'hpc-policy-engine', 'Redis streams', 'GPU quota', ':8001', ':8004', ':11434']) {
      expect(text).not.toContain(marker)
    }
  })

  it('shows a "no report data yet" state, with no Generate button, when no report exists', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportData).mockRejectedValue(new Error('/report/data 404'))
    vi.mocked(api.fetchReportStatus).mockResolvedValue({ report_exists: false, status: 'idle' } as any)
    render(<PublicEcosystemPage refreshKey={0} />)
    await waitFor(() => expect(screen.getByText('No report data yet')).toBeInTheDocument())
    expect(screen.queryByText(/Generate Report/)).not.toBeInTheDocument()
  })

  it('source imports only from ./EcosystemReportTabs and ../api -- never ./EcosystemPage, ArchTab, or LANES', () => {
    // Only the import statements matter for what actually ships in the
    // bundle -- explanatory prose in this file's own doc comment
    // necessarily *names* EcosystemPage/ArchTab/GenerateCta/HealthTab to
    // say they're absent, so scanning the whole file text would trip on
    // its own documentation (same convention ControlApp.test.tsx already
    // uses for the same reason).
    const thisFile = fileURLToPath(import.meta.url)
    const source = readFileSync(join(dirname(thisFile), 'PublicEcosystemPage.tsx'), 'utf-8')
    const importLines = source
      .split('\n')
      .filter((line: string) => /^\s*import\b.*\bfrom\s+['"]/.test(line))
      .join('\n')
    for (const forbidden of [
      "'./EcosystemPage'", '"./EcosystemPage"', 'ArchTab', 'LANES',
      'fetchSummary', 'triggerGenerate', 'GenerateCta', 'HealthTab',
    ]) {
      expect(importLines).not.toContain(forbidden)
    }
  })
})
