// Phase 3 PR3C: Teams data layer, mirroring roles.ts/organizations.ts's own
// shape exactly. Every call hits control-center's own backend at a
// relative path (routes_team_proxy.py proxies to omnibioai-auth's
// existing, unmodified /orgs/{org_id}/teams* endpoints -- no backend
// change was made for this PR). No function here makes an authorization
// decision -- that's entirely omnibioai-auth's job
// (require_org_permission_or_platform_admin(MANAGE_TEAMS) for mutations,
// bare org membership for listing).
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

// Mirrors omnibioai-auth's TeamOut exactly -- member_user_ids only, no
// email/name (that resolution happens client-side against the org's
// member roster, see TeamRow.tsx; TeamOut is not being extended for this
// PR -- see the implementation report's "Deviations" section).
export interface Team {
  id: number
  organization_id: number
  name: string
  member_user_ids: number[]
}

export async function listTeams(orgId: number): Promise<Team[]> {
  const r = await apiFetch(`/orgs/${orgId}/teams`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/teams ${r.status}`)
  return r.json()
}

export async function createTeam(orgId: number, payload: { name: string }): Promise<Team> {
  const r = await apiFetch(`/orgs/${orgId}/teams`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`/orgs/${orgId}/teams ${r.status}`)
  return r.json()
}

export async function updateTeamMembers(orgId: number, teamId: number, userIds: number[]): Promise<Team> {
  const r = await apiFetch(`/orgs/${orgId}/teams/${teamId}/members`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_ids: userIds }),
  })
  if (!r.ok) throw new Error(`/orgs/${orgId}/teams/${teamId}/members ${r.status}`)
  return r.json()
}

export async function deleteTeam(orgId: number, teamId: number): Promise<void> {
  const r = await apiFetch(`/orgs/${orgId}/teams/${teamId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/orgs/${orgId}/teams/${teamId} ${r.status}`)
}
