// PR14.5C: Billing dashboard/invoice UI data layer, mirroring sso.ts/
// serviceAccounts.ts's own shape exactly. Every call hits control-center's
// own backend at a relative path (routes_billing_proxy.py proxies the
// /billing/* surface to omnibioai-billing); no function here makes an
// authorization decision -- that's entirely omnibioai-billing's job
// (app.core.iam.get_authorized_organization_id/get_authorized_invoice,
// independent JWT verification, PR14.4F/PR14.5C).
//
// Field shapes mirror app/schemas/billing.py's PR14.5C response models
// exactly -- Decimal fields serialize as JSON numbers (FastAPI's default
// jsonable_encoder), so they're typed `number` here, same convention
// organizations.ts already uses for its own numeric fields.
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

// ── Shapes ──────────────────────────────────────────────────────────────

// PR B (Admin Console Billing/Usage consolidation): raw consumption by
// service/action/resource for a period -- distinct from
// SubscriptionUsageLimit below, which is consumption *relative to a
// plan's included allowance* (included/used/remaining/percentage_used).
// This is the plain number, no plan context. Field shapes mirror
// app/schemas/billing.py's UsageSummaryResponse/UsageDimensionSummary
// exactly, same convention every other shape in this file already
// follows.
export interface UsageDimensionSummary {
  service: string
  action: string
  resource: string
  unit: string
  quantity: number
}

export interface OrganizationUsage {
  organization_id: number
  period_start: string
  period_end: string
  services: UsageDimensionSummary[]
}

export interface CurrentPeriodSummary {
  billing_period_id: number
  period_start: string
  period_end: string
  status: string
}

export interface OrganizationBillingSummary {
  organization_id: number
  current_period: CurrentPeriodSummary | null
  current_usage_cost: number
  currency: string
  invoice_count: number
  outstanding_amount: number
}

export interface InvoiceListItem {
  id: number
  invoice_number: string | null
  billing_period_id: number
  period_start: string
  period_end: string
  status: string
  subtotal: number
  total: number
  currency: string
  created_at: string | null
}

export interface InvoiceListResult {
  organization_id: number
  total_count: number
  limit: number
  offset: number
  invoices: InvoiceListItem[]
}

export interface InvoiceLineItemDetail {
  id: number
  rated_usage_record_id: number
  service: string
  action: string
  resource: string
  unit: string
  quantity: number
  unit_price: number
  line_total: number
  description: string | null
}

export interface InvoiceDetail {
  id: number
  invoice_number: string | null
  organization_id: number
  billing_period_id: number
  period_start: string
  period_end: string
  status: string
  currency: string
  subtotal: number
  credits: number
  adjustments: number
  taxes: number
  total: number
  issued_at: string | null
  due_at: string | null
  paid_at: string | null
  created_at: string | null
  line_items: InvoiceLineItemDetail[]
}

export interface InvoiceLineItemListResult {
  invoice_id: number
  total_count: number
  limit: number
  offset: number
  line_items: InvoiceLineItemDetail[]
}

export interface CostBreakdownEntry {
  quantity: number
  cost: number
}

export interface CostBreakdownResult {
  organization_id: number
  period_start: string
  period_end: string
  group_by: string
  currency: string
  breakdown: Record<string, CostBreakdownEntry>
}

export interface InvoiceListFilters {
  status?: string
  start_date?: string
  end_date?: string
  limit?: number
  offset?: number
}

// PR14.6D: subscription summary + usage-limits shapes. Field shapes
// mirror app/schemas/subscriptions.py's SubscriptionSummaryResponse/
// SubscriptionUsageLimitsResponse exactly, same convention every other
// shape in this file already follows.

export interface SubscriptionFeature {
  feature_key: string
  value_type: string
  bool_value: boolean | null
  int_value: number | null
  string_value: string | null
}

export interface SubscriptionSummary {
  organization_id: number
  billing_plan_id: number
  plan_name: string
  billing_interval: string
  currency: string
  status: string
  start_date: string
  end_date: string | null
  renewal_date: string | null
  features: SubscriptionFeature[]
}

export interface SubscriptionUsageLimit {
  service: string
  action: string
  resource: string
  unit: string
  period: string
  included: number
  used: number
  remaining: number
  percentage_used: number
}

export interface SubscriptionUsageLimits {
  organization_id: number
  billing_plan_id: number
  plan_name: string
  as_of: string
  limits: SubscriptionUsageLimit[]
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchOrganizationUsage(orgId: number): Promise<OrganizationUsage> {
  const r = await apiFetch(`/billing/organizations/${orgId}/usage`)
  if (!r.ok) throw new Error(await _errorMessage(r, `/billing/organizations/${orgId}/usage`))
  return r.json()
}

export async function fetchOrganizationBillingSummary(orgId: number): Promise<OrganizationBillingSummary> {
  const r = await apiFetch(`/billing/organizations/${orgId}/summary`)
  if (!r.ok) throw new Error(await _errorMessage(r, `/billing/organizations/${orgId}/summary`))
  return r.json()
}

export async function fetchInvoices(orgId: number, filters: InvoiceListFilters = {}): Promise<InvoiceListResult> {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.start_date) params.set('start_date', filters.start_date)
  if (filters.end_date) params.set('end_date', filters.end_date)
  params.set('limit', String(filters.limit ?? 50))
  params.set('offset', String(filters.offset ?? 0))
  const path = `/billing/organizations/${orgId}/invoices?${params.toString()}`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchInvoiceDetail(invoiceId: number): Promise<InvoiceDetail> {
  const r = await apiFetch(`/billing/invoices/${invoiceId}`)
  if (!r.ok) throw new Error(await _errorMessage(r, `/billing/invoices/${invoiceId}`))
  return r.json()
}

export async function fetchInvoiceLineItems(invoiceId: number, limit = 50, offset = 0): Promise<InvoiceLineItemListResult> {
  const path = `/billing/invoices/${invoiceId}/line-items?limit=${limit}&offset=${offset}`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchCostBreakdown(
  orgId: number, startDate: string, endDate: string, groupBy: 'service' | 'action' | 'resource' | 'month' = 'service',
): Promise<CostBreakdownResult> {
  const path = `/billing/organizations/${orgId}/cost-breakdown?start_date=${startDate}&end_date=${endDate}&group_by=${groupBy}`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchOrganizationSubscription(orgId: number): Promise<SubscriptionSummary> {
  const path = `/billing/organizations/${orgId}/subscription`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchSubscriptionUsageLimits(orgId: number, asOf?: string): Promise<SubscriptionUsageLimits> {
  const path = asOf
    ? `/billing/organizations/${orgId}/subscription/usage-limits?as_of=${asOf}`
    : `/billing/organizations/${orgId}/subscription/usage-limits`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// Prefers the backend's own detail message over a bare "<path> <status>"
// -- same convention sso.ts's own _errorMessage established.
async function _errorMessage(r: Response, path: string): Promise<string> {
  try {
    const data = await r.json()
    if (typeof data?.detail === 'string') return data.detail
    if (typeof data?.error === 'string') return data.error
  } catch {
    // fall through to the generic message below
  }
  return `${path} ${r.status}`
}
