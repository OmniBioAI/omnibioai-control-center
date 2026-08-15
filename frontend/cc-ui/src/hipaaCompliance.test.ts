import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  fetchHipaaComplianceSummary, fetchHipaaComplianceChanges, fetchHipaaComplianceChange,
  createHipaaComplianceChange, updateHipaaComplianceChange,
  type HipaaComplianceSummary, type HipaaComplianceChange, type HipaaComplianceChangeListResponse,
} from './hipaaCompliance'
import * as auth from './auth'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return { ...actual, authHeaders: vi.fn(() => ({})), reportUnauthorized: vi.fn() }
})

const SUMMARY: HipaaComplianceSummary = {
  overall_status: 'on_track',
  total_controls_tracked: 2,
  verified_count: 2,
  pending_count: 0,
  exception_count: 0,
  latest_change_id: 'CC-PR45',
  latest_change_title: 'HIPAA PR3c',
  latest_change_date: '2026-08-15',
  controls: [],
}

const CHANGE: HipaaComplianceChange = {
  change_id: 'CC-PR45',
  title: 'HIPAA PR3c',
  change_date: '2026-08-15',
  repository: 'omnibioai-control-center',
  branch: 'feat/hipaa-pr3c-audit-integrity',
  commit_sha: '80ea650',
  pr_number: 45,
  description: 'desc',
  control_category: 'audit_event_verification',
  affected_component: 'checks/audit_trail.py',
  status: 'released',
  verification_result: '1323/1323 passed',
  reviewer: null,
  evidence: [{ type: 'github_pr', label: 'PR #45', url: 'https://example.com/45' }],
  notes: 'notes',
  created_at: '2026-08-15T00:00:00Z',
  updated_at: '2026-08-15T00:00:00Z',
}

const LIST: HipaaComplianceChangeListResponse = {
  items: [CHANGE], total: 1, page: 1, page_size: 20, total_pages: 1,
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.mocked(auth.reportUnauthorized).mockClear()
})

describe('fetchHipaaComplianceSummary', () => {
  it('fetches the summary endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(SUMMARY), { status: 200 }))
    const summary = await fetchHipaaComplianceSummary()
    expect(summary.overall_status).toBe('on_track')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toBe('/hipaa-compliance/changes/summary')
  })

  it('throws on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 403 }))
    await expect(fetchHipaaComplianceSummary()).rejects.toThrow('403')
  })

  it('reports unauthorized on 401', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 401 }))
    await expect(fetchHipaaComplianceSummary()).rejects.toThrow('401')
    expect(auth.reportUnauthorized).toHaveBeenCalled()
  })
})

describe('fetchHipaaComplianceChanges', () => {
  it('requests default pagination with no filters', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(LIST), { status: 200 }))
    const result = await fetchHipaaComplianceChanges()
    expect(result.total).toBe(1)
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toContain('/hipaa-compliance/changes?')
    expect(calledUrl).toContain('page=1')
    expect(calledUrl).toContain('page_size=20')
    expect(calledUrl).not.toContain('status=')
    expect(calledUrl).not.toContain('control_category=')
  })

  it('passes status/control_category/repository filters through', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(LIST), { status: 200 }))
    await fetchHipaaComplianceChanges({
      status: 'verified', controlCategory: 'audit_event_signing', repository: 'omnibioai-security-audit', page: 2, pageSize: 10,
    })
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toContain('status=verified')
    expect(calledUrl).toContain('control_category=audit_event_signing')
    expect(calledUrl).toContain('repository=omnibioai-security-audit')
    expect(calledUrl).toContain('page=2')
    expect(calledUrl).toContain('page_size=10')
  })

  it('throws on a non-ok response', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 500 }))
    await expect(fetchHipaaComplianceChanges()).rejects.toThrow('500')
  })
})

describe('fetchHipaaComplianceChange', () => {
  it('fetches a single change by id', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(CHANGE), { status: 200 }))
    const change = await fetchHipaaComplianceChange('CC-PR45')
    expect(change.title).toBe('HIPAA PR3c')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toBe('/hipaa-compliance/changes/CC-PR45')
  })

  it('URL-encodes the change id', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(CHANGE), { status: 200 }))
    await fetchHipaaComplianceChange('a/b c')
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string
    expect(calledUrl).toBe('/hipaa-compliance/changes/a%2Fb%20c')
  })

  it('throws on 404', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }))
    await expect(fetchHipaaComplianceChange('nope')).rejects.toThrow('404')
  })
})

describe('createHipaaComplianceChange', () => {
  it('POSTs the input as JSON', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(CHANGE), { status: 201 }))
    await createHipaaComplianceChange({
      change_id: 'CC-PR45', title: 'HIPAA PR3c', change_date: '2026-08-15',
      repository: 'omnibioai-control-center', control_category: 'audit_event_verification', status: 'released',
    })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/hipaa-compliance/changes')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string).change_id).toBe('CC-PR45')
  })

  it('throws on 409 conflict', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 409 }))
    await expect(createHipaaComplianceChange({
      change_id: 'DUP', title: 't', change_date: '2026-08-15',
      repository: 'r', control_category: 'other', status: 'planned',
    })).rejects.toThrow('409')
  })

  it('throws on 422 validation error', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 422 }))
    await expect(createHipaaComplianceChange({
      change_id: 'BAD', title: 't', change_date: '2026-08-15',
      repository: 'r', control_category: 'other',
      // @ts-expect-error -- deliberately invalid status to prove the client surfaces a 422, not silently coerce it
      status: 'not-a-status',
    })).rejects.toThrow('422')
  })
})

describe('updateHipaaComplianceChange', () => {
  it('PATCHes only the provided fields', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ ...CHANGE, status: 'verified' }), { status: 200 }))
    await updateHipaaComplianceChange('CC-PR45', { status: 'verified' })
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/hipaa-compliance/changes/CC-PR45')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual({ status: 'verified' })
  })

  it('throws on 404', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }))
    await expect(updateHipaaComplianceChange('nope', { status: 'verified' })).rejects.toThrow('404')
  })
})
