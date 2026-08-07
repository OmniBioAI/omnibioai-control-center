// PR E2 (Admin Console Enterprise UX Hardening): shared formatting/error-
// classification helpers, extracted from what was previously ~17
// independent, near-identical copies scattered across pages (audited
// directly, not estimated -- see docs/pr-e2-enterprise-ux-hardening.md).
// Every function here reproduces an existing call site's exact prior
// behavior verbatim -- this file changes where the logic lives, not
// what it does, so no page's rendered output changes as a result of
// switching to it.

// The plain "date + time" formatter every operational/audit-flavored
// page (ToolExecutionPage, WorkflowsPage, AIModelsPage, RAGPage,
// AuditLogsPage, ServiceAccountsPage, OrganizationMFAPolicyPage,
// SSOSettingsPage, SecurityDashboardPage, ...) already used, byte-for-
// byte identical across all of them before this file existed.
export function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

// Billing's own variant -- date only, no time-of-day, since billing
// periods/renewal dates are meaningfully date-grained, not timestamped
// to the minute. Deliberately kept as a separate function from
// formatDate above rather than unified with it -- these are two
// genuinely different, both-correct formatting needs, not drift to
// resolve.
export function formatDateOnly(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

// UsersPage.tsx's/UserDetailPage.tsx's own variant -- explicit
// year/month/day/hour/minute Intl options, and "Not available" (not
// "—") as its null fallback, matching users.ts's own established
// "Not available", never fabricated" convention for this domain. Kept
// as its own function, not merged into formatDate above, for the same
// reason as formatDateOnly.
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return 'Not available'
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

// The three-way (and, on pages with no classify() at all, effectively
// zero-way) split every page in this app makes between "backend denied
// this" and "something else went wrong" was independently reimplemented
// per page, with real drift: some pages fold a 401 into the same
// "Permission denied" copy as a 403 (misleading -- a 401 means the
// caller's own session is the problem, not their permissions); most
// pages that classify at all fold 401 into the generic error bucket
// (not misleading, but not informative either); four pages classify
// nothing and show the raw "<path> <status>" string verbatim. This
// helper is the one place that decision now lives -- callers still own
// their own rendering (what copy/icon to show for each outcome), this
// only decides which of the four buckets a given failure belongs in.
export type AuthErrorKind = 'session' | 'denied' | 'not-found' | 'error'

export function classifyAuthError(message: string): AuthErrorKind {
  if (message.endsWith(' 401')) return 'session'
  if (message.endsWith(' 403')) return 'denied'
  if (message.endsWith(' 404')) return 'not-found'
  return 'error'
}
