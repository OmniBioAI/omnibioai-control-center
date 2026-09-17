import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HipaaCompliancePage from './HipaaCompliancePage'
import * as hipaaCompliance from '../../hipaaCompliance'
import type {
  HipaaControl, HipaaControlEvidence, HipaaControlException, HipaaControlListResponse,
  HipaaControlRisk, HipaaLegacyMapping, HipaaReadinessHistory,
} from '../../hipaaCompliance'

vi.mock('../../hipaaCompliance', async () => {
  const actual = await vi.importActual<typeof import('../../hipaaCompliance')>('../../hipaaCompliance')
  return {
    ...actual,
    fetchHipaaReadinessControls: vi.fn(),
    fetchHipaaControlEvidence: vi.fn(),
    fetchHipaaControlRisks: vi.fn(),
    fetchHipaaControlExceptions: vi.fn(),
    fetchHipaaReadinessHistory: vi.fn(),
    fetchHipaaLegacyMappings: vi.fn(),
  }
})

const now = '2026-09-17T12:00:00Z'

function control(overrides: Partial<HipaaControl>): HipaaControl {
  return {
    id: 1,
    control_key: 'AUDIT-INTEGRITY-VERIFY',
    title: 'Audit integrity verification',
    description: 'Audit records can be verified against stored integrity metadata.',
    domain: 'audit_integrity',
    regulatory_reference: [{ framework: 'HIPAA Security Rule', citation: '45 CFR 164.312(b)', label: 'Audit controls' }],
    applicability_status: 'applicable',
    applicability_rationale: 'Technical audit control in the bounded readiness catalog.',
    owner: null,
    implementation_status: 'implemented',
    testing_status: 'tested',
    deployment_status: 'deployed',
    operational_verification_status: 'verified',
    overall_status: 'evidence_ready',
    evidence_count: 2,
    open_risk_count: 0,
    active_exception_count: 0,
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

const CONTROLS: HipaaControl[] = [
  control({ id: 1 }),
  control({
    id: 2,
    control_key: 'REDIS-RAG-ROLE-SEPARATION',
    title: 'RAG Redis role separation',
    description: 'RAG Redis access roles are separated in source and tests while production closure remains tracked.',
    domain: 'secrets_management',
    regulatory_reference: [{ framework: 'HIPAA Security Rule', citation: '45 CFR 164.312(a)(1)', label: 'Access control' }],
    implementation_status: 'partial',
    testing_status: 'tested',
    deployment_status: 'unknown',
    operational_verification_status: 'unknown',
    overall_status: 'partial',
    evidence_count: 1,
    open_risk_count: 1,
  }),
  control({
    id: 3,
    control_key: 'LOGGING-REDACTION-PHI',
    title: 'PHI logging redaction',
    description: 'Application logs avoid rendering PHI-bearing values in readiness evidence.',
    domain: 'logging_redaction',
    regulatory_reference: [],
    implementation_status: 'implemented',
    testing_status: 'partial',
    deployment_status: 'unknown',
    operational_verification_status: 'unknown',
    overall_status: 'partial',
    evidence_count: 0,
    open_risk_count: 0,
  }),
]

const EVIDENCE: Record<string, HipaaControlEvidence[]> = {
  'AUDIT-INTEGRITY-VERIFY': [
    {
      id: 11,
      control_id: 1,
      evidence_type: 'test_suite',
      reference: 'backend/tests/test_audit_integrity.py::test_verify_chain',
      repository: 'omnibioai-control-center',
      commit_ref: 'abc1234',
      environment: 'ci',
      verification_result: 'pass',
      notes: 'Synthetic fixture only.',
      observed_at: '2026-09-16T10:00:00Z',
      recorded_at: now,
      recorded_by: 'global-admin',
    },
    {
      id: 12,
      control_id: 1,
      evidence_type: 'operational_verification',
      reference: 'https://example.internal/evidence/audit-integrity',
      repository: 'control-center',
      commit_ref: null,
      environment: 'production-check',
      verification_result: 'pass',
      notes: null,
      observed_at: '2026-09-16T11:00:00Z',
      recorded_at: now,
      recorded_by: 'global-admin',
    },
  ],
  'REDIS-RAG-ROLE-SEPARATION': [
    {
      id: 21,
      control_id: 2,
      evidence_type: 'test_suite',
      reference: 'backend/tests/test_rag_redis_roles.py::test_role_boundaries',
      repository: 'omnibioai-control-center',
      commit_ref: 'def5678',
      environment: 'ci',
      verification_result: 'partial',
      notes: null,
      observed_at: null,
      recorded_at: now,
      recorded_by: 'global-admin',
    },
  ],
  'LOGGING-REDACTION-PHI': [],
}

const RISKS: Record<string, HipaaControlRisk[]> = {
  'AUDIT-INTEGRITY-VERIFY': [],
  'REDIS-RAG-ROLE-SEPARATION': [
    {
      id: 31,
      control_id: 2,
      state: 'open',
      severity: 'medium',
      description: 'Production closure evidence for RAG Redis role separation remains pending.',
      impact: 'Deployment state cannot be represented as verified.',
      mitigation: 'Record production verification evidence after closure.',
      owner: null,
      opened_at: now,
      target_date: null,
      closed_at: null,
      evidence: [{ source: 'risk-fixture' }],
    },
  ],
  'LOGGING-REDACTION-PHI': [],
}

const EXCEPTIONS: Record<string, HipaaControlException[]> = {
  'AUDIT-INTEGRITY-VERIFY': [],
  'REDIS-RAG-ROLE-SEPARATION': [],
  'LOGGING-REDACTION-PHI': [],
}

const HISTORY: HipaaReadinessHistory[] = [
  {
    id: 41,
    entity_type: 'control',
    entity_id: 'REDIS-RAG-ROLE-SEPARATION',
    change_type: 'catalog_seeded',
    old_state: null,
    new_state: { control_key: 'REDIS-RAG-ROLE-SEPARATION', deployment_status: 'unknown' },
    actor: 'catalog-seed',
    changed_at: now,
    reason: 'phase-c-evidence-backed-catalog',
    source: 'catalog_seed',
    legacy: false,
  },
]

const LEGACY: HipaaLegacyMapping[] = []

function listResponse(items: HipaaControl[]): HipaaControlListResponse {
  return { items, total: items.length, page: 1, page_size: 100, total_pages: 1 }
}

function mockHappyPath(controls = CONTROLS) {
  vi.mocked(hipaaCompliance.fetchHipaaReadinessControls).mockResolvedValue(listResponse(controls))
  vi.mocked(hipaaCompliance.fetchHipaaControlEvidence).mockImplementation(async key => EVIDENCE[key] ?? [])
  vi.mocked(hipaaCompliance.fetchHipaaControlRisks).mockImplementation(async key => RISKS[key] ?? [])
  vi.mocked(hipaaCompliance.fetchHipaaControlExceptions).mockImplementation(async key => EXCEPTIONS[key] ?? [])
  vi.mocked(hipaaCompliance.fetchHipaaReadinessHistory).mockResolvedValue(HISTORY)
  vi.mocked(hipaaCompliance.fetchHipaaLegacyMappings).mockResolvedValue(LEGACY)
}

describe('HipaaCompliancePage Phase D readiness UI', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mockHappyPath()
  })

  it('renders the approved title, subtitle, and primary tabs', async () => {
    render(<HipaaCompliancePage />)

    expect(await screen.findByRole('heading', { name: 'HIPAA Readiness' })).toBeInTheDocument()
    expect(screen.getByText('HIPAA-aligned security controls, implementation status, verification evidence, and identified gaps.')).toBeInTheDocument()
    for (const tab of ['Overview', 'Controls', 'Change History', 'Evidence', 'Risk & Exceptions', 'Reports']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
    }
  })

  it('shows live catalog counts without a score or percentage', async () => {
    render(<HipaaCompliancePage />)

    await screen.findByText('Tracked Controls')
    expect(screen.getByText('Evidence Records')).toBeInTheDocument()
    expect(screen.getByText('Accepted Exceptions')).toBeInTheDocument()
    expect(screen.getByText('Operationally Verified')).toBeInTheDocument()
    expect(screen.getByText(/Counts are scoped to the initial bounded catalog/)).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/%|score|certification/i)
  })

  it('keeps lifecycle dimensions independent and preserves Unknown as distinct from zero and failure', async () => {
    render(<HipaaCompliancePage />)

    expect(await screen.findByText('Implementation')).toBeInTheDocument()
    expect(screen.getByText('Deployment')).toBeInTheDocument()
    expect(screen.getByText('Operational Verification')).toBeInTheDocument()
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0)
  })

  it('groups domains represented by backend controls and renders backend risks', async () => {
    render(<HipaaCompliancePage />)

    expect(await screen.findByText('Audit Integrity')).toBeInTheDocument()
    expect(screen.getByText('Secrets Management')).toBeInTheDocument()
    expect(screen.getByText('Logging / Redaction')).toBeInTheDocument()
    expect(screen.getByText('Production closure evidence for RAG Redis role separation remains pending.')).toBeInTheDocument()
  })

  it('filters controls and opens a detail view with separated lifecycle sections', async () => {
    const user = userEvent.setup()
    render(<HipaaCompliancePage />)
    await user.click(await screen.findByRole('tab', { name: 'Controls' }))

    await user.type(screen.getByLabelText('Search controls'), 'redis')
    expect(screen.getByText('REDIS-RAG-ROLE-SEPARATION')).toBeInTheDocument()
    expect(screen.queryByText('AUDIT-INTEGRITY-VERIFY')).not.toBeInTheDocument()

    await user.click(screen.getByText('REDIS-RAG-ROLE-SEPARATION'))
    const dialog = await screen.findByRole('dialog', { name: /Control detail REDIS-RAG-ROLE-SEPARATION/ })
    for (const section of ['Description', 'Regulatory Mapping', 'Applicability', 'Implementation', 'Testing', 'Deployment', 'Operational Verification', 'Evidence', 'Risks / Gaps', 'Exceptions', 'Change History']) {
      expect(within(dialog).getAllByText(section).length).toBeGreaterThan(0)
    }
    expect(within(dialog).getAllByText('Unknown').length).toBeGreaterThan(0)
  })

  it('filters evidence by type and keeps safe references as links only when appropriate', async () => {
    const user = userEvent.setup()
    render(<HipaaCompliancePage />)
    await user.click(await screen.findByRole('tab', { name: 'Evidence' }))

    expect(screen.getByText('https://example.internal/evidence/audit-integrity')).toHaveAttribute('href', 'https://example.internal/evidence/audit-integrity')
    await user.selectOptions(screen.getByLabelText('Evidence Type'), 'test_suite')
    expect(screen.getByText('backend/tests/test_rag_redis_roles.py::test_role_boundaries')).toBeInTheDocument()
    expect(screen.queryByText('https://example.internal/evidence/audit-integrity')).not.toBeInTheDocument()
  })

  it('separates open risks from scoped accepted-exception empty state', async () => {
    const user = userEvent.setup()
    render(<HipaaCompliancePage />)
    await user.click(await screen.findByRole('tab', { name: 'Risk & Exceptions' }))

    expect(screen.getByText('Open Risks / Gaps')).toBeInTheDocument()
    expect(screen.getByText('Production closure evidence for RAG Redis role separation remains pending.')).toBeInTheDocument()
    expect(screen.getByText('No accepted exceptions recorded')).toBeInTheDocument()
    expect(screen.getByText('No accepted exceptions are recorded in the readiness catalog.')).toBeInTheDocument()
  })

  it('renders append-only readiness history and filters it by actor', async () => {
    const user = userEvent.setup()
    render(<HipaaCompliancePage />)
    await user.click(await screen.findByRole('tab', { name: 'Change History' }))

    expect(screen.getByText(/Append-only readiness change history is application-enforced/)).toBeInTheDocument()
    expect(screen.getAllByText('catalog_seeded').length).toBeGreaterThan(0)
    await user.selectOptions(screen.getByLabelText('Actor'), 'catalog-seed')
    expect(screen.getByText('control:REDIS-RAG-ROLE-SEPARATION')).toBeInTheDocument()
  })

  it('renders a truthful reports tab with catalog scope and known unknowns', async () => {
    const user = userEvent.setup()
    render(<HipaaCompliancePage />)
    await user.click(await screen.findByRole('tab', { name: 'Reports' }))

    expect(screen.getByText('HIPAA Readiness Report')).toBeInTheDocument()
    expect(screen.getByText('Control Evidence Report for the initial bounded catalog.')).toBeInTheDocument()
    expect(screen.getByText('Initial bounded catalog')).toBeInTheDocument()
    expect(screen.getByText('Known Unknowns')).toBeInTheDocument()
    expect(screen.getByText('REDIS-RAG-ROLE-SEPARATION')).toBeInTheDocument()
  })

  it('shows permission and session states from backend authorization failures', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaReadinessControls).mockRejectedValueOnce(new Error('/hipaa-compliance/controls 403'))
    const { unmount } = render(<HipaaCompliancePage />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()

    unmount()
    vi.resetAllMocks()
    mockHappyPath()
    vi.mocked(hipaaCompliance.fetchHipaaReadinessControls).mockRejectedValueOnce(new Error('/hipaa-compliance/controls 401'))
    render(<HipaaCompliancePage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
  })

  it('shows unavailable API state without rendering fallback zeros', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaReadinessControls).mockRejectedValueOnce(new Error('/hipaa-compliance/controls 503'))
    render(<HipaaCompliancePage />)

    expect(await screen.findByText(/HIPAA readiness data unavailable/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Tracked Controls')).not.toBeInTheDocument())
  })
})
