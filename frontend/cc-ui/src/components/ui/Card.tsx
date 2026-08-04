import type { CSSProperties, ReactNode } from 'react'

interface Props {
  children: ReactNode
  style?: CSSProperties
  padding?: number | string
}

/** Admin Console Phase 2 design system: the one card chrome (border,
 * radius, surface background) every page currently hand-rolls its own
 * copy of inline. New code should use this instead of repeating the
 * pattern; existing pages are not retrofitted in this PR (see this PR's
 * report for why -- avoiding touching already-tested pages). */
export default function Card({ children, style, padding = 20 }: Props) {
  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding,
        ...style,
      }}
    >
      {children}
    </div>
  )
}
