import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { downloadHipaaReportCsv, downloadHipaaReportPdf, fetchHipaaReport, type HipaaReport } from './compliance'
import * as auth from './auth'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return { ...actual, authHeaders: vi.fn(() => ({})), reportUnauthorized: vi.fn() }
})

const REPORT: HipaaReport = {
  organization_id: 1,
  organization_name: 'KUMC Research',
  from_date: '2026-08-01',
  to_date: '2026-08-31',
  generated_at: '2026-08-11T12:00:00Z',
  generated_by: 'admin@omnibioai.org',
  summary: { total_users: 2, active_users: 1, total_rag_queries: 3, failed_login_attempts: 0, security_events_requiring_review: 0 },
  user_access: [],
  rag_queries: [],
  security_events: [],
  truncated: false,
  sources_unavailable: [],
}

describe('fetchHipaaReport', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('requests the expected query params', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(REPORT), { status: 200 }))
    const report = await fetchHipaaReport({ fromDate: '2026-08-01', toDate: '2026-08-31', orgId: 1 })
    expect(report.organization_name).toBe('KUMC Research')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toContain('/compliance/hipaa-report?')
    expect(calledUrl).toContain('from_date=2026-08-01')
    expect(calledUrl).toContain('to_date=2026-08-31')
    expect(calledUrl).toContain('org_id=1')
  })

  it('throws on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 403 }))
    await expect(fetchHipaaReport({ fromDate: '2026-08-01', toDate: '2026-08-31', orgId: 1 })).rejects.toThrow('403')
  })

  it('reports unauthorized on 401', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 401 }))
    await expect(fetchHipaaReport({ fromDate: '2026-08-01', toDate: '2026-08-31', orgId: 1 })).rejects.toThrow('401')
    expect(auth.reportUnauthorized).toHaveBeenCalled()
  })
})

describe('downloadHipaaReportPdf / downloadHipaaReportCsv', () => {
  // The blob/anchor-click download mechanism itself has no existing unit
  // test anywhere in this codebase (exportAnalyticsCsv's identical
  // mechanism is only ever exercised indirectly, through
  // AnalyticsDashboard.test.tsx mocking the whole function out) --
  // jsdom's URL.createObjectURL isn't implemented by default, so it's
  // stubbed here; a real anchor's .click() is safe in jsdom (no
  // navigation happens for a blob: URL).
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:mock'), revokeObjectURL: vi.fn() })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('downloads the PDF hitting the pdf endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(new Blob(['%PDF-1.7']), { status: 200 }))
    await downloadHipaaReportPdf({ fromDate: '2026-08-01', toDate: '2026-08-31', orgId: 1 })
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toContain('/compliance/hipaa-report/pdf?')
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('downloads the CSV hitting the csv endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(new Blob(['col1,col2']), { status: 200 }))
    await downloadHipaaReportCsv({ fromDate: '2026-08-01', toDate: '2026-08-31', orgId: 1 })
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toContain('/compliance/hipaa-report/csv?')
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('throws on a non-ok download response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 500 }))
    await expect(downloadHipaaReportPdf({ fromDate: '2026-08-01', toDate: '2026-08-31', orgId: 1 })).rejects.toThrow('500')
  })
})
