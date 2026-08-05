// PR11.2 (Phase 4): a compact "at a glance" security summary for
// OrganizationDetailPage -- deliberately separate from the existing, more
// detailed "SSO Configuration" card further down PlatformDetailView. MFA
// and domain verification are NOT implemented anywhere in this platform
// (confirmed directly against omnibioai-auth, not assumed -- see the PR11
// Identity Findings discovery doc) -- this card says so explicitly rather
// than omitting them or implying they exist, per this PR's own
// instruction not to imply functionality that isn't there.
interface Props {
  /** true/false = live org.sso.configured (platform-admin view only);
   * null = not available in this view (MyOrg carries no SSO field at
   * all -- OrganizationOut simply doesn't return it). */
  ssoConfigured: boolean | null
}

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '18px 20px', boxShadow: 'var(--shadow-card)',
  marginTop: 16,
}
const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12,
}
const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16,
}
const fieldLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}
const fieldValue: React.CSSProperties = { fontSize: 13, color: 'var(--text)' }

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={fieldLabel}>{title}</div>
      <div style={fieldValue}>{children}</div>
    </div>
  )
}

export default function SecuritySummaryCard({ ssoConfigured }: Props) {
  return (
    <div style={card}>
      <div style={label}>Security</div>
      <div style={grid}>
        <Field title="SSO">
          {ssoConfigured == null ? 'Not available in this view' : ssoConfigured ? 'Configured' : 'Not configured'}
        </Field>
        <Field title="MFA">Not configured</Field>
        <Field title="Domain">Pending verification</Field>
      </div>
      <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--muted)' }}>
        MFA enforcement and domain verification are not implemented in this platform yet -- these
        are explicit placeholders, not live status.
      </div>
    </div>
  )
}
