import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RegressionHealthPage from './RegressionHealthPage'
import { fetchRegressionHealth } from '../api'

vi.mock('../api', () => ({ fetchRegressionHealth: vi.fn() }))

const capability = (id: string, label: string, certification_status = 'certified') => ({
  id, label, implementation_status: 'implemented', test_status: 'pass',
  live_status: 'pass', certification_status, last_validated_at: '2026-08-26', evidence: {},
})

const response = (freshness: 'CURRENT' | 'STALE' | 'UNKNOWN' = 'CURRENT') => ({
  schema_version: '1.0', generated_at: '2026-08-29T12:00:00Z',
  source: { repository: 'omnibioai-ecosystem-regression', commit: 'abc123' },
  phases: {
    p0: { status: 'complete', certification_status: 'certified', evidence: {} },
    p1: { status: 'complete', certification_status: 'certified', evidence: {} },
    p2: { status: 'in_progress', certification_status: 'partial', evidence: {} },
  },
  capabilities: [
    capability('local-nextflow', 'Local Nextflow'),
    capability('backend-aware-timeout', 'Backend-aware timeout', 'not_certified'),
  ],
  findings: [{ id: 'REG-007', status: 'fixed', validation_status: 'live_validated', summary: 'Gateway query forwarding fixed.', last_validated_at: '2026-08-26' }],
  technical_debt: [{ id: 'phase-6-4-pause', status: 'paused', summary: 'Live timeout certification is paused.' }],
  freshness: { status: freshness, stale_after_hours: 168 },
})

describe('RegressionHealthPage', () => {
  beforeEach(() => vi.mocked(fetchRegressionHealth).mockReset())

  it('renders loading and the API phase values', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue(response() as any)
    render(<RegressionHealthPage />)
    expect(screen.getByText('Loading regression health…')).toBeInTheDocument()
    expect(await screen.findByText('Certification Summary')).toBeInTheDocument()
    expect(screen.getAllByText('certified', { exact: false }).length).toBeGreaterThan(0)
    expect(screen.getByText('in_progress', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('partial', { exact: false })).toBeInTheDocument()
  })

  it('renders current freshness and keeps runtime health distinct', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue(response() as any)
    render(<RegressionHealthPage />)
    expect(await screen.findByText('CURRENT')).toBeInTheDocument()
    expect(screen.getByText('Runtime Health')).toBeInTheDocument()
    expect(screen.getAllByText('Regression Health')).toHaveLength(2)
    expect(screen.getAllByText('Certification Freshness')).toHaveLength(2)
  })

  it('warns for stale data without changing certification state', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue(response('STALE') as any)
    render(<RegressionHealthPage />)
    expect(await screen.findByText('Certification data is stale; underlying certification states are preserved.')).toBeInTheDocument()
    expect(screen.getByText('STALE')).toBeInTheDocument()
    expect(screen.getAllByText('certified', { exact: false }).length).toBeGreaterThan(0)
  })

  it('renders unknown freshness safely', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue(response('UNKNOWN') as any)
    render(<RegressionHealthPage />)
    expect(await screen.findByText('UNKNOWN')).toBeInTheDocument()
    expect(screen.getByText('Freshness could not be determined from the artifact timestamp.')).toBeInTheDocument()
  })

  it('renders capability statuses, findings, and technical debt dynamically', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue(response() as any)
    render(<RegressionHealthPage />)
    expect(await screen.findByText('Local Nextflow')).toBeInTheDocument()
    expect(screen.getByText('Backend-aware timeout')).toBeInTheDocument()
    expect(screen.getByText('not_certified', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('REG-007')).toBeInTheDocument()
    expect(screen.getByText('Gateway query forwarding fixed.')).toBeInTheDocument()
    expect(screen.getByText('phase-6-4-pause')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows a safe unavailable state and does not render default certification', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue({ status: 'STATUS_UNAVAILABLE' } as any)
    render(<RegressionHealthPage />)
    expect(await screen.findByText('Regression health unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('CERTIFIED')).not.toBeInTheDocument()
  })

  it('handles an invalid response as unavailable', async () => {
    vi.mocked(fetchRegressionHealth).mockResolvedValue({} as any)
    render(<RegressionHealthPage />)
    await waitFor(() => expect(screen.getByText('Regression health unavailable.')).toBeInTheDocument())
  })

  it('handles empty capabilities with an explicit empty state', async () => {
    const empty = response()
    empty.capabilities = []
    vi.mocked(fetchRegressionHealth).mockResolvedValue(empty as any)
    render(<RegressionHealthPage />)
    expect(await screen.findByText('No capabilities reported')).toBeInTheDocument()
  })
})
