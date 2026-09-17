// Admin Console HIPAA Readiness (V1). Every call hits
// control-center's own backend at a relative path -- routes_hipaa_
// compliance.py, an in-process router this repo's own hipaa_compliance/
// package owns (not a routes_*_proxy.py relay to another service). No
// function here makes an authorization decision -- that's entirely the
// backend's job (require_permission(manage_all_orgs), the same
// permission audit.ts/organizations.ts already reuse for their own
// platform-admin-only reads).
import { authHeaders, reportUnauthorized } from './auth'

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401) {
    reportUnauthorized()
  }
  return r
}

// Mirrors backend/src/control_center/hipaa_compliance/schemas.py exactly.
export type ComplianceStatus = 'planned' | 'in_progress' | 'verified' | 'released' | 'exception'

export const COMPLIANCE_STATUSES: readonly ComplianceStatus[] = [
  'planned', 'in_progress', 'verified', 'released', 'exception',
]

export type ComplianceControlCategory =
  | 'audit_integrity' | 'audit_event_signing' | 'audit_event_verification'
  | 'access_control' | 'authentication_authorization' | 'data_integrity'
  | 'monitoring_logging' | 'other'

export const CONTROL_CATEGORIES: readonly ComplianceControlCategory[] = [
  'audit_integrity', 'audit_event_signing', 'audit_event_verification',
  'access_control', 'authentication_authorization', 'data_integrity',
  'monitoring_logging', 'other',
]

// Mirrors CONTROL_CATEGORY_LABELS (schemas.py) exactly -- display only.
export const CONTROL_CATEGORY_LABELS: Record<ComplianceControlCategory, string> = {
  audit_integrity: 'Audit Integrity',
  audit_event_signing: 'Audit Event Signing',
  audit_event_verification: 'Audit Event Verification',
  access_control: 'Access Control',
  authentication_authorization: 'Authentication / Authorization',
  data_integrity: 'Data Integrity',
  monitoring_logging: 'Monitoring / Logging',
  other: 'Other',
}

export const STATUS_LABELS: Record<ComplianceStatus, string> = {
  planned: 'Planned',
  in_progress: 'In Progress',
  verified: 'Verified',
  released: 'Released',
  exception: 'Exception',
}

export type EvidenceType = 'github_pr' | 'commit' | 'ci_run' | 'test_suite' | 'documentation' | 'other'

export const EVIDENCE_TYPES: readonly EvidenceType[] = [
  'github_pr', 'commit', 'ci_run', 'test_suite', 'documentation', 'other',
]

export interface EvidenceRef {
  type: EvidenceType
  label: string
  url?: string | null
  identifier?: string | null
}

export interface HipaaComplianceChange {
  change_id: string
  title: string
  change_date: string
  repository: string
  branch: string | null
  commit_sha: string | null
  pr_number: number | null
  description: string
  control_category: ComplianceControlCategory
  affected_component: string | null
  status: ComplianceStatus
  verification_result: string | null
  reviewer: string | null
  evidence: EvidenceRef[]
  notes: string | null
  created_at: string
  updated_at: string
}

export interface HipaaComplianceChangeListResponse {
  items: HipaaComplianceChange[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface ControlCategorySummary {
  category: ComplianceControlCategory
  label: string
  total: number
  verified: number
  pending: number
  exceptions: number
}

export interface HipaaComplianceSummary {
  overall_status: 'no_data' | 'on_track' | 'in_progress' | 'attention_needed'
  total_controls_tracked: number
  verified_count: number
  pending_count: number
  exception_count: number
  latest_change_id: string | null
  latest_change_title: string | null
  latest_change_date: string | null
  controls: ControlCategorySummary[]
}

export interface HipaaComplianceChangeFilters {
  status?: ComplianceStatus
  controlCategory?: ComplianceControlCategory
  repository?: string
  page?: number
  pageSize?: number
}

export interface HipaaComplianceChangeInput {
  change_id: string
  title: string
  change_date: string
  repository: string
  branch?: string | null
  commit_sha?: string | null
  pr_number?: number | null
  description?: string
  control_category: ComplianceControlCategory
  affected_component?: string | null
  status: ComplianceStatus
  verification_result?: string | null
  reviewer?: string | null
  evidence?: EvidenceRef[]
  notes?: string | null
}

export type HipaaComplianceChangeUpdateInput = Partial<Omit<HipaaComplianceChangeInput, 'change_id'>>

export async function fetchHipaaComplianceSummary(): Promise<HipaaComplianceSummary> {
  const r = await apiFetch('/hipaa-compliance/changes/summary')
  if (!r.ok) throw new Error(`/hipaa-compliance/changes/summary ${r.status}`)
  return r.json()
}

export async function fetchHipaaComplianceChanges(
  filters: HipaaComplianceChangeFilters = {},
): Promise<HipaaComplianceChangeListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(filters.page ?? 1))
  qs.set('page_size', String(filters.pageSize ?? 20))
  if (filters.status) qs.set('status', filters.status)
  if (filters.controlCategory) qs.set('control_category', filters.controlCategory)
  if (filters.repository) qs.set('repository', filters.repository)

  const r = await apiFetch(`/hipaa-compliance/changes?${qs.toString()}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/changes ${r.status}`)
  return r.json()
}

export async function fetchHipaaComplianceChange(changeId: string): Promise<HipaaComplianceChange> {
  const r = await apiFetch(`/hipaa-compliance/changes/${encodeURIComponent(changeId)}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/changes/${changeId} ${r.status}`)
  return r.json()
}

export async function createHipaaComplianceChange(
  input: HipaaComplianceChangeInput,
): Promise<HipaaComplianceChange> {
  const r = await apiFetch('/hipaa-compliance/changes', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (!r.ok) throw new Error(`/hipaa-compliance/changes ${r.status}`)
  return r.json()
}

export async function updateHipaaComplianceChange(
  changeId: string, input: HipaaComplianceChangeUpdateInput,
): Promise<HipaaComplianceChange> {
  const r = await apiFetch(`/hipaa-compliance/changes/${encodeURIComponent(changeId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (!r.ok) throw new Error(`/hipaa-compliance/changes/${changeId} ${r.status}`)
  return r.json()
}


export type Domain =
  | 'identity_access_management' | 'authentication' | 'authorization_tenant_isolation'
  | 'audit_logging' | 'audit_integrity' | 'data_protection' | 'encryption'
  | 'backup_recovery' | 'phi_handling' | 'logging_redaction'
  | 'external_ai_data_egress' | 'execution_isolation' | 'infrastructure_security'
  | 'network_security' | 'secrets_management' | 'incident_operational_controls' | 'other'

export type ApplicabilityStatus = 'unknown' | 'applicable' | 'not_applicable' | 'deferred'
export type ImplementationStatus = 'unknown' | 'not_started' | 'partial' | 'implemented' | 'deferred' | 'not_applicable'
export type TestingStatus = 'unknown' | 'not_tested' | 'partial' | 'tested' | 'failed' | 'not_applicable'
export type DeploymentStatus = 'unknown' | 'not_deployed' | 'partial' | 'deployed' | 'not_applicable'
export type OperationalVerificationStatus = 'unknown' | 'not_verified' | 'partial' | 'verified' | 'failed' | 'not_applicable'
export type OverallControlStatus = 'unknown' | 'not_applicable' | 'deferred' | 'needs_work' | 'partial' | 'evidence_ready'
export type ControlEvidenceType = 'git_commit' | 'github_pr' | 'ci_run' | 'test_suite' | 'documentation' | 'deployment_verification' | 'operational_verification' | 'migration' | 'audit_result' | 'other'
export type VerificationResult = 'unknown' | 'pass' | 'fail' | 'partial' | 'not_applicable'
export type RiskState = 'open' | 'partial' | 'mitigated' | 'accepted' | 'deferred' | 'closed'
export type Severity = 'unknown' | 'low' | 'medium' | 'high' | 'critical'
export type ExceptionStatus = 'open' | 'approved' | 'expired' | 'revoked' | 'closed'

export const DOMAIN_LABELS: Record<Domain, string> = {
  identity_access_management: 'Identity & Access Management',
  authentication: 'Authentication',
  authorization_tenant_isolation: 'Authorization / Tenant Isolation',
  audit_logging: 'Audit Logging',
  audit_integrity: 'Audit Integrity',
  data_protection: 'Data Protection',
  encryption: 'Encryption',
  backup_recovery: 'Backup & Recovery',
  phi_handling: 'PHI Handling',
  logging_redaction: 'Logging / Redaction',
  external_ai_data_egress: 'External AI / Data Egress',
  execution_isolation: 'Execution Isolation',
  infrastructure_security: 'Infrastructure Security',
  network_security: 'Network Security',
  secrets_management: 'Secrets Management',
  incident_operational_controls: 'Incident / Operational Controls',
  other: 'Other',
}

export const APPLICABILITY_LABELS: Record<ApplicabilityStatus, string> = {
  unknown: 'Unknown', applicable: 'Applicable', not_applicable: 'Not Applicable', deferred: 'Deferred',
}
export const IMPLEMENTATION_LABELS: Record<ImplementationStatus, string> = {
  unknown: 'Unknown', not_started: 'Not Started', partial: 'Partial', implemented: 'Implemented', deferred: 'Deferred', not_applicable: 'Not Applicable',
}
export const TESTING_LABELS: Record<TestingStatus, string> = {
  unknown: 'Unknown', not_tested: 'Not Tested', partial: 'Partial', tested: 'Tested', failed: 'Failed', not_applicable: 'Not Applicable',
}
export const DEPLOYMENT_LABELS: Record<DeploymentStatus, string> = {
  unknown: 'Unknown', not_deployed: 'Not Deployed', partial: 'Partial', deployed: 'Deployed', not_applicable: 'Not Applicable',
}
export const OPERATIONAL_LABELS: Record<OperationalVerificationStatus, string> = {
  unknown: 'Unknown', not_verified: 'Not Verified', partial: 'Partial', verified: 'Verified', failed: 'Failed', not_applicable: 'Not Applicable',
}
export const VERIFICATION_RESULT_LABELS: Record<VerificationResult, string> = {
  unknown: 'Unknown', pass: 'Pass', fail: 'Fail', partial: 'Partial', not_applicable: 'Not Applicable',
}
export const RISK_STATE_LABELS: Record<RiskState, string> = {
  open: 'Open', partial: 'Partial', mitigated: 'Mitigated', accepted: 'Accepted', deferred: 'Deferred', closed: 'Closed',
}
export const EXCEPTION_STATUS_LABELS: Record<ExceptionStatus, string> = {
  open: 'Open', approved: 'Approved', expired: 'Expired', revoked: 'Revoked', closed: 'Closed',
}

export interface RegulatoryReference {
  framework: string
  citation: string
  label?: string | null
}

export interface HipaaControl {
  id: number
  control_key: string
  title: string
  description: string
  domain: Domain
  regulatory_reference: RegulatoryReference[]
  applicability_status: ApplicabilityStatus
  applicability_rationale: string | null
  owner: string | null
  implementation_status: ImplementationStatus
  testing_status: TestingStatus
  deployment_status: DeploymentStatus
  operational_verification_status: OperationalVerificationStatus
  overall_status: OverallControlStatus
  evidence_count: number
  open_risk_count: number
  active_exception_count: number
  created_at: string
  updated_at: string
}

export interface HipaaControlListResponse {
  items: HipaaControl[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface HipaaControlEvidence {
  id: number
  control_id: number
  evidence_type: ControlEvidenceType
  reference: string
  repository: string | null
  commit_ref: string | null
  environment: string | null
  verification_result: VerificationResult
  notes: string | null
  observed_at: string | null
  recorded_at: string
  recorded_by: string | null
}

export interface HipaaControlRisk {
  id: number
  control_id: number
  state: RiskState
  severity: Severity
  description: string
  impact: string | null
  mitigation: string | null
  owner: string | null
  opened_at: string
  target_date: string | null
  closed_at: string | null
  evidence: Record<string, unknown>[]
}

export interface HipaaControlException {
  id: number
  control_id: number
  rationale: string
  scope: string
  approver: string | null
  owner: string | null
  status: ExceptionStatus
  created_at: string
  review_date: string | null
  expires_at: string | null
  supporting_evidence: Record<string, unknown>[]
}

export interface HipaaReadinessHistory {
  id: number
  entity_type: string
  entity_id: string
  change_type: string
  old_state: Record<string, unknown> | null
  new_state: Record<string, unknown>
  actor: string | null
  changed_at: string
  reason: string | null
  source: string | null
  legacy: boolean
}

export interface HipaaLegacyMapping {
  id: number
  legacy_change_id: string
  control_id: number | null
  mapping_status: string
  mapping_rationale: string | null
  created_at: string
  updated_at: string
}

export interface HipaaReadinessControlFilters {
  domain?: Domain
  applicabilityStatus?: ApplicabilityStatus
  implementationStatus?: ImplementationStatus
  testingStatus?: TestingStatus
  deploymentStatus?: DeploymentStatus
  operationalVerificationStatus?: OperationalVerificationStatus
  page?: number
  pageSize?: number
}

export async function fetchHipaaReadinessControls(
  filters: HipaaReadinessControlFilters = {},
): Promise<HipaaControlListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(filters.page ?? 1))
  qs.set('page_size', String(filters.pageSize ?? 100))
  if (filters.domain) qs.set('domain', filters.domain)
  if (filters.applicabilityStatus) qs.set('applicability_status', filters.applicabilityStatus)
  if (filters.implementationStatus) qs.set('implementation_status', filters.implementationStatus)
  if (filters.testingStatus) qs.set('testing_status', filters.testingStatus)
  if (filters.deploymentStatus) qs.set('deployment_status', filters.deploymentStatus)
  if (filters.operationalVerificationStatus) qs.set('operational_verification_status', filters.operationalVerificationStatus)
  const r = await apiFetch(`/hipaa-compliance/controls?${qs.toString()}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/controls ${r.status}`)
  return r.json()
}

export async function fetchHipaaControlEvidence(controlKey: string): Promise<HipaaControlEvidence[]> {
  const r = await apiFetch(`/hipaa-compliance/controls/${encodeURIComponent(controlKey)}/evidence`)
  if (!r.ok) throw new Error(`/hipaa-compliance/controls/${controlKey}/evidence ${r.status}`)
  return r.json()
}

export async function fetchHipaaControlRisks(controlKey: string, state?: RiskState): Promise<HipaaControlRisk[]> {
  const qs = new URLSearchParams()
  if (state) qs.set('state', state)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const r = await apiFetch(`/hipaa-compliance/controls/${encodeURIComponent(controlKey)}/risks${suffix}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/controls/${controlKey}/risks ${r.status}`)
  return r.json()
}

export async function fetchHipaaControlExceptions(controlKey: string): Promise<HipaaControlException[]> {
  const r = await apiFetch(`/hipaa-compliance/controls/${encodeURIComponent(controlKey)}/exceptions`)
  if (!r.ok) throw new Error(`/hipaa-compliance/controls/${controlKey}/exceptions ${r.status}`)
  return r.json()
}

export async function fetchHipaaReadinessHistory(filters: { entityType?: string; entityId?: string } = {}): Promise<HipaaReadinessHistory[]> {
  const qs = new URLSearchParams()
  if (filters.entityType) qs.set('entity_type', filters.entityType)
  if (filters.entityId) qs.set('entity_id', filters.entityId)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const r = await apiFetch(`/hipaa-compliance/history${suffix}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/history ${r.status}`)
  return r.json()
}

export async function fetchHipaaLegacyMappings(): Promise<HipaaLegacyMapping[]> {
  const r = await apiFetch('/hipaa-compliance/legacy-mappings')
  if (!r.ok) throw new Error(`/hipaa-compliance/legacy-mappings ${r.status}`)
  return r.json()
}
