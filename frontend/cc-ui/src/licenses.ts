import { authHeaders, reportUnauthorized } from './auth'
import { fetchPlatformUserDetail, fetchPlatformUsers } from './users'

async function request(path: string, init: RequestInit = {}) {
  const response = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (response.status === 401) reportUnauthorized()
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.detail
    const message = typeof detail === 'object' ? detail.message : detail
    const error = new Error(message || body.error || `${path} ${response.status}`) as Error & { code?: string }
    error.code = typeof detail === 'object' ? detail.code : undefined
    throw error
  }
  return response.json()
}

export type LicensePersona = 'developer' | 'application_user'

export interface LicensePolicy {
  validity_days: number[]
  personas: LicensePersona[]
  issuance_enabled: boolean
  unknown_identity_action: 'provisioning_required'
}

export interface LicenseMetadata {
  id: number
  key_prefix: string
  masked_key: string
  recipient_name: string | null
  email: string
  user_id: number | null
  organization_id: number | null
  persona: LicensePersona | null
  iam_role: string | null
  plan: string
  platform: string
  created_at: string
  expires_at: string | null
  renewed_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  revoked_reason: string | null
  status: 'active' | 'expired' | 'revoked'
}

export interface IssueLicenseRequest {
  full_name: string
  email: string
  persona: LicensePersona
  validity_days: number
  organization_id: number
  confirm_role_change: boolean
  confirm_replace_existing: boolean
}

export interface IssueLicenseResponse {
  license: LicenseMetadata
  key: string | null
  one_time_display: boolean
  idempotent_replay: boolean
}

export interface LicenseIdentity {
  user_id: number
  email: string
  organization_id: number
}

type LicenseIdentityErrorCode =
  | 'identity_missing'
  | 'identity_inactive'
  | 'identity_membership_required'

function identityError(code: LicenseIdentityErrorCode, message: string) {
  return Object.assign(new Error(message), { code })
}

/**
 * Resolve an already-registered, active user with an active membership in
 * the selected organization. The platform-user endpoints enforce their own
 * authorization; this client-side check is only a UX guard, while issuance
 * repeats the same eligibility checks server-side.
 */
export async function lookupLicenseIdentity(email: string, organizationId: number): Promise<LicenseIdentity> {
  const normalizedEmail = email.trim().toLowerCase()
  const users = await fetchPlatformUsers({
    page: 1,
    pageSize: 100,
    search: normalizedEmail,
    sortBy: 'email',
    sortOrder: 'asc',
  })
  const user = users.items.find(item => item.email.trim().toLowerCase() === normalizedEmail)
  if (!user) {
    throw identityError('identity_missing', 'No account exists for this email. Complete the approved user invitation/onboarding workflow before issuing a license.')
  }
  if (user.status !== 'active') {
    throw identityError('identity_inactive', 'This account is not active and cannot receive a license.')
  }

  const detail = await fetchPlatformUserDetail(user.id)
  const membership = detail.memberships.find(item => item.organization_id === organizationId)
  if (!membership || membership.status !== 'active') {
    throw identityError('identity_membership_required', 'This account does not have an accepted, active membership in the selected organization.')
  }
  return { user_id: user.id, email: user.email, organization_id: organizationId }
}

export interface LicenseHistoryItem {
  id: number
  event_type: string
  actor_user_id: number | null
  created_at: string | null
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
}

export const fetchLicensePolicy = (): Promise<LicensePolicy> => request('/platform/licenses/policy')
export const fetchLicenses = (): Promise<{ items: LicenseMetadata[]; total: number }> => request('/platform/licenses')
export const fetchLicenseHistory = (id: number): Promise<{ items: LicenseHistoryItem[] }> => request(`/platform/licenses/${id}/history`)

export function issueLicense(body: IssueLicenseRequest, idempotencyKey: string): Promise<IssueLicenseResponse> {
  return request('/platform/licenses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(body),
  })
}

export function revokeLicense(id: number, reason: string): Promise<LicenseMetadata> {
  return request(`/platform/licenses/${id}/revoke`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }),
  })
}

export function renewLicense(id: number, validityDays: number): Promise<LicenseMetadata> {
  return request(`/platform/licenses/${id}/renew`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ validity_days: validityDays }),
  })
}
