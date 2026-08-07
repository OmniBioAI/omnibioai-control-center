// PR E2 (Admin Console Enterprise UX Hardening): extracted from
// BillingPage.tsx's own already-exported BackLink (the one call site
// that already had a configurable `label` prop) -- five other pages
// (OrganizationDetailPage, UserDetailPage, OrganizationMFAPolicyPage,
// SSOSettingsPage, ServiceAccountsPage) each independently reimplemented
// the identical button, three of them with a hardcoded generic "← Back"
// instead of a destination-specific label. Same markup/styles as every
// prior copy; only the three generic ones changed copy (to match the
// same "← Back to Organizations" convention OrganizationDetailPage
// already established for the identical "return to the org picker"
// interaction) -- a real but small, low-risk, unambiguously-better
// label, not new behavior.
interface Props {
  label: string
  onBack: () => void
}

export default function BackLink({ label, onBack }: Props) {
  return (
    <button
      onClick={onBack}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 16,
        fontSize: 12, fontWeight: 600, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer',
      }}
    >
      ← {label}
    </button>
  )
}
