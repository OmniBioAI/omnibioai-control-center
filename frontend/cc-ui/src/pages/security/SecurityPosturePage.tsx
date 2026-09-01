import { useCallback, useEffect, useState } from 'react'
import type { SecurityControlItem, SecurityEvidenceItem, SecurityFindingItem, SecurityPostureResponse } from '../../api'
import { fetchSecurityPosture } from '../../api'
import { classifyAuthError, formatDate } from '../../format'
import StatusBadge from '../../components/StatusBadge'
import { Card, EmptyState, ErrorState, LoadingState, SectionHeader, SessionExpiredState, StatCard } from '../../components/ui'

type LoadState =
  | { status: 'loading' }
  | { status: 'session' }
  | { status: 'denied' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: SecurityPostureResponse }

function isResponse(value: unknown): value is SecurityPostureResponse {
  const isRecord = (item: unknown): item is Record<string, unknown> => !!item && typeof item === 'object'
  if (!isRecord(value)) return false
  const data = value as Partial<SecurityPostureResponse>
  const summary = data.summary
  const isTimestamp = (item: unknown): item is string => typeof item === 'string' && !Number.isNaN(Date.parse(item))
  const isEvidence = (item: unknown): item is SecurityEvidenceItem => {
    if (!isRecord(item)) return false
    return typeof item.type === 'string' && typeof item.repository === 'string'
      && typeof item.identifier === 'string' && typeof item.status === 'string'
      && (item.validated_at === null || isTimestamp(item.validated_at))
      && typeof item.freshness === 'string'
      && (item.description === undefined || typeof item.description === 'string')
  }
  const isFinding = (item: unknown): item is SecurityFindingItem => {
    if (!isRecord(item)) return false
    return typeof item.finding_id === 'string' && typeof item.title === 'string'
      && typeof item.type === 'string' && Array.isArray(item.control_ids)
      && item.control_ids.every(controlId => typeof controlId === 'string')
      && (item.source === undefined || typeof item.source === 'string')
      && (item.validated_at === null || item.validated_at === undefined || isTimestamp(item.validated_at))
      && (item.summary === undefined || typeof item.summary === 'string')
  }
  const isControl = (item: unknown): item is SecurityControlItem => {
    if (!isRecord(item)) return false
    const control = item as Partial<SecurityControlItem>
    return typeof control.control_id === 'string' && typeof control.name === 'string'
      && typeof control.category === 'string' && typeof control.priority === 'string'
      && typeof control.implementation_status === 'string' && typeof control.test_status === 'string'
      && typeof control.live_status === 'string' && typeof control.certification_status === 'string'
      && typeof control.freshness === 'string' && typeof control.posture === 'string'
      && Array.isArray(control.evidence) && control.evidence.every(isEvidence)
      && Array.isArray(control.findings) && control.findings.every(isFinding)
      && Array.isArray(control.limitations) && control.limitations.every(item => typeof item === 'string')
  }
  return typeof data.schema_version === 'string'
    && isTimestamp(data.generated_at)
    && !!summary
    && ['verified', 'partial', 'attention', 'unknown', 'not_implemented'].every(key => typeof summary[key as keyof typeof summary] === 'number')
    && Array.isArray(data.categories) && data.categories.every(item => typeof item === 'string')
    && Array.isArray(data.controls) && data.controls.every(isControl)
    && Array.isArray(data.findings) && data.findings.every(isFinding)
    && Array.isArray(data.technical_debt) && data.technical_debt.every(item => isRecord(item)
      && typeof item.debt_id === 'string' && typeof item.summary === 'string'
      && Array.isArray(item.control_ids) && item.control_ids.every(controlId => typeof controlId === 'string'))
    && isRecord(data.data_sources)
    && Object.values(data.data_sources).every(item => typeof item === 'string')
    && Array.isArray(data.limitations) && data.limitations.every(item => typeof item === 'string')
}

function statusClass(status: string): string {
  return status.toLowerCase()
}

const SOURCE_LABELS: Record<string, string> = {
  auth: 'Auth', gateway: 'Gateway', policy: 'Policy', hpc_policy: 'HPC Policy',
  security_audit: 'Security Audit', docker_proxy: 'Docker Proxy',
  regression_health: 'Regression Health', secret_scan: 'Secret Scan',
}

const FINDING_LABELS: Record<string, string> = {
  ACTIVE_ISSUE: 'Active issue', FIXED_HISTORICAL: 'Fixed historical',
  TECHNICAL_DEBT: 'Technical debt', COVERAGE_GAP: 'Coverage gap',
}

function EvidenceList({ evidence }: { evidence: SecurityEvidenceItem[] }) {
  if (evidence.length === 0) return <span style={{ color: 'var(--muted)', fontSize: 12 }}>No evidence recorded.</span>
  return <div style={{ display: 'grid', gap: 10 }}>{evidence.map((item, index) => (
    <div key={`${item.type}-${item.identifier}-${index}`} style={{ display: 'grid', gap: 3, fontSize: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <StatusBadge status={item.type} />
        <StatusBadge status={item.status} />
        {item.freshness !== 'UNKNOWN' && <StatusBadge status={statusClass(item.freshness)} />}
      </div>
      <div style={{ color: 'var(--text2)' }}>{item.description || 'Redacted evidence description'}</div>
      <div style={{ color: 'var(--muted)' }}>{item.repository} · {item.identifier} · Validated {formatDate(item.validated_at)}</div>
    </div>
  ))}</div>
}

function FindingList({ findings }: { findings: SecurityFindingItem[] }) {
  if (findings.length === 0) return <span style={{ color: 'var(--muted)', fontSize: 12 }}>No findings recorded.</span>
  return <div style={{ display: 'grid', gap: 10 }}>{findings.map(finding => (
    <div key={finding.finding_id} style={{ display: 'grid', gap: 3, fontSize: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <StatusBadge status={statusClass(finding.type === 'ACTIVE_ISSUE' ? 'attention' : finding.type === 'FIXED_HISTORICAL' ? 'fixed' : 'unknown')} />
        <strong style={{ color: 'var(--text2)' }}>{FINDING_LABELS[finding.type] ?? finding.type}</strong>
        <span style={{ color: 'var(--muted)' }}>{finding.finding_id}</span>
      </div>
      <div style={{ color: 'var(--text2)' }}>{finding.title}</div>
      {finding.summary && <div style={{ color: 'var(--muted)' }}>{finding.summary}</div>}
    </div>
  ))}</div>
}

function ControlDetails({ control, onClose }: { control: SecurityControlItem; onClose: () => void }) {
  return <Card style={{ marginTop: 16 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 18 }}>
      <div><h2 style={{ fontSize: 15, color: 'var(--text)' }}>{control.name}</h2><div style={{ fontSize: 11, color: 'var(--muted)' }}>{control.control_id}</div></div>
      <button type="button" onClick={onClose} style={{ padding: '6px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--bg2)', color: 'var(--text2)' }}>Close</button>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14, marginBottom: 20 }}>
      {([['Category', control.category], ['Priority', control.priority], ['Implementation', control.implementation_status], ['Tests', control.test_status], ['Live', control.live_status], ['Certification', control.certification_status], ['Freshness', control.freshness], ['Posture', control.posture]] as const).map(([label, value]) => (
        <div key={label}><div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 5 }}>{label}</div><StatusBadge status={statusClass(value)} /></div>
      ))}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div><h3 style={{ fontSize: 13, marginBottom: 8, color: 'var(--text)' }}>Evidence</h3><EvidenceList evidence={control.evidence} /></div>
      <div><h3 style={{ fontSize: 13, marginBottom: 8, color: 'var(--text)' }}>Findings</h3><FindingList findings={control.findings} /></div>
    </div>
    {control.limitations.length > 0 && <div style={{ marginTop: 20 }}><h3 style={{ fontSize: 13, marginBottom: 8, color: 'var(--text)' }}>Limitations</h3><ul style={{ margin: 0, paddingLeft: 20, color: 'var(--muted)', fontSize: 12 }}>{control.limitations.map(item => <li key={item}>{item}</li>)}</ul></div>}
  </Card>
}

function SourceAvailability({ sources }: { sources: Record<string, string> }) {
  return <Card><h2 style={{ fontSize: 14, color: 'var(--text)', marginBottom: 12 }}>Evidence sources</h2><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '0 24px' }}>{Object.entries(sources).sort(([a], [b]) => a.localeCompare(b)).map(([name, value]) => <div key={name} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--border)' }}><span style={{ fontSize: 12, color: 'var(--text2)' }}>{SOURCE_LABELS[name] ?? name}</span><StatusBadge status={statusClass(value)} /></div>)}</div></Card>
}

export default function SecurityPosturePage() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [selected, setSelected] = useState<string | null>(null)
  const load = useCallback(async () => {
    setState({ status: 'loading' })
    try {
      const data: unknown = await fetchSecurityPosture()
      if (!isResponse(data)) throw new Error('invalid response')
      setState({ status: 'ready', data })
    } catch (error) {
      const message = error instanceof Error ? error.message : ''
      const kind = classifyAuthError(message)
      if (kind === 'session') setState({ status: 'session' })
      else if (kind === 'denied') setState({ status: 'denied' })
      else if (message.endsWith(' 503')) setState({ status: 'error', message: 'Security posture data is unavailable.' })
      else setState({ status: 'error', message: 'Security posture data could not be loaded.' })
    }
  }, [])
  useEffect(() => { load() }, [load])

  if (state.status === 'loading') return <div><LoadingState label="Loading security posture…" /></div>
  if (state.status === 'session') return <div><SessionExpiredState /></div>
  if (state.status === 'denied') return <div><EmptyState title="Permission denied" description="Security Posture requires platform-wide security administration access." /></div>
  if (state.status === 'error') return <div><ErrorState message={state.message} onRetry={load} /></div>

  const { data } = state
  const control = selected ? data.controls.find(item => item.control_id === selected) : undefined
  return <div>
    <SectionHeader title="Security Posture" description="Evidence-backed verification of security controls across the OmniBioAI ecosystem." />
    <Card style={{ marginBottom: 20 }}><div style={{ fontSize: 13, color: 'var(--text2)' }}>Security Overview shows current operational activity. Security Posture shows the implementation, test, runtime, certification, and freshness evidence behind each control. This page is read-only.</div><div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>Schema {data.schema_version} · Generated {formatDate(data.generated_at)}</div></Card>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 20 }}>
      <StatCard label="Verified" value={data.summary.verified} accent="green" />
      <StatCard label="Partial" value={data.summary.partial} accent="amber" />
      <StatCard label="Attention" value={data.summary.attention} accent="red" />
      <StatCard label="Unknown" value={data.summary.unknown} />
      <StatCard label="Not Implemented" value={data.summary.not_implemented} />
    </div>
    <div style={{ display: 'grid', gap: 20 }}>
      <SourceAvailability sources={data.data_sources} />
      <Card>
        <h2 style={{ fontSize: 14, color: 'var(--text)', marginBottom: 12 }}>Security controls</h2>
        {data.controls.length === 0 ? <EmptyState title="No controls available" description="No control evidence was returned." /> : <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}><thead><tr>{['Control', 'Category', 'Priority', 'Implementation', 'Tests', 'Live', 'Certification', 'Freshness', 'Posture'].map(label => <th key={label} style={{ textAlign: 'left', padding: '9px 8px', color: 'var(--muted)', fontSize: 10, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{label}</th>)}</tr></thead><tbody>{data.controls.map(item => <tr key={item.control_id} style={{ borderTop: '1px solid var(--border)' }}><td style={{ padding: '10px 8px', minWidth: 190 }}><button type="button" onClick={() => setSelected(item.control_id)} aria-expanded={selected === item.control_id} style={{ border: 0, background: 'transparent', padding: 0, textAlign: 'left', color: 'var(--accent)', cursor: 'pointer' }}><strong>{item.name}</strong><div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 3 }}>{item.control_id}</div></button></td><td style={{ padding: '10px 8px', whiteSpace: 'nowrap' }}>{item.category}</td><td style={{ padding: '10px 8px' }}>{item.priority}</td><td style={{ padding: '10px 8px' }}><StatusBadge status={statusClass(item.implementation_status)} /></td><td style={{ padding: '10px 8px' }}><StatusBadge status={statusClass(item.test_status)} /></td><td style={{ padding: '10px 8px' }}><StatusBadge status={statusClass(item.live_status)} /></td><td style={{ padding: '10px 8px' }}><StatusBadge status={statusClass(item.certification_status)} /></td><td style={{ padding: '10px 8px' }}><StatusBadge status={statusClass(item.freshness)} /></td><td style={{ padding: '10px 8px' }}><StatusBadge status={statusClass(item.posture)} /></td></tr>)}</tbody></table></div>}
      </Card>
      {control && <ControlDetails control={control} onClose={() => setSelected(null)} />}
      {(data.limitations.length > 0 || data.technical_debt.length > 0 || data.findings.length > 0) && <Card><h2 style={{ fontSize: 14, color: 'var(--text)', marginBottom: 12 }}>Posture limitations and findings</h2>{data.limitations.map(item => <div key={item} style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 7 }}>{item}</div>)}{data.technical_debt.map(item => <div key={item.debt_id} style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 7 }}><StatusBadge status="technical_debt" /> {item.summary}</div>)}<FindingList findings={data.findings} /></Card>}
    </div>
  </div>
}
