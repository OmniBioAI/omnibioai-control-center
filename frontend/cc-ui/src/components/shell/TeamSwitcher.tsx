import { useEffect, useState } from 'react'
import { Check, ChevronDown, Users } from 'lucide-react'
import type { SessionUser } from '../../auth'
import { switchTeam } from '../../auth'
import { listTeams, type Team } from '../../teams'

/**
 * Mode B Phase 2: Workspace Switcher. Same interactive-dropdown shape
 * ProfileMenu.tsx already established (useState(open), fixed-inset
 * click-outside backdrop, absolute-positioned panel) combined with
 * OrgSelector.tsx's icon+label+chevron button styling -- the first real
 * (non-placeholder) switcher in this top bar; OrgSelector next to it is
 * still an explicit, deliberate placeholder (its own docstring: "no
 * organization-switching functionality is implemented").
 *
 * Team membership source: listTeams(orgId) (teams.ts, unchanged, the
 * same call TeamsCard already uses) filtered to teams whose
 * member_user_ids includes the caller's own userId -- there is no
 * "teams I belong to" endpoint of its own; this is the existing
 * authenticated team data, not a new team source. Requires user.orgId --
 * renders nothing without one (a platform admin with no primary org has
 * no single org's teams to resolve against; same "nothing true to show"
 * posture OrgSelector already documents for its own no-org case).
 *
 * Switching itself is entirely auth.ts's switchTeam(): POST
 * /auth/switch-team via the existing authenticated fetch path, persist
 * the reissued access token, rehydrate cachedUser from it. This
 * component never computes, stores, or trusts a team_id itself beyond
 * the one round-trip through the server's own response.
 *
 * On success: a full page reload. Deliberate, not a shortcut -- the
 * server-issued token is already persisted before the reload happens,
 * so nothing is lost; the reload is what "Navigate/refresh only as
 * necessary to guarantee that all team-scoped views use the new JWT"
 * (this task's own §2.10) cashes out to as an actual guarantee, without
 * this component needing to know which other pages/data are team-scoped
 * today or become so later -- the same reasoning production apps with
 * an equivalent workspace switch (e.g. a full reload on switching
 * GitHub orgs) already rely on, not a novel choice for this codebase.
 */
export default function TeamSwitcher({ user }: { user: SessionUser | null }) {
  const [open, setOpen] = useState(false)
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [switching, setSwitching] = useState(false)
  const [switchError, setSwitchError] = useState<string | null>(null)

  const orgId = user?.orgId != null ? Number(user.orgId) : null
  const userId = user?.userId != null ? Number(user.userId) : null

  useEffect(() => {
    if (orgId == null) {
      setTeams(null)
      return
    }
    let cancelled = false
    listTeams(orgId)
      .then(list => { if (!cancelled) setTeams(list) })
      .catch(() => { if (!cancelled) setLoadError('Teams unavailable') })
    return () => { cancelled = true }
  }, [orgId])

  if (!user || orgId == null) return null

  const myTeams = (teams ?? []).filter(t => userId != null && t.member_user_ids.includes(userId))
  const activeTeam = user.teamId != null ? myTeams.find(t => t.id === Number(user.teamId)) : undefined
  const label = user.teamId == null ? 'Personal Workspace' : (activeTeam?.name ?? `Team ${user.teamId}`)

  const handleSwitch = async (teamId: number | null) => {
    if (switching) return // race protection: no concurrent switch attempts
    if (teamId === (user.teamId != null ? Number(user.teamId) : null)) {
      setOpen(false)
      return // already active -- nothing to do
    }
    setSwitching(true)
    setSwitchError(null)
    try {
      await switchTeam(teamId)
      // Server confirmed and cachedUser is already rebuilt -- the reload
      // just makes every mounted page/query re-run against the new JWT.
      // Dropdown is left open/disabled rather than closed here -- the
      // page is about to unload regardless, and closing first would
      // just flash an interactive-looking menu for a moment with
      // nothing behind it to click.
      window.location.reload()
    } catch (e) {
      // Left open (not closed) so the error message below is visible --
      // closing on failure would hide the one piece of feedback the
      // caller needs to know the switch didn't happen.
      setSwitchError(e instanceof Error ? e.message : 'Unable to switch teams.')
      setSwitching(false)
    }
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        disabled={switching}
        aria-label="Switch workspace"
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: 12, fontWeight: 600, color: 'var(--text2)',
          border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          padding: '5px 10px', background: 'var(--bg2)',
          cursor: switching ? 'not-allowed' : 'pointer', opacity: switching ? 0.6 : 1,
        }}
      >
        <Users size={13} color="var(--muted)" />
        <span style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {switching ? 'Switching…' : label}
        </span>
        <ChevronDown size={12} color="var(--muted)" />
      </button>

      {open && (
        <>
          <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 149 }} />
          <div
            role="menu"
            style={{
              position: 'absolute', top: 34, right: 0, zIndex: 150,
              minWidth: 220, background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-card)', overflow: 'hidden',
            }}
          >
            <div style={{ padding: '8px 12px', fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', borderBottom: '1px solid var(--border)' }}>
              Switch workspace
            </div>

            {loadError && (
              <div role="alert" style={{ padding: '10px 12px', fontSize: 12, color: 'var(--red)' }}>{loadError}</div>
            )}

            <SwitcherItem
              label="Personal Workspace"
              active={user.teamId == null}
              disabled={switching}
              onClick={() => void handleSwitch(null)}
            />

            {myTeams.length === 0 && !loadError && teams != null && (
              <div style={{ padding: '10px 12px', fontSize: 12, color: 'var(--muted)' }}>No team memberships yet.</div>
            )}

            {[...myTeams].sort((a, b) => a.name.localeCompare(b.name)).map(t => (
              <SwitcherItem
                key={t.id}
                label={t.name}
                active={user.teamId != null && Number(user.teamId) === t.id}
                disabled={switching}
                onClick={() => void handleSwitch(t.id)}
              />
            ))}

            {switchError && (
              <div role="alert" style={{ padding: '10px 12px', fontSize: 12, color: 'var(--red)', borderTop: '1px solid var(--border)' }}>
                {switchError}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function SwitcherItem({ label, active, disabled, onClick }: { label: string; active: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button
      role="menuitemradio"
      aria-checked={active}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, width: '100%',
        padding: '9px 12px', fontSize: 12, fontWeight: active ? 700 : 500,
        color: active ? 'var(--text)' : 'var(--text2)', textAlign: 'left',
        background: active ? 'var(--bg2)' : 'transparent',
        cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.6 : 1,
      }}
    >
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      {active && <Check size={13} color="var(--accent)" />}
    </button>
  )
}
