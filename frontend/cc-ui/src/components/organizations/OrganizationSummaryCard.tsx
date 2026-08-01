import type { ResourceCountSummary } from '../../organizations'

// Reused across every summary tile on OrganizationDetailPage (Members,
// Teams, API Keys, OAuth Clients, Licenses) -- one card shape for all
// five, since PlatformOrgDetailOut already gives every one of them the
// same {total, active, invited, revoked, most_recent_at} shape.
interface Props {
  title: string
  summary: ResourceCountSummary
}

const cardStyle: React.CSSProperties = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius)',
  padding: '14px 16px',
  boxShadow: 'var(--shadow-card)',
}

export default function OrganizationSummaryCard({ title, summary }: Props) {
  const breakdown: string[] = []
  if (summary.active != null) breakdown.push(`${summary.active} active`)
  if (summary.invited != null) breakdown.push(`${summary.invited} invited`)
  if (summary.revoked != null) breakdown.push(`${summary.revoked} revoked`)

  return (
    <div style={cardStyle}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: 'var(--muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', lineHeight: 1 }}>{summary.total}</div>
      {breakdown.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text2)' }}>{breakdown.join(' · ')}</div>
      )}
      {summary.most_recent_at && (
        <div style={{ marginTop: 4, fontSize: 10, color: 'var(--muted)' }}>
          Most recent {new Date(summary.most_recent_at).toLocaleDateString()}
        </div>
      )}
    </div>
  )
}
