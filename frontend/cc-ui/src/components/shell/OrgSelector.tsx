import { Building2, ChevronDown } from 'lucide-react'
import type { SessionUser } from '../../auth'
import { hasPlatformAdminAccess } from '../../auth'

/**
 * Admin Console Phase 2: organization-context indicator. Explicitly a
 * placeholder per this phase's scope (no organization-switching
 * functionality is implemented) -- shows real, non-fabricated context
 * (the session's actual org_id, or "All Organizations" for a platform
 * admin whose token isn't scoped to one org) rather than fake selectable
 * options, and isn't clickable. Renders nothing for a session with
 * neither (nothing true to show).
 */
export default function OrgSelector({ user }: { user: SessionUser | null }) {
  if (!user) return null
  const label = user.orgId
    ? `Org ${user.orgId}`
    : hasPlatformAdminAccess()
      ? 'All Organizations'
      : null
  if (!label) return null

  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        fontSize: 12, fontWeight: 600, color: 'var(--text2)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
        padding: '5px 10px', background: 'var(--bg2)',
      }}
    >
      <Building2 size={13} color="var(--muted)" />
      <span className="shell-org-selector-label">{label}</span>
      <ChevronDown size={12} color="var(--muted)" />
    </div>
  )
}
