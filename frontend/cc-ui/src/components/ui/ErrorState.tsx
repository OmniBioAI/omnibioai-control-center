import { AlertTriangle } from 'lucide-react'
import EmptyState from './EmptyState'

interface Props {
  message?: string
  onRetry?: () => void
}

/** Admin Console Phase 2 design system: generic in-page error state,
 * with an optional retry action. */
export default function ErrorState({ message = 'Something went wrong.', onRetry }: Props) {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Error"
      description={message}
      action={onRetry && (
        <button
          onClick={onRetry}
          style={{
            fontSize: 12, fontWeight: 600, padding: '6px 14px',
            border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
            background: 'var(--bg2)', color: 'var(--text2)',
          }}
        >
          Retry
        </button>
      )}
    />
  )
}
