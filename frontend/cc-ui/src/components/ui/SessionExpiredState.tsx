import { ShieldAlert } from 'lucide-react'
import EmptyState from './EmptyState'

// PR E2 (Admin Console Enterprise UX Hardening): the shared "session
// issue" state -- a 401 (the caller's own token is missing/expired/
// invalid) is a different fact from a 403 (a valid token lacking the
// right permission) and must not render the same "Permission denied"
// copy, which would misattribute the failure to the user's grants
// rather than their session. Originally introduced in BillingPage.tsx,
// moved here so every page's classify()-equivalent can render the same
// state without importing UI from an unrelated feature page.
export default function SessionExpiredState() {
  return (
    <EmptyState
      icon={ShieldAlert}
      title="Session expired"
      description="Your session couldn't be verified. Try refreshing the page."
    />
  )
}
