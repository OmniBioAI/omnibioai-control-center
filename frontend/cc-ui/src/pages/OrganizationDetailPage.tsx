import { useEffect, useState } from 'react'
import {
  fetchMyOrg,
  fetchPlatformOrgDetail,
  setOrganizationStatus,
  type MyOrg,
  type PlatformOrgDetail,
} from '../organizations'
import { hasPlatformAdminAccess } from '../auth'
import OrganizationStatusBadge from '../components/organizations/OrganizationStatusBadge'
import OrganizationSummaryCard from '../components/organizations/OrganizationSummaryCard'

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '18px 20px', boxShadow: 'var(--shadow-card)',
}
const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}
const value: React.CSSProperties = { fontSize: 13, color: 'var(--text)' }
const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16,
}
const cardsGrid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginTop: 20,
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={label}>{title}</div>
      <div style={value}>{children}</div>
    </div>
  )
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div role="alert" style={{
      padding: '12px 16px', borderRadius: 8, background: 'var(--red-bg)',
      border: '1px solid var(--red)', color: 'var(--red)', fontSize: 13,
    }}>
      {msg}
    </div>
  )
}

interface Props {
  orgId: number
  onBack: () => void
}

/* ── Suspend/reactivate: platform-admin only, backend-enforced. This
   button simply calls the existing PATCH; the 403 a non-platform-admin
   caller gets back is what actually stops them, not this component
   hiding the button (which it also does, for UX, but never as the real
   guard). ──────────────────────────────────────────────────────────── */
function StatusAction({ org, onChanged }: { org: PlatformOrgDetail; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [confirming, setConfirming] = useState(false)

  const targetStatus = org.status === 'active' ? 'suspended' : 'active'
  const isDestructive = targetStatus === 'suspended'

  const apply = async () => {
    setBusy(true)
    setErr(null)
    try {
      await setOrganizationStatus(org.id, targetStatus, reason.trim() || undefined)
      setConfirming(false)
      setReason('')
      onChanged()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!confirming) {
    return (
      <div>
        {err && <div style={{ marginBottom: 8 }}><ErrBox msg={err} /></div>}
        <button
          onClick={() => setConfirming(true)}
          style={{
            fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 8,
            border: `1px solid ${isDestructive ? 'var(--red)' : 'var(--green-border)'}`,
            background: 'transparent', color: isDestructive ? 'var(--red)' : 'var(--color-success)',
            cursor: 'pointer',
          }}
        >
          {isDestructive ? 'Suspend Organization' : 'Reactivate Organization'}
        </button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 420 }}>
      {err && <ErrBox msg={err} />}
      <div style={{ fontSize: 12, color: 'var(--text2)' }}>
        {isDestructive
          ? 'This blocks nothing else in the platform today (no code path currently checks organization status for enforcement) -- it is a visible flag only, reversible at any time.'
          : 'This clears the suspended flag and restores normal status.'}
      </div>
      <input
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="Reason (optional, recorded for this change)"
        aria-label="Reason for status change"
        style={{
          fontSize: 12, padding: '7px 10px', borderRadius: 6,
          border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
        }}
      />
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={apply}
          disabled={busy}
          style={{
            fontSize: 12, fontWeight: 700, padding: '7px 14px', borderRadius: 8, border: 'none',
            background: isDestructive ? 'var(--red)' : 'var(--accent)',
            color: isDestructive ? '#fff' : '#000', cursor: busy ? 'not-allowed' : 'pointer',
          }}
        >
          {busy ? 'Applying…' : `Confirm ${isDestructive ? 'suspend' : 'reactivate'}`}
        </button>
        <button
          onClick={() => { setConfirming(false); setErr(null) }}
          disabled={busy}
          style={{
            fontSize: 12, fontWeight: 600, padding: '7px 14px', borderRadius: 8,
            border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer',
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

/* ── Platform-admin view: GET /platform/orgs/{id} -- full detail. ────── */
function PlatformDetailView({ orgId, onBack }: Props) {
  const [org, setOrg] = useState<PlatformOrgDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    fetchPlatformOrgDetail(orgId)
      .then(d => { setOrg(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [orgId])

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>Loading organization…</div>
  if (err || !org) {
    // Covers both "doesn't exist" (404) and, defensively, any
    // authorization rejection the backend might return -- this page
    // never assumes access just because the URL contains an org_id.
    return (
      <div>
        <BackLink onBack={onBack} />
        <ErrBox msg={err ?? 'Organization not found'} />
      </div>
    )
  }

  return (
    <div>
      <BackLink onBack={onBack} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>{org.name}</h2>
        <OrganizationStatusBadge status={org.status} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>{org.slug}</div>

      <div style={card}>
        <div style={{ ...label, marginBottom: 12 }}>General Information</div>
        <div style={grid}>
          <Field title="Organization ID">{org.id}</Field>
          <Field title="Slug">{org.slug}</Field>
          <Field title="Plan">{org.plan}</Field>
          <Field title="Owner">{org.owner_email ?? '—'}</Field>
          <Field title="Created">{new Date(org.created_at).toLocaleString()}</Field>
        </div>
        {org.status_changed_at && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--muted)' }}>
            Status last changed {new Date(org.status_changed_at).toLocaleString()}
            {org.status_changed_by_email && ` by ${org.status_changed_by_email}`}
            {org.status_changed_reason && ` — "${org.status_changed_reason}"`}
          </div>
        )}
        <div style={{ marginTop: 16 }}>
          <StatusAction org={org} onChanged={load} />
        </div>
      </div>

      <div style={cardsGrid}>
        <OrganizationSummaryCard title="Members" summary={org.member_summary} />
        <OrganizationSummaryCard title="Teams" summary={org.team_summary} />
        <OrganizationSummaryCard title="API Keys" summary={org.api_key_summary} />
        <OrganizationSummaryCard title="OAuth Clients" summary={org.oauth_client_summary} />
        <OrganizationSummaryCard title="Licenses" summary={org.license_summary} />
      </div>

      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ ...label, marginBottom: 12 }}>SSO Configuration</div>
        {org.sso.configured ? (
          <div style={grid}>
            <Field title="Provider">{org.sso.provider_type ?? '—'}</Field>
            <Field title="Issuer">{org.sso.issuer ?? '—'}</Field>
            <Field title="Status">{org.sso.status ?? '—'}</Field>
            <Field title="Enforced">{org.sso.enforced ? 'Yes' : 'No'}</Field>
            <Field title="Break-glass override">{org.sso.override_active ? 'Active' : 'None'}</Field>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>No SSO configured for this organization.</div>
        )}
      </div>

      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ ...label, marginBottom: 12 }}>Recent Activity</div>
        <div style={grid}>
          <Field title="Organization created">{new Date(org.recent_activity.org_created_at ?? org.created_at).toLocaleString()}</Field>
          <Field title="Most recent member joined">
            {org.recent_activity.most_recent_member_joined_at
              ? new Date(org.recent_activity.most_recent_member_joined_at).toLocaleString() : '—'}
          </Field>
          <Field title="Most recent API key">
            {org.recent_activity.most_recent_api_key_created_at
              ? new Date(org.recent_activity.most_recent_api_key_created_at).toLocaleString() : '—'}
          </Field>
          <Field title="Most recent OAuth client">
            {org.recent_activity.most_recent_oauth_client_created_at
              ? new Date(org.recent_activity.most_recent_oauth_client_created_at).toLocaleString() : '—'}
          </Field>
        </div>
        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}>
          Best-effort, derived from existing timestamps -- not a full activity/audit feed
          (that pipeline doesn't exist yet).
        </div>
      </div>
    </div>
  )
}

/* ── Org-admin view: GET /orgs/{id} -- OrganizationOut's existing shape
   only (id/slug/name/plan/status[+status tracking]). No owner, no
   summaries, no SSO, no recent activity: that data simply isn't in this
   response, and per this PR's own scope this page must not invent a new
   API call to fill the gap in (no members/teams/SSO/API-key/license
   pages exist yet, and building the data-fetching for their summaries
   here would be exactly that). ──────────────────────────────────────── */
function MyOrgDetailView({ orgId, onBack }: Props) {
  const [org, setOrg] = useState<MyOrg | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchMyOrg(orgId)
      .then(d => { setOrg(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [orgId])

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>Loading organization…</div>
  if (err || !org) {
    // A non-member manually changing the URL to another org's id lands
    // here -- get_org_membership_or_platform_admin's own 404 is what
    // actually stops them; this is just how that rejection renders.
    return (
      <div>
        <BackLink onBack={onBack} />
        <ErrBox msg={err ?? 'Organization not found'} />
      </div>
    )
  }

  return (
    <div>
      <BackLink onBack={onBack} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>{org.name}</h2>
        <OrganizationStatusBadge status={org.status} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>{org.slug}</div>

      <div style={card}>
        <div style={{ ...label, marginBottom: 12 }}>General Information</div>
        <div style={grid}>
          <Field title="Organization ID">{org.id}</Field>
          <Field title="Slug">{org.slug}</Field>
          <Field title="Plan">{org.plan}</Field>
        </div>
        {org.status_changed_at && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--muted)' }}>
            Status last changed {new Date(org.status_changed_at).toLocaleString()}
            {org.status_changed_reason && ` — "${org.status_changed_reason}"`}
          </div>
        )}
      </div>

      <div style={{ marginTop: 16, fontSize: 12, color: 'var(--muted)' }}>
        Member/team/API-client/license/SSO summaries and platform-admin actions are not available
        in this view -- see this PR's implementation report for why.
      </div>
    </div>
  )
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <button
      onClick={onBack}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 16,
        fontSize: 12, fontWeight: 600, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer',
      }}
    >
      ← Back to Organizations
    </button>
  )
}

export default function OrganizationDetailPage({ orgId, onBack }: Props) {
  const [isPlatformAdmin] = useState(() => hasPlatformAdminAccess())
  return isPlatformAdmin
    ? <PlatformDetailView orgId={orgId} onBack={onBack} />
    : <MyOrgDetailView orgId={orgId} onBack={onBack} />
}
