import { useCallback, useEffect, useState } from 'react'
import type {
  RegressionCapability,
  RegressionFinding,
  RegressionHealthResponse,
  RegressionStatus,
} from '../api'
import { fetchRegressionHealth } from '../api'
import StatusBadge from '../components/StatusBadge'
import {
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionHeader,
} from '../components/ui'

function isRegressionHealthResponse(value: unknown): value is RegressionHealthResponse {
  if (!value || typeof value !== 'object') return false
  const data = value as Partial<RegressionHealthResponse>
  return data.schema_version === '1.0'
    && typeof data.generated_at === 'string'
    && !!data.source
    && !!data.phases?.p0 && !!data.phases?.p1 && !!data.phases?.p2
    && Array.isArray(data.capabilities)
    && Array.isArray(data.findings)
    && Array.isArray(data.technical_debt)
    && !!data.freshness
    && ['CURRENT', 'STALE', 'UNKNOWN'].includes(data.freshness.status)
}

function formatDate(value?: string | null): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function PhaseCard({ phase, data }: { phase: 'p0' | 'p1' | 'p2'; data: RegressionHealthResponse }) {
  const value = data.phases[phase]
  return (
    <Card>
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 }}>
        {phase}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
        <StatusBadge status={value.status} />
        <StatusBadge status={value.certification_status} />
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 12 }}>
        Last certified: {formatDate(value.last_certified_at)}
      </div>
    </Card>
  )
}

function capabilityRow(capability: RegressionCapability) {
  return capability
}

function capabilityStatus(status: RegressionStatus) {
  return <StatusBadge status={status} />
}

function findingsRows(findings: RegressionFinding[]) {
  return findings
}

export default function RegressionHealthPage() {
  const [data, setData] = useState<RegressionHealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetchRegressionHealth()
      if (!isRegressionHealthResponse(response)) throw new Error('Invalid regression health response')
      setData(response)
      setError(null)
    } catch (reason) {
      setData(null)
      const message = String(reason)
      setError (/\b401\b/.test(message) || /\b403\b/.test(message)
        ? 'You are not authorized to view regression health.'
        : 'Regression health unavailable.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  if (loading) return <div><LoadingState label="Loading regression health…" /></div>
  if (error || !data) {
    return (
      <div>
        <SectionHeader title="Regression Health" description="Read-only ecosystem certification status." />
        <ErrorState message={error ?? 'Regression health unavailable.'} onRetry={() => void load()} />
      </div>
    )
  }

  const freshness = data.freshness.status
  return (
    <div>
      <SectionHeader
        title="Regression Health"
        description="Read-only, reviewed end-to-end certification status for the OmniBioAI ecosystem."
      />

      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16 }}>
          <div><strong style={{ color: 'var(--text)' }}>Runtime Health</strong><div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>Is the platform currently reachable?</div></div>
          <div><strong style={{ color: 'var(--text)' }}>Regression Health</strong><div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>Has ecosystem behavior been validated end-to-end?</div></div>
          <div><strong style={{ color: 'var(--text)' }}>Certification Freshness</strong><div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>When was the certification artifact generated?</div></div>
        </div>
      </Card>

      <section aria-labelledby="phase-summary-heading" style={{ marginBottom: 24 }}>
        <h2 id="phase-summary-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Certification Summary</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
          {(['p0', 'p1', 'p2'] as const).map(phase => <PhaseCard key={phase} phase={phase} data={data} />)}
        </div>
      </section>

      <section aria-labelledby="freshness-heading" style={{ marginBottom: 24 }}>
        <h2 id="freshness-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Certification Freshness</h2>
        <Card style={{ borderColor: freshness === 'STALE' ? 'var(--amber)' : 'var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <StatusBadge status={freshness} />
            {freshness === 'STALE' && <span role="alert" style={{ color: 'var(--amber)', fontSize: 12 }}>Certification data is stale; underlying certification states are preserved.</span>}
            {freshness === 'UNKNOWN' && <span style={{ color: 'var(--muted)', fontSize: 12 }}>Freshness could not be determined from the artifact timestamp.</span>}
          </div>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginTop: 14, fontSize: 12, color: 'var(--muted)' }}>
            <span>Generated: {formatDate(data.generated_at)}</span>
            <span>Source commit: <code>{data.source.commit}</code></span>
            <span>Stale after: {data.freshness.stale_after_hours} hours</span>
          </div>
        </Card>
      </section>

      <section aria-labelledby="capabilities-heading" style={{ marginBottom: 24 }}>
        <h2 id="capabilities-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Current Capabilities</h2>
        {data.capabilities.length === 0 ? <EmptyState title="No capabilities reported" /> : (
          <div style={{ overflowX: 'auto' }}>
            <DataTable
              rows={data.capabilities.map(capabilityRow)}
              rowKey={row => row.id}
              columns={[
                { key: 'label', header: 'Capability', render: row => <strong>{row.label}</strong> },
                { key: 'implementation', header: 'Implementation', render: row => capabilityStatus(row.implementation_status) },
                { key: 'tests', header: 'Tests', render: row => capabilityStatus(row.test_status) },
                { key: 'live', header: 'Live', render: row => capabilityStatus(row.live_status) },
                { key: 'certification', header: 'Certification', render: row => capabilityStatus(row.certification_status) },
                { key: 'validated', header: 'Last Validated', render: row => formatDate(row.last_validated_at) },
              ]}
            />
          </div>
        )}
      </section>

      <section aria-labelledby="findings-heading" style={{ marginBottom: 24 }}>
        <h2 id="findings-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Regression Findings</h2>
        {data.findings.length === 0 ? <EmptyState title="No regression findings reported" /> : (
          <div style={{ overflowX: 'auto' }}>
            <DataTable
              rows={findingsRows(data.findings)}
              rowKey={row => row.id}
              columns={[
                { key: 'id', header: 'Finding', render: row => <strong>{row.id}</strong> },
                { key: 'status', header: 'Status', render: row => <StatusBadge status={row.status} /> },
                { key: 'validation', header: 'Validation', render: row => <StatusBadge status={row.validation_status} /> },
                { key: 'summary', header: 'Summary', render: row => row.summary },
                { key: 'validated', header: 'Last Validated', render: row => formatDate(row.last_validated_at) },
              ]}
            />
          </div>
        )}
      </section>

      <section aria-labelledby="debt-heading">
        <h2 id="debt-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Technical Debt / Paused Items</h2>
        {data.technical_debt.length === 0 ? <EmptyState title="No technical debt reported" /> : (
          <div style={{ display: 'grid', gap: 10 }}>
            {data.technical_debt.map(item => (
              <Card key={item.id} padding="12px 16px">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <strong style={{ color: 'var(--text)' }}>{item.id}</strong>
                  <StatusBadge status={item.status} />
                </div>
                <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 6 }}>{item.summary}</div>
                {item.notes && <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 4 }}>{item.notes}</div>}
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
