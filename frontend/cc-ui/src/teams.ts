// Team Management v0.8.0 Step 5: Teams UI catch-up. Mirrors organizations.ts/
// serviceAccounts.ts/sso.ts's own shape -- every call hits control-center's
// own backend at a relative path (routes_team_proxy.py proxies to
// omnibioai-auth's /orgs/{org_id}/teams* endpoints, Steps 1-4, unchanged by
// this change); no function here makes an authorization decision -- that's
// entirely omnibioai-auth's job (require_org_permission_or_platform_admin
// (manage_teams) for org-level mutations -- create/rename/delete --
// app.rbac.require_team_manage_permission -- Step 4's centralized
// dependency, org manage_teams OR a live team-admin TeamMember row -- for
// the per-member mutations below, bare org membership for every read).
//
// Step 5 replaces the pre-v0.8.0 full-replacement membership model (the
// old `PUT .../members`/`updateTeamMembers`) with the per-member endpoints
// Steps 1-4 actually added: invite/role-change/remove/leave. That old
// function is intentionally removed, not kept alongside the new ones --
// nothing in this app calls the full-replace endpoint anymore (see this
// change's implementation summary); the backend endpoint itself is
// untouched and still reachable directly if ever needed again.
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

// Mutating calls prefer the backend's own detail message (e.g. "Cannot
// demote the last team admin", "Invalid role: 'x' (expected one of
// ['admin', 'member', 'viewer'])") over a bare "<path> <status>" -- those
// messages are already written to be shown directly to the caller, same
// convention serviceAccounts.ts/sso.ts already established. Read-only
// calls (listTeams, fetchTeamMembers) don't need this -- a failed list
// fetch degrades to a generic/hidden state regardless of the specific
// reason, matching those two functions' existing callers.
async function _errorMessage(r: Response, path: string): Promise<string> {
  try {
    const data = await r.json()
    if (typeof data?.detail === 'string') return data.detail
  } catch {
    // fall through to the generic message below
  }
  return `${path} ${r.status}`
}

// Mirrors omnibioai-auth's TeamOut (app/schemas/teams.py) exactly.
// member_user_ids stays -- it's what TeamRow's collapsed summary (member
// count) uses without a second request; the roster itself (role/
// invited_by/joined_at per member) only comes from fetchTeamMembers
// below, fetched on demand when a team's member panel is opened.
export interface Team {
  id: number
  organization_id: number
  name: string
  member_user_ids: number[]
  description: string | null
  created_by_user_id: number | null
}

// Mirrors omnibioai-auth's TeamMemberOut exactly -- no email/display name
// (that resolution happens client-side against the org's member roster,
// same as the old model -- see TeamMembersPanel.tsx).
export interface TeamMember {
  user_id: number
  role: string
  invited_by_user_id: number | null
  joined_at: string | null
}

// Mirrors team_service.TEAM_ROLES exactly (app/services/team_service.py).
// Not derived from the backend at request time -- there is no "list valid
// team roles" endpoint, and this three-value set has needed a migration
// on the backend every time it changed historically, so hardcoding it
// here carries the same staleness risk this app already accepts for
// ADMIN_PERMISSIONS in auth.ts.
export const TEAM_ROLES = ['admin', 'member', 'viewer'] as const
export type TeamRole = (typeof TEAM_ROLES)[number]

export async function listTeams(orgId: number): Promise<Team[]> {
  const r = await apiFetch(`/orgs/${orgId}/teams`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/teams ${r.status}`)
  return r.json()
}

export async function createTeam(orgId: number, payload: { name: string; description?: string }): Promise<Team> {
  const path = `/orgs/${orgId}/teams`
  const r = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// PATCH semantics match omnibioai-auth's TeamUpdate exactly: a field left
// out of `payload` means "leave alone", not "clear this field" -- so a
// rename-only edit never has to resend the current description back.
export async function updateTeam(
  orgId: number, teamId: number, payload: { name?: string; description?: string },
): Promise<Team> {
  const path = `/orgs/${orgId}/teams/${teamId}`
  const r = await apiFetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function deleteTeam(orgId: number, teamId: number): Promise<void> {
  const path = `/orgs/${orgId}/teams/${teamId}`
  const r = await apiFetch(path, { method: 'DELETE' })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
}

export async function fetchTeamMembers(orgId: number, teamId: number): Promise<TeamMember[]> {
  const r = await apiFetch(`/orgs/${orgId}/teams/${teamId}/members`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/teams/${teamId}/members ${r.status}`)
  return r.json()
}

// Backend requires the invitee already be an active member of this
// team's own organization (team_service.invite_to_team) -- the UI builds
// this from the org roster already loaded for email resolution rather
// than a free-text address, see TeamMembersPanel.tsx.
export async function inviteTeamMember(
  orgId: number, teamId: number, payload: { email: string; role?: string },
): Promise<TeamMember> {
  const path = `/orgs/${orgId}/teams/${teamId}/invite`
  const r = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function updateTeamMemberRole(
  orgId: number, teamId: number, userId: number, role: string,
): Promise<TeamMember> {
  const path = `/orgs/${orgId}/teams/${teamId}/members/${userId}/role`
  const r = await apiFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function removeTeamMember(orgId: number, teamId: number, userId: number): Promise<void> {
  const path = `/orgs/${orgId}/teams/${teamId}/members/${userId}`
  const r = await apiFetch(path, { method: 'DELETE' })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
}

export async function leaveTeam(orgId: number, teamId: number): Promise<void> {
  const path = `/orgs/${orgId}/teams/${teamId}/leave`
  const r = await apiFetch(path, { method: 'POST' })
  if (!r.ok) throw new Error(await _errorMessage(r, path))
}
