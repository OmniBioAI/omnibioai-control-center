import DashboardCard from './DashboardCard'
import type { IconComponent } from '../ui/icon-type'

type Tone = 'good' | 'bad' | 'neutral'

const TONE_COLOR: Record<Tone, string> = {
  good: 'var(--green)',
  bad: 'var(--red)',
  neutral: 'var(--muted)',
}

interface Props {
  label: string
  /** Short status text, e.g. "Reachable", "68% util", "Configured". */
  statusText: string | null
  tone?: Tone
  icon?: IconComponent
  placeholder?: boolean
}

/** PR10 (Live Platform Dashboard): a card for a categorical/qualitative
 * status rather than a count -- GPU reachability, an individual
 * service's state, a boolean-flavored integration status. Distinct from
 * HealthCard (the one aggregate platform-health indicator) and MetricCard
 * (a number) -- this is the shape for "one named thing, one status word"
 * cards, reusable by any future module that has that shape (e.g. IAM's
 * "SSO: Configured/Not configured" once that module ships). */
export default function StatusCard({ label, statusText, tone = 'neutral', icon, placeholder }: Props) {
  const color = TONE_COLOR[tone]
  return (
    <DashboardCard label={label} icon={icon} iconColor={color} placeholder={placeholder}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
        <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
          {statusText ?? 'Unknown'}
        </span>
      </div>
    </DashboardCard>
  )
}
