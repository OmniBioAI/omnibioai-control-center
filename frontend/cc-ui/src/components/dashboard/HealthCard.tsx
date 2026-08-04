import DashboardCard from './DashboardCard'

type Health = 'UP' | 'WARN' | 'DOWN' | null

const CONFIG: Record<'UP' | 'WARN' | 'DOWN', { label: string; color: string }> = {
  UP:   { label: 'Healthy',  color: 'var(--green)' },
  WARN: { label: 'Degraded', color: 'var(--amber)' },
  DOWN: { label: 'Down',     color: 'var(--red)' },
}

interface Props {
  label: string
  status: Health
  sublabel?: string
}

/** PR10 (Live Platform Dashboard): the aggregate platform-health card --
 * one big colored status word plus a pulsing dot, for Operations >
 * Health. `status: null` (no permission to see infra data, or the
 * upstream check itself failed) renders as an honest "Unknown", not a
 * silently-green default. */
export default function HealthCard({ label, status, sublabel }: Props) {
  const cfg = status ? CONFIG[status] : null
  return (
    <DashboardCard label={label}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            width: 9, height: 9, borderRadius: '50%',
            background: cfg?.color ?? 'var(--muted)',
            animation: cfg ? 'pulse-dot 2s ease-in-out infinite' : undefined,
          }}
        />
        <span style={{ fontSize: 20, fontWeight: 700, color: cfg?.color ?? 'var(--muted)' }}>
          {cfg?.label ?? 'Unknown'}
        </span>
      </div>
      {sublabel && (
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{sublabel}</span>
      )}
    </DashboardCard>
  )
}
