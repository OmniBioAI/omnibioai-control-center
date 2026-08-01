// Phase 3 PR3B. A neutral pill for a single role name -- deliberately not
// reusing StatusBadge's active/suspended color semantics (green/red mean
// something specific there); roles get their own neutral, theme-aware
// treatment since there's no inherent "good/bad" role.
interface Props {
  name: string
}

export default function RoleBadge({ name }: Props) {
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 700,
        padding: '3px 9px',
        borderRadius: 99,
        background: 'rgba(255,255,255,0.06)',
        border: '1px solid var(--border)',
        color: 'var(--text2)',
        whiteSpace: 'nowrap',
      }}
    >
      {name}
    </span>
  )
}
