// Phase 3 PR3A: extracted from organizations/OrganizationStatusBadge.tsx
// (Phase 3 PR2) since the "active"/"suspended" vocabulary this badge
// renders is identical for both organizations and users -- one shared
// component instead of a second near-duplicate. OrganizationStatusBadge
// itself becomes a thin re-export below so PR2's existing imports in
// OrganizationTable.tsx/OrganizationDetailPage.tsx keep working
// unchanged; nothing about this move touches those files.
//
// Matches DockerPage.tsx's ContainerBadge visual language (same sizing/
// radius/uppercase convention) for consistency with the rest of Control
// Center, without importing from that page (its badge isn't exported).
interface Props {
  status: string
}

const KNOWN: Record<string, { bg: string; color: string }> = {
  active: { bg: 'var(--green-bg)', color: 'var(--color-success)' },
  suspended: { bg: 'var(--red-bg)', color: 'var(--red)' },
  // PR-C (Control Center Sessions Integration): 'revoked' is the same
  // "blocked/terminated" semantic 'suspended' already renders (same
  // red), just a different word for a session instead of an
  // organization/user -- not a new visual language. 'expired' is a
  // passive, non-actioned outcome (nobody blocked it, it just aged
  // out), rendered amber like every other "needs attention but not a
  // hard failure" state elsewhere in this app (WorkflowsPage.tsx's
  // banner, SubscriptionPage.tsx's own 'suspended' variant).
  revoked: { bg: 'var(--red-bg)', color: 'var(--red)' },
  expired: { bg: 'var(--amber-bg)', color: 'var(--amber)' },
  // PR-B6 (Integrations status): 'configured' is the same "present and
  // working" semantic 'active' already renders (same green), just a
  // different word for an env-var-derived integration than an
  // organization/user/session. 'not_configured' is a neutral, non-
  // actioned absence, not an error -- the same fallback color unknown
  // statuses already get, made explicit here so it self-documents
  // rather than relying on the KNOWN-miss fallback below.
  configured: { bg: 'var(--green-bg)', color: 'var(--color-success)' },
  not_configured: { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' },
  complete: { bg: 'rgba(0,148,255,0.12)', color: 'var(--blue)' },
  pass: { bg: 'var(--green-bg)', color: 'var(--color-success)' },
  certified: { bg: 'var(--green-bg)', color: 'var(--color-success)' },
  in_progress: { bg: 'rgba(0,148,255,0.12)', color: 'var(--blue)' },
  partial: { bg: 'var(--amber-bg)', color: 'var(--amber)' },
  paused: { bg: 'var(--amber-bg)', color: 'var(--amber)' },
  blocked: { bg: 'var(--red-bg)', color: 'var(--red)' },
  not_implemented: { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' },
  not_certified: { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' },
  failed: { bg: 'var(--red-bg)', color: 'var(--red)' },
  unknown: { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' },
  not_run: { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' },
  stale: { bg: 'var(--amber-bg)', color: 'var(--amber)' },
  fixed: { bg: 'var(--green-bg)', color: 'var(--color-success)' },
  live_validated: { bg: 'var(--green-bg)', color: 'var(--color-success)' },
  tested: { bg: 'rgba(0,148,255,0.12)', color: 'var(--blue)' },
  not_live_validated: { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' },
}

export default function StatusBadge({ status }: Props) {
  const cfg = KNOWN[status.toLowerCase()] ?? { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' }
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        padding: '3px 9px',
        borderRadius: 99,
        background: cfg.bg,
        color: cfg.color,
        whiteSpace: 'nowrap',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {status}
    </span>
  )
}
