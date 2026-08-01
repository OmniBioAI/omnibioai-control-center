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
}

export default function StatusBadge({ status }: Props) {
  const cfg = KNOWN[status] ?? { bg: 'rgba(255,255,255,0.08)', color: 'var(--muted)' }
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
