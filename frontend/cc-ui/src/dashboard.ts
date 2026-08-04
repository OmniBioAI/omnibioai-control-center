// PR10: Live Platform Dashboard data layer, mirroring organizations.ts/
// users.ts's own shape -- one module, one backend call
// (GET /dashboard/summary), typed to match routes_dashboard.py's
// response exactly. Every field is `number | string | null`: `null`
// means "no live source for this yet" (see routes_dashboard.py's own
// docstring for which fields that applies to and why), never a
// fabricated value -- DashboardPage renders null as a placeholder via
// MetricCard's own `placeholder` handling, the same convention Phase 2's
// StatCard already established.
import { authHeaders, reportUnauthorized } from './auth'

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

export interface IdentitySummary {
  organizations: number | null
  users: number | null
  teams: number | null
  roles: number | null
  active_sessions: number | null
}

export interface AiPlatformSummary {
  registered_models: number | null
  active_models: number | null
  embedding_models: number | null
  llm_providers: number | null
}

export interface KnowledgeSummary {
  rag_collections: number | null
  indexed_documents: number | null
  indexed_publications: number | null
  knowledge_bases: number | null
}

export interface WorkflowSummary {
  workflow_bundles: number | null
  running_jobs: number | null
  queued_jobs: number | null
  failed_jobs: number | null
}

export interface InfrastructureSummary {
  containers_running: number | null
  containers_stopped: number | null
  services_healthy: number | null
  services_total: number | null
  gpu_utilization_pct: number | null
  storage_used_bytes: number | null
  storage_total_bytes: number | null
  cpu_pct: number | null
  memory_pct: number | null
}

export interface OperationsSummary {
  health: 'UP' | 'WARN' | 'DOWN' | null
  alerts: number | null
  active_services: number | null
  uptime: string | null
}

export interface BusinessSummary {
  organizations: string | null
  subscription: string | null
  billing: string | null
  credits: string | null
}

export interface DashboardSummary {
  generated_at: string
  identity: IdentitySummary
  ai_platform: AiPlatformSummary
  knowledge: KnowledgeSummary
  workflow: WorkflowSummary
  infrastructure: InfrastructureSummary
  operations: OperationsSummary
  business: BusinessSummary
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const r = await apiFetch('/dashboard/summary')
  if (!r.ok) throw new Error(`/dashboard/summary ${r.status}`)
  return r.json()
}
