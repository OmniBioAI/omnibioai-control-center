import type { ReactNode } from 'react'

/** Admin Console Phase 2 design system: a right-aligned row of action
 * buttons -- pass as SectionHeader's `actions` prop, or use standalone
 * above a table/list. */
export default function ActionToolbar({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {children}
    </div>
  )
}
