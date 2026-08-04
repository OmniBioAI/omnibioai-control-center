import { ChevronRight } from 'lucide-react'

/** Admin Console Phase 2: breadcrumb trail, derived by the caller from
 * navigation.ts (section label + item label) -- kept dumb/presentational
 * here so it has no opinion on where the labels came from. */
export default function Breadcrumb({ trail }: { trail: string[] }) {
  if (trail.length === 0) return null
  return (
    <nav aria-label="Breadcrumb" style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      {trail.map((label, i) => (
        <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          {i > 0 && <ChevronRight size={12} color="var(--muted)" />}
          <span
            style={{
              fontSize: 13,
              fontWeight: i === trail.length - 1 ? 600 : 400,
              color: i === trail.length - 1 ? 'var(--text)' : 'var(--muted)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}
          >
            {label}
          </span>
        </span>
      ))}
    </nav>
  )
}
