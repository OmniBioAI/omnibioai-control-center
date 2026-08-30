import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  DeploymentHealthResponse,
  DeploymentServiceView,
} from '../api'
import { fetchDeploymentHealth } from '../api'
import { classifyAuthError } from '../format'
import StatusBadge from '../components/StatusBadge'
import {
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageContainer,
  SectionHeader,
  SessionExpiredState,
  StatCard,
} from '../components/ui'

// DH-3: consumes DH-2's GET /deployment-health/data (rewritten to the
// backend's GET /deployment-health -- see docker/nginx/api-proxy.conf
// and api.ts's own module comment for the REG-010-style SPA/API split).
// This page performs no health/dependency computation of its own -- the
// backend is authoritative for every intrinsic/effective status, image
// comparison, and evidence value rendered here; this file only renders
// what DH-2 already decided.

function isDeploymentHealthResponse(value: unknown): value is DeploymentHealthResponse {
  if (!value || typeof value !== 'object') return false
  const data = value as Partial<DeploymentHealthResponse>
  return typeof data.generated_at === 'string'
    && typeof data.baseline === 'string'
    && !!data.summary && typeof data.summary.total === 'number'
    && Array.isArray(data.services)
    && !!data.data_sources
    && Array.isArray(data.warnings)
}

type LoadState =
  | { status: 'loading' }
  | { status: 'session' }
  | { status: 'denied' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: DeploymentHealthResponse }

function classify(message: string): 'session' | 'denied' | 'unavailable' | 'error' {
  if (message.endsWith(' 503')) return 'unavailable'
  const kind = classifyAuthError(message)
  if (kind === 'session') return 'session'
  if (kind === 'denied') return 'denied'
  return 'error'
}

const DATA_SOURCE_LABEL: Record<string, string> = {
  compose: 'Compose', docker: 'Docker', application_probe: 'Application Probe',
  prometheus: 'Prometheus', regression_health: 'Regression Artifact',
}

function DataSourceBadge({ name, value }: { name: string; value: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '8px 0' }}>
      <span style={{ fontSize: 12, color: 'var(--text2)' }}>{DATA_SOURCE_LABEL[name] ?? name}</span>
      <StatusBadge status={value} />
    </div>
  )
}

/** A service is "unknown ownership" (a legitimate third-party
 * infrastructure component, e.g. MySQL/Redis/Prometheus -- DH-1's own
 * documented behavior) not an error. Rendered plainly, distinct from
 * and never conflated with the health badges next to it. */
function RepositoryCell({ repository }: { repository: string | null }) {
  if (repository) return <code style={{ fontSize: 12 }}>{repository}</code>
  return <span style={{ fontSize: 12, color: 'var(--muted)', fontStyle: 'italic' }}>Unknown ownership</span>
}

/** HARD REQUIREMENT (DH-3 section 7): intrinsic and effective health are
 * always two distinct badges, never collapsed into one. When they
 * differ, the reason (from the backend's own effective_evidence) is
 * shown alongside -- never implied, never guessed here. */
function HealthCells({ service }: { service: DeploymentServiceView }) {
  const differs = service.health.intrinsic !== service.health.effective
  const reason = service.health.effective_evidence[0]?.detail
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 10, color: 'var(--muted)', width: 58 }}>Intrinsic</span>
        <StatusBadge status={service.health.intrinsic} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 10, color: 'var(--muted)', width: 58 }}>Effective</span>
        <StatusBadge status={service.health.effective} />
      </div>
      {differs && reason && (
        <div style={{ fontSize: 10, color: 'var(--muted)', maxWidth: 220 }}>{reason}</div>
      )}
    </div>
  )
}

function CompletenessCell({ service }: { service: DeploymentServiceView }) {
  if (service.completeness.is_complete) {
    return <span style={{ fontSize: 11, color: 'var(--muted)' }}>Complete</span>
  }
  return (
    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
      Partial ({service.completeness.missing_fields.join(', ')})
    </span>
  )
}

function EvidenceList({ evidence }: { evidence: { source: string; detail: string }[] }) {
  if (evidence.length === 0) return <EmptyState title="No evidence recorded" />
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {evidence.map((item, i) => (
        <div key={i} style={{ display: 'flex', gap: 10, fontSize: 12 }}>
          <code style={{ color: 'var(--muted)', flexShrink: 0 }}>{item.source}</code>
          <span style={{ color: 'var(--text2)' }}>{item.detail}</span>
        </div>
      ))}
    </div>
  )
}

function DependencyList({ dependencies }: { dependencies: DeploymentServiceView['dependencies'] }) {
  if (dependencies.length === 0) return <EmptyState title="No declared dependencies" />
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {dependencies.map((dep, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase' }}>
            {dep.relationship}
          </span>
          <span aria-hidden style={{ color: 'var(--muted)' }}>→</span>
          <code>{dep.to_service}</code>
          <StatusBadge status={dep.target_intrinsic_health} />
        </div>
      ))}
    </div>
  )
}

function ServiceDetailPanel({ service, onClose }: { service: DeploymentServiceView; onClose: () => void }) {
  const img = service.deployment.image
  return (
    <Card style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{service.display_name}</div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>{service.service_id}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          style={{
            fontSize: 12, fontWeight: 600, padding: '6px 12px',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            background: 'var(--bg2)', color: 'var(--text2)',
          }}
        >
          Close
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Category</div>
          <div style={{ fontSize: 13, color: 'var(--text2)' }}>{service.category}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Repository</div>
          <RepositoryCell repository={service.repository} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Build configured</div>
          <div style={{ fontSize: 13, color: 'var(--text2)' }}>{service.deployment.build_configured ? 'Yes' : 'No'}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Healthcheck configured</div>
          <div style={{ fontSize: 13, color: 'var(--text2)' }}>{service.deployment.healthcheck_configured ? 'Yes' : 'No'}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Ports</div>
          <div style={{ fontSize: 13, color: 'var(--text2)' }}>{service.deployment.ports.length > 0 ? service.deployment.ports.join(', ') : 'None declared'}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Dependency count</div>
          <div style={{ fontSize: 13, color: 'var(--text2)' }}>{service.dependencies.length}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Metadata completeness</div>
          <CompletenessCell service={service} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Image comparison</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <StatusBadge status={service.image_comparison.status} />
            {service.image_comparison.status !== 'unknown' && (
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                {service.image_comparison.configured} vs {service.image_comparison.running}
              </span>
            )}
          </div>
        </div>
      </div>

      {img && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>Configured image</div>
          <code style={{ fontSize: 12 }}>{img.raw}</code>
          {img.is_untagged && <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--muted)' }}>(untagged)</span>}
          {img.is_latest_tag && <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--muted)' }}>(latest -- not a verified version)</span>}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 20 }}>
        <div>
          <h3 style={{ fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>Health</h3>
          <HealthCells service={service} />
        </div>
        <div>
          <h3 style={{ fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>Runtime</h3>
          <div style={{ fontSize: 12, color: 'var(--text2)', display: 'grid', gap: 4 }}>
            <div>Present: {service.runtime.present ? 'Yes' : 'No'}</div>
            <div>Running: {service.runtime.running === null ? 'Unknown' : service.runtime.running ? 'Yes' : 'No'}</div>
            <div>Docker healthcheck: {service.runtime.docker_health ?? 'None reported'}</div>
          </div>
        </div>
      </div>

      <div style={{ marginBottom: 20 }}>
        <h3 style={{ fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>Dependencies</h3>
        <DependencyList dependencies={service.dependencies} />
      </div>

      <div>
        <h3 style={{ fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>Evidence</h3>
        <EvidenceList evidence={service.evidence} />
      </div>
    </Card>
  )
}

export default function DeploymentHealthPage() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(null)

  const load = useCallback(() => {
    setState({ status: 'loading' })
    fetchDeploymentHealth()
      .then(response => {
        if (!isDeploymentHealthResponse(response)) throw new Error('Invalid deployment health response')
        setState({ status: 'ready', data: response })
      })
      .catch((reason: unknown) => {
        const message = reason instanceof Error ? reason.message : String(reason)
        const kind = classify(message)
        if (kind === 'session') setState({ status: 'session' })
        else if (kind === 'denied') setState({ status: 'denied' })
        else if (kind === 'unavailable') setState({ status: 'error', message: 'Deployment health data is unavailable.' })
        else setState({ status: 'error', message: 'Deployment health unavailable.' })
      })
  }, [])

  useEffect(load, [load])

  const selectedService = useMemo(() => {
    if (state.status !== 'ready' || !selectedServiceId) return null
    return state.data.services.find(s => s.service_id === selectedServiceId) ?? null
  }, [state, selectedServiceId])

  if (state.status === 'loading') return <PageContainer><LoadingState label="Loading deployment health…" /></PageContainer>
  if (state.status === 'session') return <PageContainer><SessionExpiredState /></PageContainer>
  if (state.status === 'denied') {
    return (
      <PageContainer>
        <SectionHeader title="Deployment Health" description="Read-only ecosystem deployment and dependency health." />
        <ErrorState message="You are not authorized to view deployment health." />
      </PageContainer>
    )
  }
  if (state.status === 'error') {
    return (
      <PageContainer>
        <SectionHeader title="Deployment Health" description="Read-only ecosystem deployment and dependency health." />
        <ErrorState message={state.message} onRetry={() => void load()} />
      </PageContainer>
    )
  }

  const { data } = state
  const { summary } = data

  return (
    <PageContainer>
      <SectionHeader
        title="Deployment Health"
        description="Read-only, dependency-aware deployment health for the OmniBioAI ecosystem, derived from Compose metadata, Docker state, and application probes."
      />

      <section aria-labelledby="summary-heading" style={{ marginBottom: 24 }}>
        <h2 id="summary-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Summary</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          <StatCard label="Total Services" value={summary.total} />
          <StatCard label="Healthy" value={summary.healthy} accent="green" />
          <StatCard label="Degraded" value={summary.degraded} accent="amber" />
          <StatCard label="Unhealthy" value={summary.unhealthy} accent="red" />
          <StatCard label="Unknown" value={summary.unknown} />
        </div>
      </section>

      <section aria-labelledby="sources-heading" style={{ marginBottom: 24 }}>
        <h2 id="sources-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Evidence / Data Sources</h2>
        <Card>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0 24px' }}>
            {Object.entries(data.data_sources).map(([name, value]) => (
              <DataSourceBadge key={name} name={name} value={value} />
            ))}
          </div>
        </Card>
        {data.warnings.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
            {data.warnings.length} metadata warning{data.warnings.length === 1 ? '' : 's'} reported by the backend.
          </div>
        )}
      </section>

      {data.regression_health.availability === 'available' && data.regression_health.phases && (
        <section aria-labelledby="regression-context-heading" style={{ marginBottom: 24 }}>
          <h2 id="regression-context-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>
            Regression Health Context
          </h2>
          <Card>
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
              {Object.entries(data.regression_health.phases).map(([phase, value]) => (
                <div key={phase}>
                  <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', marginBottom: 6 }}>{phase}</div>
                  <StatusBadge status={value.certification_status} />
                </div>
              ))}
            </div>
          </Card>
        </section>
      )}

      <section aria-labelledby="services-heading">
        <h2 id="services-heading" style={{ fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>Services</h2>
        {data.services.length === 0 ? <EmptyState title="No services reported" /> : (
          <div style={{ overflowX: 'auto' }}>
            <DataTable
              rows={data.services}
              rowKey={row => row.service_id}
              columns={[
                {
                  key: 'service', header: 'Service', render: row => (
                    <button
                      type="button"
                      onClick={() => setSelectedServiceId(row.service_id)}
                      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left' }}
                    >
                      <strong style={{ color: 'var(--accent)' }}>{row.display_name}</strong>
                    </button>
                  ),
                },
                { key: 'category', header: 'Category', render: row => row.category },
                { key: 'repository', header: 'Repository', render: row => <RepositoryCell repository={row.repository} /> },
                { key: 'health', header: 'Health', render: row => <HealthCells service={row} /> },
                { key: 'dependencies', header: 'Dependencies', render: row => row.dependencies.length },
                { key: 'completeness', header: 'Metadata', render: row => <CompletenessCell service={row} /> },
              ]}
            />
          </div>
        )}
      </section>

      {selectedService && (
        <ServiceDetailPanel service={selectedService} onClose={() => setSelectedServiceId(null)} />
      )}
    </PageContainer>
  )
}
