import { authHeaders, reportUnauthorized } from './auth'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

// Wraps fetch() with the admin Authorization header and centralizes the
// 401 handling (main.py's require_admin gate) so every call site doesn't
// have to re-implement "session expired, go back to login".
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401) {
    reportUnauthorized()
  }
  return r
}

export interface ServiceResult {
  name: string
  type: string
  target: string
  status: 'UP' | 'WARN' | 'DOWN'
  latency_ms: number | null
  message: string
  ui_url?: string | null
}

export interface DiskResult {
  name: string
  type: string
  target: string
  status: 'UP' | 'WARN' | 'DOWN'
  latency_ms: number | null
  message: string
}

export interface SummaryResponse {
  overall_status: 'UP' | 'WARN' | 'DOWN'
  generated_at: string
  services: ServiceResult[]
  system: { disk: DiskResult[] }
}

export interface ReportStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  started_at: string | null
  finished_at: string | null
  message: string
  report_exists: boolean
  report_generated_at: string | null
}

export interface Container {
  Names: string
  Image: string
  Status: string
  State?: string
  RunningFor: string
  Ports: string
  Command?: string
  CreatedAt?: string
}

export interface ContainersResponse {
  containers: Container[]
  running: number
  stopped: number
  error?: string
}

export interface SifImage {
  tool: string
  category: string
  sif_path: string | null
  exists: boolean
  size_mb: number
}

export interface SifImagesResponse {
  images: SifImage[]
  built: number
  missing: number
  total_gb: number
}

export interface PluginImage {
  plugin: string
  name: string
  category: string
  image: string
  local_status: 'present' | 'missing' | 'unknown'
  size_mb: number
}

export interface PluginImagesResponse {
  plugins: PluginImage[]
  present: number
  missing: number
}

export async function fetchSummary(): Promise<SummaryResponse> {
  const r = await apiFetch(`${BASE}/summary`)
  if (!r.ok) throw new Error(`/summary ${r.status}`)
  return r.json()
}

export interface HealthResponse {
  status: string
}

// Public Read-Only Control Center architecture: GET /health is the one
// genuinely anonymous liveness check (no permission requirement, no
// service/disk detail -- see routes_health.py). Deliberately a plain
// fetch(), not apiFetch() -- ControlApp must never attach a bearer token
// merely because one happens to be sitting in this origin's
// localStorage; this call has no Authorization header under any
// circumstances.
export async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch(`${BASE}/health`)
  if (!r.ok) throw new Error(`/health ${r.status}`)
  return r.json()
}

export type RegressionStatus =
  | 'complete' | 'in_progress' | 'implemented' | 'not_implemented' | 'pass'
  | 'certified' | 'partial' | 'paused' | 'blocked' | 'not_run'
  | 'not_certified' | 'failed' | 'unknown'

export interface RegressionPhase {
  status: RegressionStatus
  certification_status: RegressionStatus
  last_certified_at?: string | null
  evidence: Record<string, unknown>
  notes?: string | null
}

export interface RegressionCapability {
  id: string
  label: string
  implementation_status: RegressionStatus
  test_status: RegressionStatus
  live_status: RegressionStatus
  certification_status: RegressionStatus
  last_validated_at?: string | null
  evidence: Record<string, unknown>
  notes?: string | null
}

export interface RegressionFinding {
  id: string
  status: 'fixed' | 'open' | 'closed' | 'unknown'
  validation_status: 'tested' | 'live_validated' | 'not_live_validated' | 'unknown'
  summary: string
  last_validated_at?: string | null
}

export interface RegressionTechnicalDebt {
  id: string
  status: RegressionStatus
  summary: string
  notes?: string | null
}

export interface RegressionHealthResponse {
  schema_version: string
  generated_at: string
  source: { repository: string; commit: string; workflow_run_id?: string | null }
  phases: Record<'p0' | 'p1' | 'p2', RegressionPhase>
  capabilities: RegressionCapability[]
  findings: RegressionFinding[]
  technical_debt: RegressionTechnicalDebt[]
  freshness: {
    status: 'CURRENT' | 'STALE' | 'UNKNOWN'
    age_seconds?: number
    stale_after_hours: number
  }
}

export async function fetchRegressionHealth(): Promise<RegressionHealthResponse> {
  const r = await apiFetch(`${BASE}/regression-health/data`)
  if (!r.ok) throw new Error(`/regression-health/data ${r.status}`)
  return r.json()
}

export type SecurityEvidenceType =
  | 'SOURCE_IMPLEMENTATION' | 'UNIT_TEST' | 'INTEGRATION_TEST' | 'LIVE_VALIDATION'
  | 'REGRESSION_CERTIFICATION' | 'RUNTIME_HEALTH' | 'CONFIGURATION'
  | 'SECURITY_AUDIT' | 'COMPOSE_SECURITY' | 'DOCKER_PROXY_POLICY'

export type SecurityPostureState = 'VERIFIED' | 'PARTIAL' | 'ATTENTION' | 'UNKNOWN' | 'NOT_IMPLEMENTED'
export type SecurityImplementationStatus = 'IMPLEMENTED' | 'NOT_IMPLEMENTED' | 'UNKNOWN'
export type SecurityTestStatus = 'PASS' | 'FAILED' | 'PARTIAL' | 'NOT_RUN' | 'UNKNOWN'
export type SecurityLiveStatus = 'AVAILABLE' | 'UNAVAILABLE' | 'PARTIAL' | 'UNKNOWN'
export type SecurityCertificationStatus = 'CERTIFIED' | 'NOT_CERTIFIED' | 'PARTIAL' | 'UNKNOWN'
export type SecurityFreshness = 'CURRENT' | 'STALE' | 'UNKNOWN'
export type SecurityDataSourceStatus = 'AVAILABLE' | 'UNAVAILABLE' | 'UNKNOWN' | 'NOT_CONFIGURED' | 'PARTIAL'

export interface SecurityEvidenceItem {
  type: SecurityEvidenceType
  repository: string
  identifier: string
  status: string
  validated_at: string | null
  freshness: SecurityFreshness
  description: string
}

export interface SecurityFindingItem {
  finding_id: string
  title: string
  type: 'ACTIVE_ISSUE' | 'FIXED_HISTORICAL' | 'TECHNICAL_DEBT' | 'COVERAGE_GAP'
  control_ids: string[]
  severity?: string
  source: string
  validated_at: string | null
  summary: string
}

export interface SecurityTechnicalDebtItem {
  debt_id: string
  summary: string
  control_ids: string[]
}

export interface SecurityControlItem {
  control_id: string
  name: string
  category: string
  priority: 'P0' | 'P1' | 'P2'
  implementation_status: SecurityImplementationStatus
  test_status: SecurityTestStatus
  live_status: SecurityLiveStatus
  certification_status: SecurityCertificationStatus
  freshness: SecurityFreshness
  posture: SecurityPostureState
  evidence: SecurityEvidenceItem[]
  findings: SecurityFindingItem[]
  limitations: string[]
}

export interface SecurityPostureResponse {
  schema_version: string
  generated_at: string
  summary: {
    verified: number
    partial: number
    attention: number
    unknown: number
    not_implemented: number
  }
  categories: string[]
  controls: SecurityControlItem[]
  findings: SecurityFindingItem[]
  technical_debt: SecurityTechnicalDebtItem[]
  data_sources: Record<string, SecurityDataSourceStatus>
  limitations: string[]
}

export async function fetchSecurityPosture(): Promise<SecurityPostureResponse> {
  const r = await apiFetch(`${BASE}/security-posture/data`)
  if (!r.ok) throw new Error(`/security-posture/data ${r.status}`)
  return r.json()
}

// ── Deployment Health (DH-3) ────────────────────────────────────────────────
// Types below are transcribed directly from the real DH-2 response shape
// (control_center/deployment_health_runtime.py's build_deployment_health_response
// and _service_view -- not inferred from a task description). Route path
// mirrors regression-health's own SPA/API separation (REG-010): the SPA
// route is /deployment-health, the API is the distinct /deployment-health/data,
// nginx rewriting the latter to the backend's real GET /deployment-health
// (see docker/nginx/api-proxy.conf) so the two never collide.
export type DeploymentHealthState = 'healthy' | 'degraded' | 'unhealthy' | 'unknown'

export type DeploymentDependencyRelationship = 'hard' | 'soft' | 'routed_through' | 'observability_only'

export type DeploymentEvidenceSource =
  | 'compose_service' | 'compose_depends_on' | 'compose_image' | 'compose_build_context'
  | 'static_ownership_mapping' | 'docker_inspect' | 'http_probe' | 'prometheus' | 'regression_artifact'

export type DeploymentServiceCategory =
  | 'control_plane' | 'security' | 'execution' | 'scientific_data' | 'ai_model'
  | 'observability' | 'user_interface' | 'infrastructure' | 'database_storage' | 'unknown'

export type DeploymentImageComparisonStatus = 'match' | 'mismatch' | 'unknown'

export type DeploymentSourceAvailability = 'available' | 'unavailable' | 'not_configured'

export type DeploymentBaselineSource = 'development' | 'release' | 'unknown'

export interface DeploymentEvidenceItem {
  source: DeploymentEvidenceSource
  detail: string
}

export interface DeploymentImageReference {
  raw: string
  registry: string | null
  repository: string | null
  tag: string | null
  digest: string | null
  has_variable: boolean
  is_untagged: boolean
  is_latest_tag: boolean
}

export interface DeploymentMetadataCompleteness {
  repository_known: boolean
  category_known: boolean
  dependencies_known: boolean
  missing_fields: string[]
  is_complete: boolean
}

export interface DeploymentServiceDependency {
  to_service: string
  relationship: DeploymentDependencyRelationship
  target_intrinsic_health: DeploymentHealthState
}

export interface DeploymentServiceRuntime {
  present: boolean
  running: boolean | null
  docker_health: string | null
  image: string | null
  match_evidence: DeploymentEvidenceItem | null
}

// DH-5: source/commit/image drift -- an independent operational dimension
// from `health` above, never folded into it. See the backend's
// deployment_health_drift.py module docstring for the full evidence model
// and why a mutable configured tag alone can never produce `match`.
export type DeploymentDriftStatus = 'match' | 'drifted' | 'unknown' | 'not_applicable'

export type DeploymentRevisionType = 'oci_label' | 'unknown'

export interface DeploymentSourceVersion {
  repository: string | null
  expected_revision: string | null
  revision_type: DeploymentRevisionType
}

export interface DeploymentConfiguredArtifact {
  image: string | null
  tag: string | null
  digest: string | null
}

export interface DeploymentRunningArtifact {
  image_id: string | null
  revision: string | null
  source: string | null
  version: string | null
}

export interface DeploymentDriftResult {
  status: DeploymentDriftStatus
  reason: string
  evidence: DeploymentEvidenceItem[]
}

export interface DeploymentServiceDrift {
  source: DeploymentSourceVersion
  configured: DeploymentConfiguredArtifact
  running: DeploymentRunningArtifact
  drift: DeploymentDriftResult
}

export interface DeploymentDriftSummary {
  match: number
  drifted: number
  unknown: number
  not_applicable: number
}

export interface DeploymentServiceView {
  service_id: string
  display_name: string
  category: DeploymentServiceCategory
  repository: string | null
  deployment: {
    image: DeploymentImageReference | null
    build_configured: boolean
    healthcheck_configured: boolean
    ports: number[]
  }
  runtime: DeploymentServiceRuntime
  health: {
    intrinsic: DeploymentHealthState
    intrinsic_evidence: DeploymentEvidenceItem
    effective: DeploymentHealthState
    effective_evidence: DeploymentEvidenceItem[]
  }
  image_comparison: {
    status: DeploymentImageComparisonStatus
    configured: string | null
    running: string | null
  }
  drift: DeploymentServiceDrift
  dependencies: DeploymentServiceDependency[]
  evidence: DeploymentEvidenceItem[]
  completeness: DeploymentMetadataCompleteness
}

export interface DeploymentHealthSummary {
  total: number
  healthy: number
  degraded: number
  unhealthy: number
  unknown: number
}

export interface DeploymentHealthDataSources {
  compose: DeploymentSourceAvailability
  docker: DeploymentSourceAvailability
  application_probe: DeploymentSourceAvailability
  prometheus: DeploymentSourceAvailability
  regression_health: DeploymentSourceAvailability
}

export interface DeploymentRegressionPhaseSummary {
  status: string
  certification_status: string
}

export interface DeploymentHealthRegressionContext {
  availability: DeploymentSourceAvailability | null
  phases: Record<string, DeploymentRegressionPhaseSummary> | null
  freshness: { status: string; age_seconds?: number; stale_after_hours?: number } | null
}

export interface DeploymentHealthResponse {
  generated_at: string
  baseline: DeploymentBaselineSource
  summary: DeploymentHealthSummary
  drift_summary: DeploymentDriftSummary
  services: DeploymentServiceView[]
  regression_health: DeploymentHealthRegressionContext
  data_sources: DeploymentHealthDataSources
  warnings: string[]
}

export async function fetchDeploymentHealth(): Promise<DeploymentHealthResponse> {
  const r = await apiFetch(`${BASE}/deployment-health/data`)
  if (!r.ok) throw new Error(`/deployment-health/data ${r.status}`)
  return r.json()
}

export async function fetchConfig(): Promise<string> {
  const r = await apiFetch(`${BASE}/config`)
  if (!r.ok) throw new Error(`/config ${r.status}`)
  return r.text()
}

export interface ProjectRow {
  name: string; full: string; cat: string; catLabel: string
  files: number; code: number; comment: number; blank: number; pct: number
}

export interface LanguageRow {
  name: string; type: string; typeLabel: string
  files: number; code: number; comment: number; blank: number; pct: number
}

export interface CoverageRow {
  repo: string; status: string; pct: number | null
  stmts: number | null; missed: number | null; branches: number | null; failUnder: number | null
}

export interface GitStatusRow {
  repo: string; branch: string; nonMain: boolean; clean: boolean
  modified: number; untracked: number; unpushed: number; details: string
}

export interface ReportData {
  generated_at: string
  grand: { files: number; code: number; comment: number; blank: number }
  projects: ProjectRow[]
  languages: LanguageRow[]
  coverage: CoverageRow[]
  gitStatus: GitStatusRow[]
}

export async function fetchReportData(): Promise<ReportData> {
  const r = await apiFetch(`${BASE}/report/data`)
  if (!r.ok) throw new Error(`/report/data ${r.status}`)
  return r.json()
}

export async function fetchReportStatus(): Promise<ReportStatus> {
  const r = await apiFetch(`${BASE}/report/status`)
  if (!r.ok) throw new Error(`/report/status ${r.status}`)
  return r.json()
}

export async function triggerGenerate(): Promise<void> {
  const r = await apiFetch(`${BASE}/report/generate`, { method: 'POST' })
  if (!r.ok && r.status !== 409) throw new Error(`/report/generate ${r.status}`)
}

export async function addService(name: string, type: string, url: string): Promise<void> {
  const r = await apiFetch(`${BASE}/config/service`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, type, url }),
  })
  if (!r.ok) throw new Error(`/config/service ${r.status}`)
}

export async function fetchContainers(): Promise<ContainersResponse> {
  const r = await apiFetch(`${BASE}/docker/containers`)
  if (!r.ok) throw new Error(`/docker/containers ${r.status}`)
  return r.json()
}

export async function fetchSifImages(): Promise<SifImagesResponse> {
  const r = await apiFetch(`${BASE}/docker/sif-images`)
  if (!r.ok) throw new Error(`/docker/sif-images ${r.status}`)
  return r.json()
}

export async function fetchPluginImages(): Promise<PluginImagesResponse> {
  const r = await apiFetch(`${BASE}/docker/plugin-images`)
  if (!r.ok) throw new Error(`/docker/plugin-images ${r.status}`)
  return r.json()
}

// ── Admin Console: Actions (report/coverage regeneration) ─────────────────
// Moved here from the legacy scripts/sections/misc/admin.py static-HTML
// panel (see docs/admin-console-navigation-move.md). Same endpoints, same
// platform.manage_content gate server-side -- AdminApp's own AuthGate is
// what supplies the Authorization header via apiFetch()'s authHeaders(),
// so there's no separate login form here (unlike the legacy panel, which
// had no ambient session to draw on).
export interface CoverageStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  started_at: string | null
  finished_at: string | null
  message: string
  result_exists: boolean
  result_generated_at: string | null
}

export async function fetchCoverageStatus(): Promise<CoverageStatus> {
  const r = await apiFetch(`${BASE}/coverage/status`)
  if (!r.ok) throw new Error(`/coverage/status ${r.status}`)
  return r.json()
}

export async function triggerCoverageGenerate(): Promise<void> {
  const r = await apiFetch(`${BASE}/coverage/generate`, { method: 'POST' })
  if (!r.ok && r.status !== 409) throw new Error(`/coverage/generate ${r.status}`)
}

// ── Admin Console: Scheduled Jobs (cron) ───────────────────────────────────
export interface CronJob {
  id: string
  name: string
  schedule: string
  paused: boolean | null
  last_status: string | null
  last_run_at: string | null
}

export interface CronJobsResponse {
  jobs: CronJob[]
}

export async function fetchCronJobs(): Promise<CronJobsResponse> {
  const r = await apiFetch(`${BASE}/cron/jobs`)
  if (!r.ok) throw new Error(`/cron/jobs ${r.status}`)
  return r.json()
}

export async function fetchCronJobLog(id: string, lines = 100): Promise<{ lines: string[] }> {
  const r = await apiFetch(`${BASE}/cron/jobs/${encodeURIComponent(id)}/log?lines=${lines}`)
  if (!r.ok) throw new Error(`/cron/jobs/${id}/log ${r.status}`)
  return r.json()
}

export async function pauseCronJob(id: string): Promise<void> {
  const r = await apiFetch(`${BASE}/cron/jobs/${encodeURIComponent(id)}/pause`, { method: 'POST' })
  if (!r.ok) throw new Error(`/cron/jobs/${id}/pause ${r.status}`)
}

export async function resumeCronJob(id: string): Promise<void> {
  const r = await apiFetch(`${BASE}/cron/jobs/${encodeURIComponent(id)}/resume`, { method: 'POST' })
  if (!r.ok) throw new Error(`/cron/jobs/${id}/resume ${r.status}`)
}

export async function updateCronSchedule(id: string, schedule: string): Promise<void> {
  const r = await apiFetch(`${BASE}/cron/jobs/${encodeURIComponent(id)}/schedule`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schedule }),
  })
  if (!r.ok) throw new Error(`/cron/jobs/${id}/schedule ${r.status}`)
}

// ── Admin Console: Known Issues ─────────────────────────────────────────────
export interface KnownIssue {
  id: string
  title: string
  description: string | null
  severity: 'low' | 'medium' | 'high' | string
  status: 'open' | 'acknowledged' | 'resolved' | string
  area: string | null
  opened_at: string | null
}

export interface KnownIssuesResponse {
  issues: KnownIssue[]
}

export async function fetchKnownIssues(): Promise<KnownIssuesResponse> {
  const r = await apiFetch(`${BASE}/known-issues`)
  if (!r.ok) throw new Error(`/known-issues ${r.status}`)
  return r.json()
}

export interface KnownIssueInput {
  title: string
  description?: string
  severity?: string
  area?: string
}

export async function createKnownIssue(body: KnownIssueInput): Promise<KnownIssue> {
  const r = await apiFetch(`${BASE}/known-issues`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`/known-issues ${r.status}`)
  return r.json()
}

export async function updateKnownIssueStatus(id: string, status: string): Promise<KnownIssue> {
  const r = await apiFetch(`${BASE}/known-issues/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
  if (!r.ok) throw new Error(`/known-issues/${id} ${r.status}`)
  return r.json()
}

export async function deleteKnownIssue(id: string): Promise<void> {
  const r = await apiFetch(`${BASE}/known-issues/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/known-issues/${id} ${r.status}`)
}
