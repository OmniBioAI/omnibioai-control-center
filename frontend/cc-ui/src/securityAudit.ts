import { authHeaders, reportUnauthorized } from './auth'

export type SourceAvailability = 'AVAILABLE' | 'UNAVAILABLE' | 'PARTIAL' | 'UNKNOWN'
export type IntegrityStatus = 'valid' | 'invalid' | 'unsigned' | 'unknown'
export interface SafeAuditEvent {
  event_id: string; timestamp: string; organization_id: string | null; tenant_scope: string
  actor: string | null; event_type: string; action: string; decision: string | null
  integrity: IntegrityStatus
  metadata: { trace_id?: string; request_id?: string; workflow_id?: string; run_id?: string; resource_type?: string; resource_id?: string; backend?: string }
}
export interface SafeAuditResponse {
  source: string; items: SafeAuditEvent[]; total: number; page: number; page_size: number; total_pages: number
  source_availability: SourceAvailability; generated_at: string; source_checked_at: string
  freshness: { status: string; ingestion_lag_seconds?: number | null }
  retention: { status: string; retention_days?: number | null }
  warnings: string[]
}
export interface SafeAuditFilters {
  page?: number; pageSize?: number; service?: string; eventType?: string; userId?: string
  decision?: string; integrityStatus?: IntegrityStatus; organizationId?: string
  fromTimestamp?: string; toTimestamp?: string
}

export async function fetchSafeAuditEvents(filters: SafeAuditFilters = {}): Promise<SafeAuditResponse> {
  const qs = new URLSearchParams({ page: String(filters.page ?? 1), page_size: String(filters.pageSize ?? 20) })
  const values: Record<string, string | undefined> = {
    service: filters.service, event_type: filters.eventType, user_id: filters.userId,
    decision: filters.decision, integrity_status: filters.integrityStatus, organization_id: filters.organizationId,
    from_timestamp: filters.fromTimestamp, to_timestamp: filters.toTimestamp,
  }
  Object.entries(values).forEach(([key, value]) => { if (value) qs.set(key, value) })
  const response = await fetch(`/audit/events/safe?${qs}`, { headers: { ...authHeaders() } })
  if (response.status === 401) reportUnauthorized()
  if (!response.ok) throw new Error(`security-audit ${response.status}`)
  return response.json()
}

export function formatSafeEventType(value: string): string {
  return value.split('_').map(word => word ? word[0].toUpperCase() + word.slice(1) : word).join(' ')
}
