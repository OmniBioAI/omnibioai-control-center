import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { AlertTriangle, History, Info, Search, ShieldAlert } from 'lucide-react'
import {
  APPLICABILITY_LABELS, DEPLOYMENT_LABELS, DOMAIN_LABELS, EXCEPTION_STATUS_LABELS, IMPLEMENTATION_LABELS,
  OPERATIONAL_LABELS, RISK_STATE_LABELS, TESTING_LABELS, VERIFICATION_RESULT_LABELS,
  fetchHipaaControlEvidence, fetchHipaaControlExceptions, fetchHipaaControlRisks,
  fetchHipaaLegacyMappings, fetchHipaaReadinessControls, fetchHipaaReadinessHistory,
  type ApplicabilityStatus, type ControlEvidenceType, type DeploymentStatus, type Domain,
  type HipaaControl, type HipaaControlEvidence, type HipaaControlException,
  type HipaaControlRisk, type HipaaLegacyMapping, type HipaaReadinessHistory,
  type ImplementationStatus, type OperationalVerificationStatus, type RiskState,
  type TestingStatus, type VerificationResult,
} from '../../hipaaCompliance'
import {
  Card, DataTable, EmptyState, ErrorState, LoadingState, SectionHeader,
  SessionExpiredState, StatCard,
} from '../../components/ui'
import { classifyAuthError, formatDate, formatDateOnly } from '../../format'

const CONTROL_PAGE_SIZE = 100

type Tab = 'overview' | 'controls' | 'history' | 'evidence' | 'risks' | 'reports'

type LoadState = {
  controls: HipaaControl[]
  evidence: Record<string, HipaaControlEvidence[]>
  risks: Record<string, HipaaControlRisk[]>
  exceptions: Record<string, HipaaControlException[]>
  history: HipaaReadinessHistory[]
  legacyMappings: HipaaLegacyMapping[]
}

const EMPTY_DATA: LoadState = {
  controls: [], evidence: {}, risks: {}, exceptions: {}, history: [], legacyMappings: [],
}

const statusChipBase: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 700,
  padding: '3px 8px', borderRadius: 999, border: '1px solid var(--border)', whiteSpace: 'nowrap',
}

const mutedText: CSSProperties = { color: 'var(--text2)', fontSize: 12 }
const fieldLabel: CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }
const selectStyle: CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}

const IMPLEMENTATION_ORDER: ImplementationStatus[] = ['implemented', 'partial', 'not_started', 'deferred', 'not_applicable', 'unknown']
const TESTING_ORDER: TestingStatus[] = ['tested', 'partial', 'not_tested', 'failed', 'not_applicable', 'unknown']
const DEPLOYMENT_ORDER: DeploymentStatus[] = ['deployed', 'partial', 'not_deployed', 'not_applicable', 'unknown']
const OPERATIONAL_ORDER: OperationalVerificationStatus[] = ['verified', 'partial', 'not_verified', 'failed', 'not_applicable', 'unknown']
const APPLICABILITY_ORDER: ApplicabilityStatus[] = ['applicable', 'not_applicable', 'deferred', 'unknown']

function badgeColor(label: string): string {
  if (['implemented', 'tested', 'deployed', 'verified', 'pass', 'applicable', 'closed', 'mitigated'].includes(label)) return 'var(--green)'
  if (['partial', 'deferred', 'unknown', 'not_tested', 'not_deployed', 'not_verified'].includes(label)) return 'var(--amber)'
  if (['failed', 'open', 'critical', 'high'].includes(label)) return 'var(--red)'
  return 'var(--muted)'
}

function StatusBadge({ value, label }: { value: string; label: string }) {
  const color = badgeColor(value)
  return <span style={{ ...statusChipBase, color, borderColor: color }}>{label}</span>
}

function UnknownValue({ children = 'Unknown' }: { children?: string }) {
  return <span style={{ ...statusChipBase, color: 'var(--amber)', borderColor: 'var(--amber)' }}>{children}</span>
}

function DashValue({ value }: { value?: string | number | null }) {
  if (value === null || value === undefined || value === '') return <UnknownValue />
  return <>{value}</>
}

function refLabel(refs: HipaaControl['regulatory_reference']) {
  if (refs.length === 0) return 'Unknown'
  return refs.map(r => `${r.citation}${r.label ? ` ${r.label}` : ''}`).join('; ')
}

function safeReference(reference: string) {
  return /^https:\/\//.test(reference)
}

function ReferenceCell({ reference }: { reference: string }) {
  if (safeReference(reference)) {
    return <a href={reference} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>{reference}</a>
  }
  return <span>{reference}</span>
}

function countBy<T, K extends string>(items: T[], getter: (item: T) => K): Record<K, number> {
  const counts = {} as Record<K, number>
  for (const item of items) {
    const key = getter(item)
    counts[key] = (counts[key] ?? 0) + 1
  }
  return counts
}

function sumRecord<T>(record: Record<string, T[]>) {
  return Object.values(record).reduce((sum, rows) => sum + rows.length, 0)
}

function openRiskCount(risks: HipaaControlRisk[]) {
  return risks.filter(r => ['open', 'partial', 'deferred'].includes(r.state)).length
}

function acceptedExceptionCount(exceptions: HipaaControlException[]) {
  return exceptions.filter(e => e.status === 'approved').length
}

function SectionTitle({ title, note }: { title: string; note?: string }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{title}</div>
      {note && <div style={{ ...mutedText, marginTop: 3 }}>{note}</div>}
    </div>
  )
}

function Distribution<T extends string>({ title, counts, order, labels }: { title: string; counts: Record<T, number>; order: readonly T[]; labels: Record<T, string> }) {
  return (
    <Card>
      <SectionTitle title={title} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {order.map(key => (
          <div key={key} style={{ display: 'grid', gridTemplateColumns: 'minmax(110px, 1fr) 48px', gap: 10, alignItems: 'center' }}>
            <StatusBadge value={key} label={labels[key]} />
            <span style={{ textAlign: 'right', fontSize: 16, fontWeight: 700 }}>{counts[key] ?? 0}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function dataForControl<T>(record: Record<string, T[]>, control: HipaaControl): T[] {
  return record[control.control_key] ?? []
}

function useReadinessData() {
  const [data, setData] = useState<LoadState>(EMPTY_DATA)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [session, setSession] = useState(false)
  const [denied, setDenied] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    setSession(false)
    setDenied(false)
    fetchHipaaReadinessControls({ pageSize: CONTROL_PAGE_SIZE })
      .then(async response => {
        const controls = response.items
        const [evidencePairs, riskPairs, exceptionPairs, history, legacyMappings] = await Promise.all([
          Promise.all(controls.map(async c => [c.control_key, await fetchHipaaControlEvidence(c.control_key)] as const)),
          Promise.all(controls.map(async c => [c.control_key, await fetchHipaaControlRisks(c.control_key)] as const)),
          Promise.all(controls.map(async c => [c.control_key, await fetchHipaaControlExceptions(c.control_key)] as const)),
          fetchHipaaReadinessHistory(),
          fetchHipaaLegacyMappings(),
        ])
        setData({
          controls,
          evidence: Object.fromEntries(evidencePairs),
          risks: Object.fromEntries(riskPairs),
          exceptions: Object.fromEntries(exceptionPairs),
          history,
          legacyMappings,
        })
      })
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'session') setSession(true)
        else if (kind === 'denied') setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])
  return { data, loading, error, session, denied, reload: load }
}

export default function HipaaCompliancePage() {
  const [tab, setTab] = useState<Tab>('overview')
  const state = useReadinessData()

  return (
    <div>
      <SectionHeader
        title="HIPAA Readiness"
        description="HIPAA-aligned security controls, implementation status, verification evidence, and identified gaps."
      />
      <div role="tablist" aria-label="HIPAA readiness sections" style={{ display: 'flex', gap: 8, marginBottom: 20, borderBottom: '1px solid var(--border)', overflowX: 'auto' }}>
        {([
          ['overview', 'Overview'], ['controls', 'Controls'], ['history', 'Change History'],
          ['evidence', 'Evidence'], ['risks', 'Risk & Exceptions'], ['reports', 'Reports'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            style={{
              fontSize: 13, fontWeight: 600, padding: '9px 14px', background: 'none', border: 'none',
              borderBottom: tab === key ? '2px solid var(--accent)' : '2px solid transparent',
              color: tab === key ? 'var(--text)' : 'var(--muted)', cursor: 'pointer', whiteSpace: 'nowrap',
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <ReadinessBody tab={tab} {...state} />
    </div>
  )
}

function ReadinessBody({ tab, data, loading, error, session, denied, reload }: ReturnType<typeof useReadinessData> & { tab: Tab }) {
  if (loading) return <LoadingState label="Loading HIPAA readiness catalog..." />
  if (session) return <SessionExpiredState />
  if (denied) {
    return <EmptyState icon={ShieldAlert} title="Permission denied" description="You don't have manage_all_orgs, so HIPAA readiness data can't be shown here. This is enforced by the backend." />
  }
  if (error) return <ErrorState message={`HIPAA readiness data unavailable: ${error}`} onRetry={reload} />
  if (data.controls.length === 0) return <EmptyState icon={Info} title="No readiness controls tracked" description="The initial bounded catalog has not been seeded or is unavailable." />

  if (tab === 'overview') return <OverviewTab data={data} />
  if (tab === 'controls') return <ControlsTab data={data} />
  if (tab === 'history') return <HistoryTab history={data.history} controls={data.controls} />
  if (tab === 'evidence') return <EvidenceTab data={data} />
  if (tab === 'risks') return <RiskExceptionTab data={data} />
  return <ReportsTab data={data} />
}

function OverviewTab({ data }: { data: LoadState }) {
  const evidenceCount = sumRecord(data.evidence)
  const risks = Object.values(data.risks).flat()
  const exceptions = Object.values(data.exceptions).flat()
  const openPartial = data.controls.filter(c => c.implementation_status === 'partial' || c.testing_status === 'partial' || c.deployment_status === 'partial' || c.operational_verification_status === 'partial').length
  const naCount = data.controls.filter(c => c.applicability_status === 'not_applicable').length
  const opVerified = data.controls.filter(c => c.operational_verification_status === 'verified').length
  const implementedCounts = countBy(data.controls, c => c.implementation_status)
  const testingCounts = countBy(data.controls, c => c.testing_status)
  const deploymentCounts = countBy(data.controls, c => c.deployment_status)
  const operationalCounts = countBy(data.controls, c => c.operational_verification_status)
  const recent = data.history.slice(0, 5)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <Info size={16} color="var(--accent)" aria-hidden />
          <div style={mutedText}>Counts are scoped to the initial bounded catalog. They are not a platform-wide HIPAA denominator or legal determination.</div>
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
        <StatCard label="Tracked Controls" value={data.controls.length} accent="blue" />
        <StatCard label="Evidence Records" value={evidenceCount} accent="green" />
        <StatCard label="Open / Partial" value={openPartial} accent={openPartial > 0 ? 'amber' : 'default'} />
        <StatCard label="Accepted Exceptions" value={acceptedExceptionCount(exceptions)} accent="default" />
        <StatCard label="Not Applicable" value={naCount} accent="default" />
        <StatCard label="Operationally Verified" value={opVerified} accent="green" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 16 }}>
        <Distribution title="Implementation" counts={implementedCounts} order={IMPLEMENTATION_ORDER} labels={IMPLEMENTATION_LABELS} />
        <Distribution title="Testing" counts={testingCounts} order={TESTING_ORDER} labels={TESTING_LABELS} />
        <Distribution title="Deployment" counts={deploymentCounts} order={DEPLOYMENT_ORDER} labels={DEPLOYMENT_LABELS} />
        <Distribution title="Operational Verification" counts={operationalCounts} order={OPERATIONAL_ORDER} labels={OPERATIONAL_LABELS} />
      </div>

      <DomainView data={data} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        <Card>
          <SectionTitle title="Open Risks / Gaps" note="Rendered from readiness catalog risk records." />
          {openRiskCount(risks) === 0 ? (
            <div style={mutedText}>No open risks recorded in the readiness catalog.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {risks.filter(r => ['open', 'partial', 'deferred'].includes(r.state)).map(r => (
                <RiskLine key={r.id} risk={r} control={data.controls.find(c => c.id === r.control_id)} />
              ))}
            </div>
          )}
        </Card>
        <Card>
          <SectionTitle title="Recent Activity" note="Append-only readiness change history." />
          {recent.length === 0 ? <div style={mutedText}>No readiness history recorded.</div> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {recent.map(h => <HistoryLine key={h.id} history={h} />)}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function DomainView({ data }: { data: LoadState }) {
  const domains = Array.from(new Set(data.controls.map(c => c.domain))).sort((a, b) => DOMAIN_LABELS[a].localeCompare(DOMAIN_LABELS[b]))
  return (
    <Card>
      <SectionTitle title="Domains" note="Only domains represented by tracked controls are shown." />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
        {domains.map(domain => {
          const controls = data.controls.filter(c => c.domain === domain)
          const risks = controls.flatMap(c => dataForControl(data.risks, c))
          return (
            <div key={domain} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{DOMAIN_LABELS[domain]}</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 6, fontSize: 12, color: 'var(--text2)' }}>
                <span>Controls tracked</span><strong>{controls.length}</strong>
                <span>Implemented</span><strong>{controls.filter(c => c.implementation_status === 'implemented').length}</strong>
                <span>Tested</span><strong>{controls.filter(c => c.testing_status === 'tested').length}</strong>
                <span>Deployment unknown</span><strong>{controls.filter(c => c.deployment_status === 'unknown').length}</strong>
                <span>Operationally verified</span><strong>{controls.filter(c => c.operational_verification_status === 'verified').length}</strong>
                <span>Open risks</span><strong>{openRiskCount(risks)}</strong>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function ControlsTab({ data }: { data: LoadState }) {
  const [domain, setDomain] = useState<Domain | ''>('')
  const [applicability, setApplicability] = useState<ApplicabilityStatus | ''>('')
  const [implementation, setImplementation] = useState<ImplementationStatus | ''>('')
  const [testing, setTesting] = useState<TestingStatus | ''>('')
  const [deployment, setDeployment] = useState<DeploymentStatus | ''>('')
  const [operational, setOperational] = useState<OperationalVerificationStatus | ''>('')
  const [riskState, setRiskState] = useState<RiskState | ''>('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<HipaaControl | null>(null)
  const domains = Array.from(new Set(data.controls.map(c => c.domain))).sort()

  const rows = data.controls.filter(c => {
    const risks = dataForControl(data.risks, c)
    const haystack = `${c.control_key} ${c.title} ${refLabel(c.regulatory_reference)}`.toLowerCase()
    return (!domain || c.domain === domain)
      && (!applicability || c.applicability_status === applicability)
      && (!implementation || c.implementation_status === implementation)
      && (!testing || c.testing_status === testing)
      && (!deployment || c.deployment_status === deployment)
      && (!operational || c.operational_verification_status === operational)
      && (!riskState || risks.some(r => r.state === riskState))
      && (!search || haystack.includes(search.toLowerCase()))
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <FilterCard>
        <SearchBox value={search} onChange={setSearch} label="Search controls" />
        <SelectFilter label="Domain" value={domain} onChange={v => setDomain(v as Domain | '')} options={domains.map(d => [d, DOMAIN_LABELS[d]] as const)} />
        <SelectFilter label="Applicability" value={applicability} onChange={v => setApplicability(v as ApplicabilityStatus | '')} options={APPLICABILITY_ORDER.map(s => [s, APPLICABILITY_LABELS[s]] as const)} />
        <SelectFilter label="Implementation" value={implementation} onChange={v => setImplementation(v as ImplementationStatus | '')} options={IMPLEMENTATION_ORDER.map(s => [s, IMPLEMENTATION_LABELS[s]] as const)} />
        <SelectFilter label="Testing" value={testing} onChange={v => setTesting(v as TestingStatus | '')} options={TESTING_ORDER.map(s => [s, TESTING_LABELS[s]] as const)} />
        <SelectFilter label="Deployment" value={deployment} onChange={v => setDeployment(v as DeploymentStatus | '')} options={DEPLOYMENT_ORDER.map(s => [s, DEPLOYMENT_LABELS[s]] as const)} />
        <SelectFilter label="Operational Verification" value={operational} onChange={v => setOperational(v as OperationalVerificationStatus | '')} options={OPERATIONAL_ORDER.map(s => [s, OPERATIONAL_LABELS[s]] as const)} />
        <SelectFilter label="Risk State" value={riskState} onChange={v => setRiskState(v as RiskState | '')} options={(['open', 'partial', 'mitigated', 'accepted', 'deferred', 'closed'] as RiskState[]).map(s => [s, RISK_STATE_LABELS[s]] as const)} />
      </FilterCard>
      <div style={{ overflowX: 'auto' }}>
        <DataTable
          rowKey={c => c.control_key}
          rows={rows}
          emptyLabel="No controls match these filters."
          columns={[
            { key: 'control', header: 'Control', render: c => <button onClick={() => setSelected(c)} style={{ color: 'var(--accent)', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 700 }}>{c.control_key}</button> },
            { key: 'title', header: 'Title', render: c => c.title },
            { key: 'domain', header: 'Domain', render: c => DOMAIN_LABELS[c.domain] },
            { key: 'ref', header: 'Regulatory Reference', render: c => refLabel(c.regulatory_reference) },
            { key: 'app', header: 'Applicability', render: c => <StatusBadge value={c.applicability_status} label={APPLICABILITY_LABELS[c.applicability_status]} /> },
            { key: 'impl', header: 'Implementation', render: c => <StatusBadge value={c.implementation_status} label={IMPLEMENTATION_LABELS[c.implementation_status]} /> },
            { key: 'test', header: 'Testing', render: c => <StatusBadge value={c.testing_status} label={TESTING_LABELS[c.testing_status]} /> },
            { key: 'dep', header: 'Deployment', render: c => <StatusBadge value={c.deployment_status} label={DEPLOYMENT_LABELS[c.deployment_status]} /> },
            { key: 'op', header: 'Operational Verification', render: c => <StatusBadge value={c.operational_verification_status} label={OPERATIONAL_LABELS[c.operational_verification_status]} /> },
            { key: 'evidence', header: 'Evidence', render: c => dataForControl(data.evidence, c).length },
            { key: 'risks', header: 'Open Risks', render: c => openRiskCount(dataForControl(data.risks, c)) },
          ]}
        />
      </div>
      {selected && <ControlDetailModal control={selected} data={data} onClose={() => setSelected(null)} />}
    </div>
  )
}

function ControlDetailModal({ control, data, onClose }: { control: HipaaControl; data: LoadState; onClose: () => void }) {
  const evidence = dataForControl(data.evidence, control)
  const risks = dataForControl(data.risks, control)
  const exceptions = dataForControl(data.exceptions, control)
  const history = data.history.filter(h => h.entity_id === control.control_key || String(h.new_state?.control_key ?? '') === control.control_key)
  return (
    <div role="dialog" aria-modal="true" aria-label={`Control detail ${control.control_key}`} onClick={e => { if (e.target === e.currentTarget) onClose() }} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.62)', zIndex: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: 20, width: 920, maxWidth: '96vw', maxHeight: '88vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 700 }}>{control.control_key}</div>
            <div style={{ fontSize: 18, fontWeight: 800 }}>{control.title}</div>
          </div>
          <button onClick={onClose} aria-label="Close control detail" style={{ background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 22 }}>x</button>
        </div>
        <DetailGrid control={control} />
        <DetailSection title="Description"><p style={mutedText}>{control.description || 'Unknown'}</p></DetailSection>
        <DetailSection title="Regulatory Mapping"><p style={mutedText}>{refLabel(control.regulatory_reference)}</p></DetailSection>
        <DetailSection title="Applicability"><p style={mutedText}>{APPLICABILITY_LABELS[control.applicability_status]}: {control.applicability_rationale ?? 'Unknown rationale'}</p></DetailSection>
        <DetailSection title="Evidence"><EvidenceTable rows={evidence} controls={[control]} /></DetailSection>
        <DetailSection title="Risks / Gaps"><RiskTable rows={risks} controls={[control]} /></DetailSection>
        <DetailSection title="Exceptions"><ExceptionList rows={exceptions} controls={[control]} /></DetailSection>
        <DetailSection title="Change History"><HistoryTable rows={history} /></DetailSection>
      </div>
    </div>
  )
}

function DetailGrid({ control }: { control: HipaaControl }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 16 }}>
      <MiniState title="Implementation" badge={<StatusBadge value={control.implementation_status} label={IMPLEMENTATION_LABELS[control.implementation_status]} />} />
      <MiniState title="Testing" badge={<StatusBadge value={control.testing_status} label={TESTING_LABELS[control.testing_status]} />} />
      <MiniState title="Deployment" badge={<StatusBadge value={control.deployment_status} label={DEPLOYMENT_LABELS[control.deployment_status]} />} />
      <MiniState title="Operational Verification" badge={<StatusBadge value={control.operational_verification_status} label={OPERATIONAL_LABELS[control.operational_verification_status]} />} />
      <MiniState title="Derived Status" badge={<StatusBadge value={control.overall_status} label={control.overall_status.replace(/_/g, ' ')} />} />
    </div>
  )
}

function MiniState({ title, badge }: { title: string; badge: ReactNode }) {
  return <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}><div style={{ ...fieldLabel, marginBottom: 8 }}>{title}</div>{badge}</div>
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return <div style={{ marginTop: 18 }}><SectionTitle title={title} />{children}</div>
}

function EvidenceTab({ data }: { data: LoadState }) {
  const [controlKey, setControlKey] = useState('')
  const [domain, setDomain] = useState<Domain | ''>('')
  const [type, setType] = useState<ControlEvidenceType | ''>('')
  const [environment, setEnvironment] = useState('')
  const [result, setResult] = useState<VerificationResult | ''>('')
  const rows = data.controls.flatMap(control => dataForControl(data.evidence, control).map(evidence => ({ control, evidence })))
  const domains = Array.from(new Set(data.controls.map(c => c.domain))).sort()
  const environments = Array.from(new Set(rows.map(r => r.evidence.environment).filter(Boolean) as string[])).sort()
  const filtered = rows.filter(row => (!controlKey || row.control.control_key === controlKey)
    && (!domain || row.control.domain === domain)
    && (!type || row.evidence.evidence_type === type)
    && (!environment || row.evidence.environment === environment)
    && (!result || row.evidence.verification_result === result))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <FilterCard>
        <SelectFilter label="Control" value={controlKey} onChange={setControlKey} options={data.controls.map(c => [c.control_key, c.control_key] as const)} />
        <SelectFilter label="Domain" value={domain} onChange={v => setDomain(v as Domain | '')} options={domains.map(d => [d, DOMAIN_LABELS[d]] as const)} />
        <SelectFilter label="Evidence Type" value={type} onChange={v => setType(v as ControlEvidenceType | '')} options={Array.from(new Set(rows.map(r => r.evidence.evidence_type))).sort().map(t => [t, t.replace(/_/g, ' ')] as const)} />
        <SelectFilter label="Environment" value={environment} onChange={setEnvironment} options={environments.map(e => [e, e] as const)} />
        <SelectFilter label="Verification Result" value={result} onChange={v => setResult(v as VerificationResult | '')} options={(Object.keys(VERIFICATION_RESULT_LABELS) as VerificationResult[]).map(s => [s, VERIFICATION_RESULT_LABELS[s]] as const)} />
      </FilterCard>
      <EvidenceTable rows={filtered.map(r => r.evidence)} controls={data.controls} />
    </div>
  )
}

function EvidenceTable({ rows, controls }: { rows: HipaaControlEvidence[]; controls: HipaaControl[] }) {
  return <div style={{ overflowX: 'auto' }}><DataTable rowKey={r => r.id} rows={rows} emptyLabel="No evidence records match this view." columns={[
    { key: 'control', header: 'Control', render: r => controls.find(c => c.id === r.control_id)?.control_key ?? 'Unknown' },
    { key: 'type', header: 'Evidence Type', render: r => r.evidence_type.replace(/_/g, ' ') },
    { key: 'repo', header: 'Repository / Service', render: r => <DashValue value={r.repository} /> },
    { key: 'ref', header: 'Reference', render: r => <ReferenceCell reference={r.reference} /> },
    { key: 'env', header: 'Environment', render: r => <DashValue value={r.environment} /> },
    { key: 'result', header: 'Verification Result', render: r => <StatusBadge value={r.verification_result} label={VERIFICATION_RESULT_LABELS[r.verification_result]} /> },
    { key: 'observed', header: 'Observed', render: r => r.observed_at ? formatDate(r.observed_at) : <UnknownValue /> },
    { key: 'recorded', header: 'Recorded', render: r => formatDate(r.recorded_at) },
    { key: 'by', header: 'Recorded By', render: r => <DashValue value={r.recorded_by} /> },
  ]} /></div>
}

function RiskExceptionTab({ data }: { data: LoadState }) {
  const risks = data.controls.flatMap(c => dataForControl(data.risks, c))
  const exceptions = data.controls.flatMap(c => dataForControl(data.exceptions, c))
  const openRisks = risks.filter(r => ['open', 'partial', 'deferred'].includes(r.state))
  const accepted = exceptions.filter(e => e.status === 'approved')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <SectionTitle title="Open Risks / Gaps" note="Engineering limitations remain risks unless accepted through an explicit exception record." />
        <RiskTable rows={openRisks} controls={data.controls} />
      </Card>
      <Card>
        <SectionTitle title="Accepted Exceptions" note="Scoped to the readiness catalog only." />
        {accepted.length === 0 ? <EmptyState icon={AlertTriangle} title="No accepted exceptions recorded" description="No accepted exceptions are recorded in the readiness catalog." /> : <ExceptionList rows={accepted} controls={data.controls} />}
      </Card>
    </div>
  )
}

function RiskTable({ rows, controls }: { rows: HipaaControlRisk[]; controls: HipaaControl[] }) {
  return <div style={{ overflowX: 'auto' }}><DataTable rowKey={r => r.id} rows={rows} emptyLabel="No risks recorded in this view." columns={[
    { key: 'control', header: 'Control', render: r => controls.find(c => c.id === r.control_id)?.control_key ?? 'Unknown' },
    { key: 'severity', header: 'Severity', render: r => <StatusBadge value={r.severity} label={r.severity === 'unknown' ? 'Unknown' : r.severity} /> },
    { key: 'state', header: 'State', render: r => <StatusBadge value={r.state} label={RISK_STATE_LABELS[r.state]} /> },
    { key: 'description', header: 'Description', render: r => r.description },
    { key: 'impact', header: 'Impact', render: r => <DashValue value={r.impact} /> },
    { key: 'mitigation', header: 'Mitigation', render: r => <DashValue value={r.mitigation} /> },
    { key: 'owner', header: 'Owner', render: r => <DashValue value={r.owner} /> },
    { key: 'opened', header: 'Opened', render: r => formatDate(r.opened_at) },
    { key: 'target', header: 'Target Date', render: r => r.target_date ? formatDateOnly(r.target_date) : <UnknownValue /> },
  ]} /></div>
}

function ExceptionList({ rows, controls }: { rows: HipaaControlException[]; controls: HipaaControl[] }) {
  return <div style={{ overflowX: 'auto' }}><DataTable rowKey={r => r.id} rows={rows} emptyLabel="No exceptions recorded in this view." columns={[
    { key: 'control', header: 'Control', render: r => controls.find(c => c.id === r.control_id)?.control_key ?? 'Unknown' },
    { key: 'scope', header: 'Scope', render: r => r.scope },
    { key: 'rationale', header: 'Rationale', render: r => r.rationale },
    { key: 'owner', header: 'Owner', render: r => <DashValue value={r.owner} /> },
    { key: 'approver', header: 'Approver', render: r => <DashValue value={r.approver} /> },
    { key: 'status', header: 'Status', render: r => <StatusBadge value={r.status} label={EXCEPTION_STATUS_LABELS[r.status]} /> },
    { key: 'review', header: 'Review / Expiration', render: r => `${r.review_date ?? 'Unknown'} / ${r.expires_at ? formatDate(r.expires_at) : 'Unknown'}` },
  ]} /></div>
}

function HistoryTab({ history, controls }: { history: HipaaReadinessHistory[]; controls: HipaaControl[] }) {
  const [entity, setEntity] = useState('')
  const [changeType, setChangeType] = useState('')
  const [actor, setActor] = useState('')
  const [date, setDate] = useState('')
  const changeTypes = Array.from(new Set(history.map(h => h.change_type))).sort()
  const actors = Array.from(new Set(history.map(h => h.actor).filter(Boolean) as string[])).sort()
  const rows = history.filter(h => (!entity || h.entity_id === entity || String(h.new_state?.control_key ?? '') === entity)
    && (!changeType || h.change_type === changeType)
    && (!actor || h.actor === actor)
    && (!date || h.changed_at.slice(0, 10) === date))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}><History size={16} color="var(--accent)" /><div style={mutedText}>Append-only readiness change history is application-enforced. It is not presented as database-level tamper-proof storage.</div></div>
      </Card>
      <FilterCard>
        <SelectFilter label="Control / Entity" value={entity} onChange={setEntity} options={controls.map(c => [c.control_key, c.control_key] as const)} />
        <SelectFilter label="Change Type" value={changeType} onChange={setChangeType} options={changeTypes.map(c => [c, c] as const)} />
        <SelectFilter label="Actor" value={actor} onChange={setActor} options={actors.map(a => [a, a] as const)} />
        <div><label style={fieldLabel} htmlFor="history-date">Date</label><input id="history-date" aria-label="Filter history by date" type="date" value={date} onChange={e => setDate(e.target.value)} style={selectStyle} /></div>
      </FilterCard>
      <HistoryTable rows={rows} />
    </div>
  )
}

function HistoryTable({ rows }: { rows: HipaaReadinessHistory[] }) {
  return <div style={{ overflowX: 'auto' }}><DataTable rowKey={r => r.id} rows={rows} emptyLabel="No readiness history records match this view." columns={[
    { key: 'ts', header: 'Timestamp', render: r => formatDate(r.changed_at) },
    { key: 'entity', header: 'Entity', render: r => `${r.entity_type}:${r.entity_id}` },
    { key: 'change', header: 'Change', render: r => r.change_type },
    { key: 'actor', header: 'Actor', render: r => <DashValue value={r.actor} /> },
    { key: 'reason', header: 'Reason / Source', render: r => <span>{r.reason ?? 'Unknown'}{r.source ? ` (${r.source})` : ''}</span> },
  ]} /></div>
}

function ReportsTab({ data }: { data: LoadState }) {
  const risks = Object.values(data.risks).flat()
  const exceptions = Object.values(data.exceptions).flat()
  const unknownControls = data.controls.filter(c => c.deployment_status === 'unknown' || c.operational_verification_status === 'unknown')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Card>
        <SectionTitle title="HIPAA Readiness Report" note="Control Evidence Report for the initial bounded catalog." />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
          <MiniMetric label="Catalog Scope" value="Initial bounded catalog" />
          <MiniMetric label="Generated" value={formatDate(new Date().toISOString())} />
          <MiniMetric label="Controls" value={data.controls.length} />
          <MiniMetric label="Evidence Records" value={sumRecord(data.evidence)} />
          <MiniMetric label="Open Risks" value={openRiskCount(risks)} />
          <MiniMetric label="Accepted Exceptions" value={acceptedExceptionCount(exceptions)} />
        </div>
      </Card>
      <Card>
        <SectionTitle title="Known Unknowns" note="Controls with unknown deployment or operational verification remain visibly unresolved." />
        <DataTable rowKey={c => c.control_key} rows={unknownControls} emptyLabel="No unknown deployment or operational verification states in the readiness catalog." columns={[
          { key: 'control', header: 'Control', render: c => c.control_key },
          { key: 'title', header: 'Title', render: c => c.title },
          { key: 'deployment', header: 'Deployment', render: c => <StatusBadge value={c.deployment_status} label={DEPLOYMENT_LABELS[c.deployment_status]} /> },
          { key: 'operational', header: 'Operational Verification', render: c => <StatusBadge value={c.operational_verification_status} label={OPERATIONAL_LABELS[c.operational_verification_status]} /> },
        ]} />
      </Card>
    </div>
  )
}

function MiniMetric({ label, value }: { label: string; value: string | number }) {
  return <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}><div style={fieldLabel}>{label}</div><div style={{ fontSize: 16, fontWeight: 700 }}>{value}</div></div>
}

function RiskLine({ risk, control }: { risk: HipaaControlRisk; control?: HipaaControl }) {
  return <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}><div style={{ fontSize: 12, fontWeight: 700 }}>{control?.control_key ?? 'Unknown control'} · {RISK_STATE_LABELS[risk.state]}</div><div style={{ ...mutedText, marginTop: 4 }}>{risk.description}</div></div>
}

function HistoryLine({ history }: { history: HipaaReadinessHistory }) {
  return <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: 8 }}><div style={{ fontSize: 12, fontWeight: 700 }}>{history.change_type} · {history.entity_type}:{history.entity_id}</div><div style={mutedText}>{formatDate(history.changed_at)} · {history.actor ?? 'Unknown actor'}</div></div>
}

function FilterCard({ children }: { children: ReactNode }) {
  return <Card><div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 12 }}>{children}</div></Card>
}

function SearchBox({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <div><label style={fieldLabel} htmlFor="control-search">{label}</label><div style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Search size={14} color="var(--muted)" /><input id="control-search" aria-label={label} value={value} onChange={e => onChange(e.target.value)} style={{ ...selectStyle, minWidth: 220 }} /></div></div>
}

function SelectFilter({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: readonly (readonly [string, string])[] }) {
  const id = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return (
    <div>
      <label style={fieldLabel} htmlFor={id}>{label}</label>
      <select id={id} aria-label={label} value={value} onChange={e => onChange(e.target.value)} style={selectStyle}>
        <option value="">All</option>
        {options.map(([optionValue, optionLabel]) => <option key={optionValue} value={optionValue}>{optionLabel}</option>)}
      </select>
    </div>
  )
}
