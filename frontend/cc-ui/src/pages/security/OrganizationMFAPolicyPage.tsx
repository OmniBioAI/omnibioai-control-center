import { useEffect, useState } from 'react'
import { ShieldAlert, ShieldOff } from 'lucide-react'
import {
  clearMFAPolicyOverride,
  createOrgMFAPolicy,
  enableMFAPolicyOverride,
  fetchOrgMFAPolicy,
  updateOrgMFAPolicy,
  type OrgMFAPolicy,
} from '../../security'
import { fetchMyOrg, fetchPlatformOrgDetail } from '../../organizations'
import { hasPermission, hasPlatformAdminAccess } from '../../auth'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState, ActionToolbar, Button, BackLink } from '../../components/ui'
import { formatDate } from '../../format'

// PR11.5.6 (Admin Console Security UI). Structurally mirrors
// SSOSettingsPage.tsx (PR11.3) deliberately closely -- same org-label
// resolution, same loading/denied/not-configured/error state machine,
// same confirm-before-enable and break-glass card shapes. See
// docs/pr11-5-6-security-ui-discovery.md.
const MANAGE_SSO = 'manage_sso'
const MANAGE_ALL_ORGS = 'manage_all_orgs'

const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16,
}
const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}
const value: React.CSSProperties = { fontSize: 13, color: 'var(--text)' }
const fieldStyle: React.CSSProperties = {
  fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
  background: 'var(--bg)', color: 'var(--text)', width: '100%', boxSizing: 'border-box',
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
      padding: '10px 14px', borderRadius: 8, background: 'var(--red-bg)',
      border: '1px solid var(--red)', color: 'var(--red)', fontSize: 12,
    }}>
      {msg}
    </div>
  )
}

/** True/false badges rendered as plain text -- same reasoning
 * SSOSettingsPage.tsx's own BoolText gives (no separate Badge component
 * exists for this in components/ui yet). */
function BoolText({ value: v, trueLabel, falseLabel }: { value: boolean; trueLabel: string; falseLabel: string }) {
  return <span style={{ color: v ? 'var(--color-success, #22c55e)' : 'var(--muted)' }}>{v ? trueLabel : falseLabel}</span>
}

// ── Current Policy ───────────────────────────────────────────────────────

function CurrentPolicyCard({ orgLabel, policy }: { orgLabel: string; policy: OrgMFAPolicy }) {
  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ ...label, marginBottom: 12 }}>Current Policy</div>
      <div style={grid}>
        <Field title="Organization">{orgLabel}</Field>
        <Field title="Status">
          <BoolText value={policy.required} trueLabel="Enabled" falseLabel="Disabled" />
        </Field>
        <Field title="Required">
          <BoolText value={policy.required} trueLabel="ON" falseLabel="OFF" />
        </Field>
        <Field title="Enabled By">{policy.enabled_by_email ?? '—'}</Field>
        <Field title="Enabled At">{formatDate(policy.enabled_at)}</Field>
        <Field title="Override Status">
          <BoolText value={policy.override_active} trueLabel="Active" falseLabel="Inactive" />
        </Field>
        <Field title="Override Reason">{policy.override_reason ?? '—'}</Field>
      </div>
      {/* Never a TOTP secret, QR secret, recovery code, or challenge
          token -- there is no such field on this resource at all, see
          security.ts's own OrgMFAPolicy shape. */}
    </Card>
  )
}

// ── Enable/Disable MFA Requirement ─────────────────────────────────────

function RequirementCard({ orgId, policy, onChanged }: { orgId: number; policy: OrgMFAPolicy; onChanged: (p: OrgMFAPolicy) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const apply = async (required: boolean) => {
    setBusy(true)
    setErr(null)
    try {
      const updated = await updateOrgMFAPolicy(orgId, required)
      setConfirming(false)
      onChanged(updated)
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionHeader title="MFA Requirement" description="Require multi-factor authentication for this organization's members." />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ fontSize: 13, color: 'var(--text2)' }}>
          Currently <strong><BoolText value={policy.required} trueLabel="required" falseLabel="not required" /></strong>
          {policy.override_active && (
            <span style={{ color: 'var(--muted)' }}> — a break-glass override is currently suspending enforcement.</span>
          )}
        </div>
        {!policy.required && !confirming && (
          <Button variant="primary" disabled={busy} onClick={() => setConfirming(true)}>
            Enable MFA Requirement
          </Button>
        )}
        {policy.required && (
          <Button variant="secondary" disabled={busy} onClick={() => apply(false)}>
            {busy ? 'Disabling…' : 'Disable MFA Requirement'}
          </Button>
        )}
      </div>

      {confirming && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 10, maxWidth: 560 }}>
            Warning: Enabling mandatory MFA may prevent users without enrolled MFA from logging in.
            Continue?
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={busy} onClick={() => apply(true)}>
              {busy ? 'Enabling…' : 'Confirm: enable MFA requirement'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

// ── Break Glass Override (manage_all_orgs, platform-admin only) ────────

function BreakGlassCard({ orgId, policy, onChanged }: { orgId: number; policy: OrgMFAPolicy; onChanged: (p: OrgMFAPolicy) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirmingEnable, setConfirmingEnable] = useState(false)
  const [confirmingDisable, setConfirmingDisable] = useState(false)
  const [reason, setReason] = useState('')

  const enable = async () => {
    if (!reason.trim()) {
      setErr('A reason is required to enable a break-glass override.')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const updated = await enableMFAPolicyOverride(orgId, reason.trim())
      setConfirmingEnable(false)
      setReason('')
      onChanged(updated)
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  const disable = async () => {
    setBusy(true)
    setErr(null)
    try {
      const updated = await clearMFAPolicyOverride(orgId)
      setConfirmingDisable(false)
      onChanged(updated)
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <SectionHeader
        title="Break Glass Override"
        description="Platform-admin only. Temporarily suspends MFA enforcement for this organization without changing its configuration."
      />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}

      <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 12 }}>
        Current override status:{' '}
        <strong><BoolText value={policy.override_active} trueLabel="Active" falseLabel="Inactive" /></strong>
      </div>

      {!policy.override_active && !confirmingEnable && (
        <ActionToolbar>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmingEnable(true)}>
            Enable override
          </Button>
        </ActionToolbar>
      )}

      {confirmingEnable && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 480 }}>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            This temporarily disables MFA enforcement. All actions are audited. Continue?
          </div>
          <input
            style={fieldStyle}
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="Reason (required, recorded on this organization's MFA policy)"
            aria-label="Override reason"
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={busy} onClick={enable}>
              {busy ? 'Enabling…' : 'Confirm: enable override'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => { setConfirmingEnable(false); setReason(''); setErr(null) }}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {policy.override_active && !confirmingDisable && (
        <ActionToolbar>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmingDisable(true)}>
            Disable override
          </Button>
        </ActionToolbar>
      )}

      {confirmingDisable && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 480 }}>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            This restores MFA enforcement immediately for this organization, if it is currently required.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={busy} onClick={disable}>
              {busy ? 'Disabling…' : 'Confirm: disable override'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setConfirmingDisable(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

interface Props {
  orgId: number
  onBack: () => void
}

/** Same reasoning/shape as SSOSettingsPage.tsx's own useOrgLabel --
 * best-effort only, never blocks the policy itself from loading. */
function useOrgLabel(orgId: number): string {
  const [orgLabel, setOrgLabel] = useState(`Organization #${orgId}`)
  useEffect(() => {
    let cancelled = false
    const isPlatformAdmin = hasPlatformAdminAccess()
    const load = isPlatformAdmin ? fetchPlatformOrgDetail(orgId) : fetchMyOrg(orgId)
    load
      .then(org => { if (!cancelled) setOrgLabel(`${org.name} (${org.slug})`) })
      .catch(() => { /* keep the id-based fallback */ })
    return () => { cancelled = true }
  }, [orgId])
  return orgLabel
}

export default function OrganizationMFAPolicyPage({ orgId, onBack }: Props) {
  const [policy, setPolicy] = useState<OrgMFAPolicy | null>(null)
  const [notConfigured, setNotConfigured] = useState(false)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createErr, setCreateErr] = useState<string | null>(null)
  const orgLabel = useOrgLabel(orgId)
  const canOverride = hasPermission(MANAGE_ALL_ORGS)

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    setNotConfigured(false)
    fetchOrgMFAPolicy(orgId)
      .then(p => setPolicy(p))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (message.endsWith(' 404')) {
          setNotConfigured(true)
          setPolicy(null)
        } else if (message.endsWith(' 403')) {
          setDenied(true)
        } else {
          setError(message)
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [orgId])

  const handleCreate = async () => {
    setCreating(true)
    setCreateErr(null)
    try {
      const created = await createOrgMFAPolicy(orgId, false)
      setPolicy(created)
      setNotConfigured(false)
    } catch (e) {
      setCreateErr(String(e instanceof Error ? e.message : e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div>
      <BackLink label="Back to Organizations" onBack={onBack} />
      <SectionHeader
        title="MFA Policy"
        description="Organization-level multi-factor authentication requirement."
      />

      {loading && <LoadingState label="Loading MFA policy…" />}

      {!loading && denied && (
        <EmptyState
          icon={ShieldAlert}
          title="Permission denied"
          description={`You don't have ${MANAGE_SSO} for this organization, so its MFA policy can't be shown here. This is enforced by the backend, not this page.`}
        />
      )}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !denied && !error && (
        <>
          {policy && <CurrentPolicyCard orgLabel={orgLabel} policy={policy} />}

          {notConfigured && (
            <div style={{ marginBottom: 16 }}>
              <EmptyState
                icon={ShieldOff}
                title="No MFA policy"
                description="This organization has no MFA policy configured yet."
                action={(
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
                    {createErr && <ErrBox msg={createErr} />}
                    <Button variant="primary" disabled={creating} onClick={handleCreate}>
                      {creating ? 'Creating…' : 'Configure MFA policy'}
                    </Button>
                  </div>
                )}
              />
            </div>
          )}

          {policy && (
            <RequirementCard orgId={orgId} policy={policy} onChanged={setPolicy} />
          )}

          {policy && canOverride && (
            <BreakGlassCard orgId={orgId} policy={policy} onChanged={setPolicy} />
          )}
        </>
      )}
    </div>
  )
}
