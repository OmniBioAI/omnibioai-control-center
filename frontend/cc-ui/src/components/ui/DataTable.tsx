import type { ReactNode } from 'react'
import EmptyState from './EmptyState'

interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  emptyLabel?: string
}

/** Admin Console Phase 2 design system: a typed wrapper around the
 * `.data-table` CSS class (index.css) every existing page already
 * applies directly to a hand-written <table> -- new code can use this
 * instead of repeating the markup. Existing tables (OrganizationTable,
 * UsersPage, ...) are untouched; they already work and this doesn't
 * change their behavior. */
export default function DataTable<T>({ columns, rows, rowKey, emptyLabel = 'No data' }: Props<T>) {
  if (rows.length === 0) {
    return <EmptyState title={emptyLabel} />
  }
  return (
    <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          {columns.map(c => <th key={c.key}>{c.header}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map(row => (
          <tr key={rowKey(row)}>
            {columns.map(c => <td key={c.key}>{c.render(row)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
