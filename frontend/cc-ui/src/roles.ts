// Phase 3 PR3B: Roles & Permissions data layer, mirroring organizations.ts/
// users.ts's own shape exactly. Every call hits control-center's own
// backend at a relative path (routes_role_proxy.py proxies both the
// /platform/* and /orgs/* surfaces to omnibioai-auth); no function here
// makes an authorization decision -- that's entirely omnibioai-auth's job
// (require_permission(MANAGE_ALL_ORGS) for the platform-scoped functions,
// require_org_permission_or_platform_admin(MANAGE_ORG) for the org-scoped
// ones, both Phase 3 PR0.4).
import { authHeaders, reportUnauthorized } from './auth'
import type { PermissionDescriptor } from './serviceAccounts'

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

export interface RoleSummary {
  id: number
  name: string
  description: string | null
  permissions: string[]
  // PR13: null/absent = platform-wide role, otherwise the id of the org
  // that owns this custom role (invisible to every other org). Optional
  // (not just nullable) so every pre-PR13 test fixture/call site
  // constructing a RoleSummary literal without this field still type-checks.
  organization_id?: number | null
}

export interface RoleWriteRequest {
  name?: string
  permissions: string[]
  description?: string | null
}

// ── Platform-admin: global role catalog + a user's global roles ───────────

export async function fetchPlatformRoles(): Promise<RoleSummary[]> {
  const r = await apiFetch('/platform/roles')
  if (!r.ok) throw new Error(`/platform/roles ${r.status}`)
  return r.json()
}

export interface UserRoleAssignment {
  user_id: number
  role: string
  // Always null today -- user_roles carries no per-row assignment
  // metadata (see omnibioai-auth's 0010_role_description migration
  // docstring). Present in the shape for forward compatibility only.
  assigned_at: string | null
  assigned_by: string | null
}

export async function fetchUserRoles(userId: number): Promise<UserRoleAssignment[]> {
  const r = await apiFetch(`/platform/users/${userId}/roles`)
  if (!r.ok) throw new Error(`/platform/users/${userId}/roles ${r.status}`)
  return r.json()
}

export async function assignUserRole(userId: number, role: string): Promise<UserRoleAssignment[]> {
  const r = await apiFetch(`/platform/users/${userId}/roles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!r.ok) throw new Error(`/platform/users/${userId}/roles ${r.status}`)
  return r.json()
}

export async function removeUserRole(userId: number, roleId: number): Promise<void> {
  const r = await apiFetch(`/platform/users/${userId}/roles/${roleId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/platform/users/${userId}/roles/${roleId} ${r.status}`)
}

// ── Platform-admin: role catalog CRUD (PR13) ────────────────────────────
// Always operates at organization_id=null -- creating/editing/deleting a
// custom org role uses the organization-scoped functions below instead.

export async function createPlatformRole(body: RoleWriteRequest): Promise<RoleSummary> {
  const r = await apiFetch('/platform/roles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`/platform/roles ${r.status}`)
  return r.json()
}

export async function updatePlatformRole(roleId: number, body: RoleWriteRequest): Promise<RoleSummary> {
  const r = await apiFetch(`/platform/roles/${roleId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`/platform/roles/${roleId} ${r.status}`)
  return r.json()
}

export async function deletePlatformRole(roleId: number): Promise<void> {
  const r = await apiFetch(`/platform/roles/${roleId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/platform/roles/${roleId} ${r.status}`)
}

// ── Org-scoped: role catalog (same global catalog, org-authorized) + one
// member's org roles ───────────────────────────────────────────────────────

export async function fetchOrgRoles(orgId: number): Promise<RoleSummary[]> {
  const r = await apiFetch(`/orgs/${orgId}/roles`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/roles ${r.status}`)
  return r.json()
}

export interface OrganizationRoleAssignment {
  organization_id: number
  user_id: number
  roles: string[]
}

export async function fetchOrgMemberRoles(orgId: number, userId: number): Promise<OrganizationRoleAssignment> {
  const r = await apiFetch(`/orgs/${orgId}/members/${userId}/roles`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/members/${userId}/roles ${r.status}`)
  return r.json()
}

export async function assignOrgMemberRole(
  orgId: number,
  userId: number,
  role: string,
): Promise<OrganizationRoleAssignment> {
  const r = await apiFetch(`/orgs/${orgId}/members/${userId}/roles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!r.ok) throw new Error(`/orgs/${orgId}/members/${userId}/roles ${r.status}`)
  return r.json()
}

export async function removeOrgMemberRole(orgId: number, userId: number, roleId: number): Promise<void> {
  const r = await apiFetch(`/orgs/${orgId}/members/${userId}/roles/${roleId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/orgs/${orgId}/members/${userId}/roles/${roleId} ${r.status}`)
}

// ── Org-scoped: role catalog visible to this org + CRUD on this org's own
// custom roles (PR13) ──────────────────────────────────────────────────
// Proxies omnibioai-auth's newer /organizations/{id}/... surface
// (routes_organization_roles.py), not the legacy /orgs/{id}/roles above --
// that one still works for read (org_admin/org_member etc, unchanged) but
// has no catalog-CRUD counterpart. Every role returned here is either
// platform-wide (organization_id: null) or owned by this exact org
// (organization_id === orgId); a role owned by a different org never
// appears.

export async function fetchOrganizationRoles(orgId: number): Promise<RoleSummary[]> {
  const r = await apiFetch(`/organizations/${orgId}/roles`)
  if (!r.ok) throw new Error(`/organizations/${orgId}/roles ${r.status}`)
  return r.json()
}

export async function fetchOrganizationPermissions(orgId: number): Promise<PermissionDescriptor[]> {
  const r = await apiFetch(`/organizations/${orgId}/permissions`)
  if (!r.ok) throw new Error(`/organizations/${orgId}/permissions ${r.status}`)
  return r.json()
}

export async function createOrganizationRole(orgId: number, body: RoleWriteRequest): Promise<RoleSummary> {
  const r = await apiFetch(`/organizations/${orgId}/roles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`/organizations/${orgId}/roles ${r.status}`)
  return r.json()
}

export async function updateOrganizationRole(orgId: number, roleId: number, body: RoleWriteRequest): Promise<RoleSummary> {
  const r = await apiFetch(`/organizations/${orgId}/roles/${roleId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`/organizations/${orgId}/roles/${roleId} ${r.status}`)
  return r.json()
}

export async function deleteOrganizationRole(orgId: number, roleId: number): Promise<void> {
  const r = await apiFetch(`/organizations/${orgId}/roles/${roleId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/organizations/${orgId}/roles/${roleId} ${r.status}`)
}
