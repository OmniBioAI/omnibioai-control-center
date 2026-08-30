import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SecurityPosturePage from './SecurityPosturePage'
import { fetchSecurityPosture } from '../../api'
import type { SecurityControlItem, SecurityPostureResponse } from '../../api'

vi.mock('../../api', () => ({ fetchSecurityPosture: vi.fn() }))

function response(overrides: Partial<SecurityPostureResponse> = {}): SecurityPostureResponse {
  return {
    schema_version: '1.0', generated_at: '2026-08-30T12:00:00Z',
    summary: { verified: 1, partial: 1, attention: 1, unknown: 1, not_implemented: 1 },
    categories: ['AUTHENTICATION'],
    controls: [{
      control_id: 'auth.jwt_validation', name: 'JWT validation', category: 'AUTHENTICATION', priority: 'P0',
      implementation_status: 'IMPLEMENTED', test_status: 'PASS', live_status: 'AVAILABLE',
      certification_status: 'CERTIFIED', freshness: 'CURRENT', posture: 'VERIFIED',
      evidence: [{ type: 'UNIT_TEST', repository: 'omnibioai-auth', identifier: 'test-jwt', status: 'PASS', validated_at: '2026-08-30T12:00:00Z', freshness: 'CURRENT', description: 'JWT validation tests' }],
      findings: [], limitations: [],
    }], findings: [], technical_debt: [],
    data_sources: { auth: 'AVAILABLE', regression_health: 'PARTIAL' }, limitations: ['Policy counters unavailable'],
    ...overrides,
  }
}

describe('SecurityPosturePage', () => {
  beforeEach(() => vi.mocked(fetchSecurityPosture).mockReset())

  it('renders backend summary, independent dimensions, evidence, source state, and limitations', async () => {
    vi.mocked(fetchSecurityPosture).mockResolvedValue(response())
    render(<SecurityPosturePage />)
    expect(await screen.findByText('Security Posture')).toBeInTheDocument()
    expect(screen.getByText('Policy counters unavailable')).toBeInTheDocument()
    expect(screen.getAllByText('verified', { exact: false }).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: /JWT validation/i }))
    expect(screen.getAllByText('Implementation').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/omnibioai-auth/)).toBeInTheDocument()
  })

  it('does not default unavailable data to green', async () => {
    vi.mocked(fetchSecurityPosture).mockResolvedValue(response({ summary: { verified: 0, partial: 0, attention: 0, unknown: 1, not_implemented: 0 }, controls: [] }))
    render(<SecurityPosturePage />)
    expect(await screen.findByText('No controls available')).toBeInTheDocument()
    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })

  it.each([
    ['/security-posture/data 401', 'Session expired'],
    ['/security-posture/data 403', 'Permission denied'],
    ['/security-posture/data 503', 'Security posture data is unavailable.'],
  ])('renders safe generic errors for %s', async (error, message) => {
    vi.mocked(fetchSecurityPosture).mockRejectedValueOnce(new Error(error))
    render(<SecurityPosturePage />)
    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(screen.queryByText(error)).not.toBeInTheDocument()
  })

  it('rejects malformed responses without displaying arbitrary nested data', async () => {
    vi.mocked(fetchSecurityPosture).mockResolvedValue({ controls: [{ password: 'should-not-render' }] } as never)
    render(<SecurityPosturePage />)
    expect(await screen.findByText('Security posture data could not be loaded.')).toBeInTheDocument()
    expect(screen.queryByText('should-not-render')).not.toBeInTheDocument()
  })

  it('renders findings and keeps the page read-only', async () => {
    const base = response().controls[0]
    vi.mocked(fetchSecurityPosture).mockResolvedValue(response({
      controls: [
        base,
        { ...base, control_id: 'partial', name: 'Partial control', test_status: 'PARTIAL', posture: 'PARTIAL', freshness: 'STALE' },
        { ...base, control_id: 'attention', name: 'Attention control', test_status: 'FAILED', posture: 'ATTENTION' },
        { ...base, control_id: 'unknown', name: 'Unknown control', implementation_status: 'UNKNOWN', posture: 'UNKNOWN' },
        { ...base, control_id: 'not-implemented', name: 'Not implemented control', implementation_status: 'NOT_IMPLEMENTED', posture: 'NOT_IMPLEMENTED' },
      ],
      findings: [
        { finding_id: 'active', title: 'Active issue', type: 'ACTIVE_ISSUE', control_ids: [], source: 'test', validated_at: null, summary: '' },
        { finding_id: 'fixed', title: 'Fixed historical', type: 'FIXED_HISTORICAL', control_ids: [], source: 'test', validated_at: null, summary: '' },
        { finding_id: 'gap', title: 'Coverage gap', type: 'COVERAGE_GAP', control_ids: [], source: 'test', validated_at: null, summary: '' },
      ],
      technical_debt: [{ debt_id: 'debt-1', summary: 'Counters need a stable contract', control_ids: [] }],
    }))
    render(<SecurityPosturePage />)
    expect(await screen.findByText('Partial control')).toBeInTheDocument()
    expect(screen.getAllByText('Fixed historical')).toHaveLength(2)
    expect(screen.getAllByText('Coverage gap')).toHaveLength(2)
    expect(screen.getByText('Counters need a stable contract')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /rotate|revoke|edit|remediate|acknowledge/i })).not.toBeInTheDocument()
  })

  it('keeps exercised-path tenant certification distinct from overall posture', async () => {
    const tenant: SecurityControlItem = {
      ...response().controls[0],
      control_id: 'isolation.organization',
      name: 'Organization isolation',
      category: 'TENANT_ISOLATION',
      certification_status: 'CERTIFIED',
      freshness: 'CURRENT',
      posture: 'PARTIAL',
      limitations: ['Tenant isolation certification applies to exercised/certified paths and does not establish platform-wide coverage.'],
    }
    vi.mocked(fetchSecurityPosture).mockResolvedValue(response({ controls: [tenant] }))
    render(<SecurityPosturePage />)
    expect(await screen.findByText('Organization isolation')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Organization isolation/i }))
    expect(screen.getAllByText('certified').length).toBeGreaterThan(0)
    expect(screen.getAllByText('partial').length).toBeGreaterThan(0)
    expect(screen.getByText(/exercised\/certified paths/)).toBeInTheDocument()
    expect(screen.queryByText('VERIFIED')).not.toBeInTheDocument()
  })
})
