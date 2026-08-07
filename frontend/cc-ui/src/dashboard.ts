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

// PR C: replaces the PR10-era always-null placeholder shape
// ({organizations, subscription, billing, credits}) -- that shape never
// had a live source (routes_dashboard.py's own stale comment claimed no
// billing system existed at all), and none of those four fields mapped
// to anything real once PR B/PR14.4-14.7 built one. `organizations` is
// dropped entirely rather than carried forward -- it would have
// duplicated identity.organizations above, which already has a live
// platform-wide count; `credits` is dropped because no such concept
// exists anywhere in omnibioai-billing's schema, live or otherwise.
// Field shapes mirror routes_dashboard.py's _business_section() exactly
// -- this is the *caller's own* organization's billing (no platform-wide
// aggregate exists), same convention that function's own docstring
// documents.
export interface BusinessSummary {
  organization_id: number | null
  organization_name: string | null
  plan_name: string | null
  subscription_status: string | null
  usage_services_count: number | null
  billing_service_available: boolean | null
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
