import { Fragment, useEffect, useMemo, useState } from 'react'
import type { IntegrationHealthRecord, IntegrationHealthResponse } from '../api'
import { fetchIntegrationHealth } from '../api'
import StatusBadge from '../components/StatusBadge'
import { Card, EmptyState, ErrorState, LoadingState, SectionHeader } from '../components/ui'

function isResponse(value: unknown): value is IntegrationHealthResponse {
  if (!value || typeof value !== 'object') return false
  const data = value as Partial<IntegrationHealthResponse>
  return typeof data.schema_version === 'string'
    && typeof data.generated_at === 'string'
    && Array.isArray(data.integrations)
    && !!data.summary
    && !!data.data_sources
    && Array.isArray(data.warnings)
}

function formatDate(value: string | null): string {
  if (!value) return 'Not checked'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function label(value: string): string {
  return value.replace(/_/g, ' ')
}

function SummaryCard({ label: title, value, status }: { label: string; value: number; status?: string }) {
  return (
    <Card padding="14px 16px">
      <div style={{ color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{title}</div>
      <div style={{ color: 'var(--text)', fontSize: 24, fontWeight: 700, marginTop: 6 }}>{value}</div>
      {status && <div style={{ marginTop: 7 }}><StatusBadge status={status} /></div>}
    </Card>
  )
}

function Detail({ row }: { row: IntegrationHealthRecord }) {
  return (
    <tr>
      <td colSpan={9} style={{ padding: 0 }}>
        <div style={{ padding: '14px 16px', background: 'var(--bg2)', borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, fontSize: 12 }}>
            <div><strong>Integration ID</strong><div>{row.integration_id}</div></div>
            <div><strong>Plugin</strong><div>{row.plugin}</div></div>
            <div><strong>Implementation</strong><div><StatusBadge status={row.implementation_status} /></div></div>
            <div><strong>Plugin signal</strong><div><StatusBadge status={row.plugin_status} /></div></div>
            <div><strong>Authentication</strong><div><StatusBadge status={row.authentication.requirement} /></div></div>
            <div><strong>Credential metadata</strong><div>{row.authentication.credential_configured === null ? 'Unknown' : row.authentication.credential_configured ? 'Configured' : 'Not configured'}</div></div>
            <div><strong>Health signal</strong><div>{label(row.health_signal_capability)}</div></div>
            <div><strong>API type</strong><div>{row.provider.api_type}</div></div>
            <div><strong>Version</strong><div>{row.version ?? 'Not recorded'}</div></div>
            <div><strong>Last checked</strong><div>{formatDate(row.provider.last_checked)}</div></div>
            <div><strong>Certification</strong><div>{label(row.certification_status)}</div></div>
          </div>
          <div style={{ marginTop: 14 }}>
            <strong style={{ fontSize: 12 }}>Evidence</strong>
            {row.evidence.length === 0 ? <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 5 }}>No evidence recorded.</div> : (
              <ul style={{ margin: '6px 0 0 18px', padding: 0, color: 'var(--muted)', fontSize: 12 }}>
                {row.evidence.map((item, index) => <li key={`${item.source}-${index}`}>{label(item.source)}: {item.description}{item.timestamp ? ` (${formatDate(item.timestamp)})` : ''}</li>)}
              </ul>
            )}
          </div>
          {row.warnings.length > 0 && <div style={{ color: 'var(--amber)', fontSize: 12, marginTop: 10 }}>Warnings: {row.warnings.join('; ')}</div>}
        </div>
      </td>
    </tr>
  )
}

export default function IntegrationHealthPage() {
  const [data, setData] = useState<IntegrationHealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('ALL')
  const [providerStatus, setProviderStatus] = useState('ALL')
  const [readiness, setReadiness] = useState('ALL')
  const [configuration, setConfiguration] = useState('ALL')
  const [signal, setSignal] = useState('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void fetchIntegrationHealth().then(response => {
      if (!active) return
      if (!isResponse(response)) throw new Error('Invalid integration health response')
      setData(response)
      setError(null)
    }).catch(reason => {
      if (!active) return
      const message = String(reason)
      setError(/\b401\b|\b403\b/.test(message) ? 'You are not authorized to view integration health.' : 'Integration Health unavailable.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    const query = search.trim().toLowerCase()
    return data.integrations.filter(row => {
      const haystack = `${row.integration_id} ${row.display_name} ${row.provider.name}`.toLowerCase()
      return (!query || haystack.includes(query))
        && (category === 'ALL' || row.category === category)
        && (providerStatus === 'ALL' || row.provider.status === providerStatus)
        && (readiness === 'ALL' || row.readiness_status === readiness)
        && (configuration === 'ALL' || row.configuration_status === configuration)
        && (signal === 'ALL' || row.health_signal_capability === signal)
    })
  }, [category, configuration, data, providerStatus, readiness, search, signal])

  if (loading) return <div><LoadingState label="Loading integration health…" /></div>
  if (error || !data) return <div><SectionHeader title="Integration Health" description="Read-only biological and data-provider readiness." /><ErrorState message={error ?? 'Integration Health unavailable.'} /></div>

  const categories = [...new Set(data.integrations.map(row => row.category))].sort()
  const providerStatuses = [...new Set(data.integrations.map(row => row.provider.status))].sort()
  const readinessStates = [...new Set(data.integrations.map(row => row.readiness_status))].sort()
  const configStates = [...new Set(data.integrations.map(row => row.configuration_status))].sort()
  const signals = [...new Set(data.integrations.map(row => row.health_signal_capability))].sort()
  const summary = data.summary

  return (
    <div>
      <SectionHeader title="Integration Health" description="Read-only availability and readiness of external biological and data providers." />
      <Card style={{ marginBottom: 20 }}>
        <div style={{ color: 'var(--muted)', fontSize: 12 }}>Provider readiness is independent from plugin liveness, deployment health, and regression certification. This page reads cached server-side evidence and never starts probes.</div>
      </Card>

      <section aria-labelledby="integration-summary-heading" style={{ marginBottom: 24 }}>
        <h2 id="integration-summary-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Readiness Summary</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12 }}>
          <SummaryCard label="Total" value={summary.total} />
          <SummaryCard label="Ready" value={summary.ready} status="READY" />
          <SummaryCard label="Degraded" value={summary.degraded} status="DEGRADED" />
          <SummaryCard label="Not Ready" value={summary.not_ready} status="NOT_READY" />
          <SummaryCard label="Disabled" value={summary.disabled} status="DISABLED" />
          <SummaryCard label="Unknown" value={summary.unknown} status="UNKNOWN" />
        </div>
      </section>

      <section aria-labelledby="data-sources-heading" style={{ marginBottom: 24 }}>
        <h2 id="data-sources-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Evidence / Data Sources</h2>
        <Card padding="14px 16px"><div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>{Object.entries(data.data_sources).map(([source, status]) => <div key={source}><div style={{ color: 'var(--muted)', fontSize: 11 }}>{label(source)}</div><StatusBadge status={status} /></div>)}</div></Card>
      </section>

      <section aria-labelledby="integrations-heading">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <h2 id="integrations-heading" style={{ fontSize: 15, color: 'var(--text)', margin: 0 }}>Biological / Data Integrations</h2>
          <span style={{ color: 'var(--muted)', fontSize: 12 }}>{filtered.length} of {data.integrations.length} shown</span>
        </div>
        <Card padding="12px 14px" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <input aria-label="Search integrations" placeholder="Search name or provider" value={search} onChange={event => setSearch(event.target.value)} style={{ minWidth: 220, flex: '1 1 220px' }} />
            {([['Category', category, setCategory, categories], ['Provider', providerStatus, setProviderStatus, providerStatuses], ['Readiness', readiness, setReadiness, readinessStates], ['Configuration', configuration, setConfiguration, configStates], ['Signal', signal, setSignal, signals]] as const).map(([title, value, setter, options]) => <label key={title} style={{ color: 'var(--muted)', fontSize: 11 }}>{title}<select aria-label={`${title} filter`} value={value} onChange={event => setter(event.target.value)} style={{ display: 'block', marginTop: 3 }}><option value="ALL">All</option>{options.map(option => <option key={option} value={option}>{label(option)}</option>)}</select></label>)}
          </div>
        </Card>
        {filtered.length === 0 ? <EmptyState title="No integrations match these filters" /> : <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th>Integration</th><th>Provider</th><th>Category</th><th>Enabled</th><th>Configuration</th><th>Provider</th><th>Readiness</th><th>Freshness</th><th>Last Checked</th><th>Failure</th><th>Details</th></tr></thead>
            <tbody>{filtered.map(row => <Fragment key={row.integration_id}>
              <tr key={row.integration_id}>
                <td><strong>{row.display_name}</strong><div style={{ color: 'var(--muted)', fontSize: 11 }}>{row.integration_id}</div></td>
                <td>{row.provider.name}</td><td>{label(row.category)}</td><td><StatusBadge status={row.enabled_status} /></td><td><StatusBadge status={row.configuration_status} /></td><td><StatusBadge status={row.provider.status} /></td><td><StatusBadge status={row.readiness_status} /></td><td><StatusBadge status={row.freshness} /></td><td>{formatDate(row.provider.last_checked)}</td><td>{row.provider.failure_reason ? <StatusBadge status={row.provider.failure_reason} /> : '—'}</td>
                <td><button type="button" aria-expanded={expanded === row.integration_id} onClick={() => setExpanded(current => current === row.integration_id ? null : row.integration_id)}>{expanded === row.integration_id ? 'Hide' : 'Details'}</button></td>
              </tr>
              {expanded === row.integration_id && <Detail key={`${row.integration_id}-detail`} row={row} />}
            </Fragment> )}</tbody>
          </table>
        </div>}
      </section>
      {data.warnings.length > 0 && <Card style={{ marginTop: 20, color: 'var(--amber)', fontSize: 12 }}>Warnings: {data.warnings.join('; ')}</Card>}
    </div>
  )
}
