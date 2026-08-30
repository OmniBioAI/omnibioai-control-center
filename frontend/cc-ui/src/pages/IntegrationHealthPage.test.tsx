import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IntegrationHealthPage from './IntegrationHealthPage'
import { fetchIntegrationHealth } from '../api'
import type { IntegrationHealthRecord, IntegrationHealthResponse } from '../api'

vi.mock('../api', () => ({ fetchIntegrationHealth: vi.fn() }))

function record(overrides: Partial<IntegrationHealthRecord> = {}): IntegrationHealthRecord {
  return {
    integration_id: 'ncbi', display_name: 'NCBI', category: 'GENOMICS', plugin: 'ncbi',
    implementation_status: 'IMPLEMENTED', enabled_status: 'ENABLED', configuration_status: 'NOT_REQUIRED',
    authentication: { requirement: 'PUBLIC', credential_configured: false }, plugin_status: 'AVAILABLE',
    readiness_status: 'READY', freshness: 'CURRENT', health_signal_capability: 'READY_SIGNAL_EXISTS',
    version: null, test_status: 'UNKNOWN', certification_status: 'UNKNOWN', warnings: [],
    provider: { name: 'NCBI E-utilities', api_type: 'REST', endpoint_family: null, status: 'AVAILABLE', last_checked: '2026-08-30T20:26:49Z', failure_reason: null, version: null },
    evidence: [{ source: 'CACHED_SUCCESS', status: 'AVAILABLE', description: 'Cached readiness result', timestamp: '2026-08-30T20:26:49Z' }],
    ...overrides,
  }
}

function response(integrations: IntegrationHealthRecord[] = [record()]): IntegrationHealthResponse {
  return {
    schema_version: '1.0', generated_at: '2026-08-30T20:30:00Z',
    summary: { total: integrations.length, ready: integrations.filter(i => i.readiness_status === 'READY').length, degraded: integrations.filter(i => i.readiness_status === 'DEGRADED').length, not_ready: integrations.filter(i => i.readiness_status === 'NOT_READY').length, disabled: integrations.filter(i => i.readiness_status === 'DISABLED').length, unknown: integrations.filter(i => i.readiness_status === 'UNKNOWN').length },
    integrations, data_sources: { plugin_registry: 'AVAILABLE', configuration: 'AVAILABLE', readiness_cache: 'AVAILABLE', regression_health: 'UNKNOWN' }, warnings: [],
  }
}

describe('IntegrationHealthPage', () => {
  beforeEach(() => vi.mocked(fetchIntegrationHealth).mockReset())

  it('loads dynamic summary and keeps provider status separate from readiness', async () => {
    vi.mocked(fetchIntegrationHealth).mockResolvedValue(response([record(), record({ integration_id: 'ensembl', display_name: 'Ensembl', readiness_status: 'NOT_READY', provider: { ...record().provider, name: 'Ensembl', status: 'UNAVAILABLE', failure_reason: 'TIMEOUT' } }), record({ integration_id: 'gnomad', display_name: 'gnomAD', readiness_status: 'UNKNOWN', freshness: 'UNKNOWN', plugin_status: 'AVAILABLE', health_signal_capability: 'NO_SAFE_READINESS_SIGNAL', provider: { ...record().provider, name: 'gnomAD', status: 'NOT_CHECKED', last_checked: null }, evidence: [] })]))
    render(<IntegrationHealthPage />)
    expect(await screen.findByText('Readiness Summary')).toBeInTheDocument()
    expect(screen.getAllByText('Ensembl').length).toBeGreaterThan(0)
    expect(screen.getByText('TIMEOUT')).toBeInTheDocument()
    expect(screen.getAllByText('UNAVAILABLE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('NOT_READY').length).toBeGreaterThan(0)
    expect(screen.getByText('NO SAFE READINESS SIGNAL')).toBeInTheDocument()
    expect(screen.getByText('NOT_CHECKED')).toBeInTheDocument()
    expect(screen.getByText('3 of 3 shown')).toBeInTheDocument()
  })

  it('renders configuration, authentication, freshness and evidence in an expandable detail panel', async () => {
    vi.mocked(fetchIntegrationHealth).mockResolvedValue(response([record({ configuration_status: 'UNKNOWN', authentication: { requirement: 'AUTH_REQUIRED', credential_configured: null }, freshness: 'STALE', version: 'release-1', evidence: [{ source: 'PLUGIN_REGISTRY', status: 'AVAILABLE', description: 'Validated manifest', timestamp: null }] })]))
    render(<IntegrationHealthPage />)
    expect(await screen.findByText('NCBI')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))
    expect(screen.getByText('AUTH_REQUIRED')).toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
    expect(screen.getByText('release-1')).toBeInTheDocument()
    expect(screen.getByText(/Validated manifest/)).toBeInTheDocument()
    expect(screen.getByText('STALE')).toBeInTheDocument()
  })

  it('filters client-side and has no probe or mutation controls', async () => {
    vi.mocked(fetchIntegrationHealth).mockResolvedValue(response([record(), record({ integration_id: 'pubchem', display_name: 'PubChem', category: 'DRUG_CHEMISTRY', readiness_status: 'DEGRADED', provider: { ...record().provider, name: 'PubChem', status: 'DEGRADED', failure_reason: 'RATE_LIMIT' } })]))
    render(<IntegrationHealthPage />)
    expect((await screen.findAllByText('PubChem')).length).toBeGreaterThan(0)
    fireEvent.change(screen.getByLabelText('Search integrations'), { target: { value: 'PubChem' } })
    expect(screen.queryByText('NCBI')).not.toBeInTheDocument()
    expect(screen.getAllByText('PubChem').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /Probe Now|Refresh Provider|Enable|Disable|Configure|Credential|Retry|Reset/i })).not.toBeInTheDocument()
    expect(vi.mocked(fetchIntegrationHealth)).toHaveBeenCalledTimes(1)
  })

  it('shows a safe unavailable error without retry or backend detail', async () => {
    vi.mocked(fetchIntegrationHealth).mockResolvedValue({} as IntegrationHealthResponse)
    render(<IntegrationHealthPage />)
    expect(await screen.findByText('Integration Health unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('/private/path')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })
})
