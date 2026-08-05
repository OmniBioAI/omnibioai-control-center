import { useEffect, useState } from 'react'
import { ShieldAlert, ShieldOff } from 'lucide-react'
import {
  clearSSOOverride,
  createOrgSSOConfig,
  enableSSOOverride,
  fetchOrgSSOConfig,
  updateOrgSSOConfig,
  type OrgSSOConfig,
} from '../../sso'
import { fetchMyOrg, fetchPlatformOrgDetail } from '../../organizations'
import { hasPermission, hasPlatformAdminAccess } from '../../auth'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState, ActionToolbar, Button } from '../../components/ui'

const MANAGE_SSO = 'manage_sso'
const OVERRIDE_SSO_ENFORCEMENT = 'override_sso_enforcement'

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
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }

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

/** True/false badges rendered as plain text -- no separate Badge
 * component exists for this in components/ui yet, and this page adding
 * one for two call sites isn't worth a new shared component. */
function BoolText({ value: v, trueLabel, falseLabel }: { value: boolean; trueLabel: string; falseLabel: string }) {
  return <span style={{ color: v ? 'var(--color-success, #22c55e)' : 'var(--muted)' }}>{v ? trueLabel : falseLabel}</span>
}

// Discovery status and Enabled/Disabled are both rendered from the same
// backend `status` field (pending_verification | active | disabled) --
// there is no separate persisted field for either in omnibioai-auth's
// schema. See docs/admin-console-pr11-sso-discovery.md §1 for why these
// are display-only derivations, not independent data.
function discoveryStatusLabel(status: string): string {
  if (status === 'active') return 'Verified'
  if (status === 'pending_verification') return 'Pending verification'
  if (status === 'disabled') return 'Disabled'
  return status
}

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

// ── Current Configuration ──────────────────────────────────────────────

function CurrentConfigCard({ orgLabel, config }: { orgLabel: string; config: OrgSSOConfig }) {
  return (
    <Card style={{ marginBottom: 16 }}>
      <div style={{ ...label, marginBottom: 12 }}>Current Configuration</div>
      <div style={grid}>
        <Field title="Organization">{orgLabel}</Field>
        <Field title="Provider type">{config.provider_type.toUpperCase()}</Field>
        <Field title="Provider status">{config.status}</Field>
        <Field title="Issuer URL">{config.issuer}</Field>
        <Field title="Client ID">{config.client_id}</Field>
        <Field title="Discovery status">{discoveryStatusLabel(config.status)}</Field>
        <Field title="Enabled/Disabled">
          <BoolText value={config.status !== 'disabled'} trueLabel="Enabled" falseLabel="Disabled" />
        </Field>
        <Field title="SSO enforced">
          <BoolText value={config.enforced} trueLabel="Yes" falseLabel="No" />
        </Field>
        <Field title="Created">{formatDate(config.created_at)}</Field>
        <Field title="Updated">{formatDate(config.updated_at)}</Field>
      </div>
      {/* Never client_secret / client_secret_encrypted -- the backend
          response never includes either (see sso.ts's OrgSSOConfig),
          so there is nothing here that could leak one by accident. */}
    </Card>
  )
}

// ── Configure OIDC Provider ────────────────────────────────────────────

function isValidIssuerUrl(v: string): boolean {
  try {
    const u = new URL(v)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

interface FormState {
  issuer_url: string
  client_id: string
  client_secret: string
  allowed_domains: string
}

function ConfigureProviderCard({
  orgId, existing, onSaved,
}: { orgId: number; existing: OrgSSOConfig | null; onSaved: (cfg: OrgSSOConfig) => void }) {
  const [form, setForm] = useState<FormState>({
    issuer_url: existing?.issuer ?? '',
    client_id: existing?.client_id ?? '',
    client_secret: '',
    allowed_domains: existing?.allowed_domains.join(', ') ?? '',
  })
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [key]: e.target.value }))

  const validate = (): Record<string, string> => {
    const errors: Record<string, string> = {}
    if (!form.issuer_url.trim()) errors.issuer_url = 'Issuer URL is required.'
    else if (!isValidIssuerUrl(form.issuer_url.trim())) errors.issuer_url = 'Enter a valid http(s) URL.'
    if (!form.client_id.trim()) errors.client_id = 'Client ID is required.'
    if (!existing && !form.client_secret.trim()) errors.client_secret = 'Client secret is required.'
    return errors
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errors = validate()
    setFieldErrors(errors)
    setSubmitError(null)
    if (Object.keys(errors).length > 0) return

    const allowedDomains = form.allowed_domains
      .split(',')
      .map(d => d.trim())
      .filter(Boolean)

    setBusy(true)
    try {
      const saved = existing
        ? await updateOrgSSOConfig(orgId, {
            issuer: form.issuer_url.trim(),
            client_id: form.client_id.trim(),
            // Blank = "leave unchanged" -- never send an empty string,
            // which the backend would otherwise encrypt and store as
            // the new (empty) secret.
            ...(form.client_secret.trim() ? { client_secret: form.client_secret.trim() } : {}),
            allowed_domains: allowedDomains,
          })
        : await createOrgSSOConfig(orgId, {
            issuer: form.issuer_url.trim(),
            client_id: form.client_id.trim(),
            client_secret: form.client_secret.trim(),
            allowed_domains: allowedDomains,
          })
      setForm(f => ({ ...f, client_secret: '' }))
      onSaved(saved)
    } catch (err) {
      setSubmitError(String(err instanceof Error ? err.message : err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionHeader
        title="Configure OIDC Provider"
        description={existing
          ? 'Update this organization’s identity provider. Leave the client secret blank to keep the current one.'
          : 'Register this organization’s OIDC identity provider (Okta, Entra ID, Google Workspace, ...).'}
      />
      <form onSubmit={submit} noValidate>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {submitError && <ErrBox msg={submitError} />}

          <div>
            <label style={fieldLabel} htmlFor="sso-issuer-url">Issuer URL</label>
            <input
              id="sso-issuer-url"
              style={fieldStyle}
              value={form.issuer_url}
              onChange={set('issuer_url')}
              placeholder="https://idp.example.com"
              aria-invalid={!!fieldErrors.issuer_url}
              aria-describedby={fieldErrors.issuer_url ? 'sso-issuer-url-error' : undefined}
            />
            {fieldErrors.issuer_url && (
              <div id="sso-issuer-url-error" role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                {fieldErrors.issuer_url}
              </div>
            )}
          </div>

          <div>
            <label style={fieldLabel} htmlFor="sso-client-id">Client ID</label>
            <input
              id="sso-client-id"
              style={fieldStyle}
              value={form.client_id}
              onChange={set('client_id')}
              aria-invalid={!!fieldErrors.client_id}
              aria-describedby={fieldErrors.client_id ? 'sso-client-id-error' : undefined}
            />
            {fieldErrors.client_id && (
              <div id="sso-client-id-error" role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                {fieldErrors.client_id}
              </div>
            )}
          </div>

          <div>
            <label style={fieldLabel} htmlFor="sso-client-secret">
              Client secret{existing ? ' (leave blank to keep current)' : ''}
            </label>
            <input
              id="sso-client-secret"
              type="password"
              autoComplete="new-password"
              style={fieldStyle}
              value={form.client_secret}
              onChange={set('client_secret')}
              aria-invalid={!!fieldErrors.client_secret}
              aria-describedby={fieldErrors.client_secret ? 'sso-client-secret-error' : undefined}
            />
            {fieldErrors.client_secret && (
              <div id="sso-client-secret-error" role="alert" style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                {fieldErrors.client_secret}
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
              Stored encrypted server-side. Never displayed again after saving, here or anywhere else.
            </div>
          </div>

          <div>
            <label style={fieldLabel} htmlFor="sso-allowed-domains">Allowed domains (optional)</label>
            <input
              id="sso-allowed-domains"
              style={fieldStyle}
              value={form.allowed_domains}
              onChange={set('allowed_domains')}
              placeholder="acme.com, acme.io"
            />
          </div>

          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? 'Saving…' : existing ? 'Save changes' : 'Create SSO configuration'}
            </Button>
          </div>
        </div>
      </form>
    </Card>
  )
}

// ── SSO Enforcement ─────────────────────────────────────────────────────

function EnforcementCard({ orgId, config, onChanged }: { orgId: number; config: OrgSSOConfig; onChanged: (cfg: OrgSSOConfig) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const apply = async (enforced: boolean) => {
    setBusy(true)
    setErr(null)
    try {
      const updated = await updateOrgSSOConfig(orgId, { enforced })
      setConfirming(false)
      onChanged(updated)
    } catch (e) {
      // Surfaces the backend's own lockout-guard message verbatim (e.g.
      // "cannot enforce SSO for this organization until at least one
      // member has completed a successful SSO login") -- the backend is
      // the source of truth for whether this is allowed, never this
      // page's own logic.
      setErr(String(e instanceof Error ? e.message : e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionHeader title="SSO Enforcement" description="Require SSO Login" />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ fontSize: 13, color: 'var(--text2)' }}>
          Currently <strong><BoolText value={config.enforced} trueLabel="enforced" falseLabel="not enforced" /></strong>
          {config.sso_override_active && (
            <span style={{ color: 'var(--muted)' }}> — a break-glass override is currently suspending enforcement.</span>
          )}
        </div>
        {!config.enforced && !confirming && (
          <Button variant="primary" disabled={busy} onClick={() => setConfirming(true)}>
            Require SSO Login
          </Button>
        )}
        {config.enforced && (
          <Button variant="secondary" disabled={busy} onClick={() => apply(false)}>
            {busy ? 'Disabling…' : 'Disable enforcement'}
          </Button>
        )}
      </div>

      {confirming && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 10, maxWidth: 560 }}>
            Before enabling, the backend enforces its own protection: this organization must
            already have at least one successful SSO login on record, or the request is
            rejected. A platform-admin break-glass override also exists separately, for
            account recovery if members are ever locked out after enforcement is on.
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={busy} onClick={() => apply(true)}>
              {busy ? 'Enabling…' : 'Confirm: require SSO login'}
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

// ── Break Glass Override (override_sso_enforcement, admin-only) ────────

function BreakGlassCard({ orgId, config, onChanged }: { orgId: number; config: OrgSSOConfig; onChanged: (cfg: OrgSSOConfig) => void }) {
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
      const updated = await enableSSOOverride(orgId, reason.trim())
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
      const updated = await clearSSOOverride(orgId)
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
        description="Platform-admin only. Suspends SSO enforcement for this organization without changing its configuration."
      />
      {err && <div style={{ marginBottom: 12 }}><ErrBox msg={err} /></div>}

      <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 12 }}>
        Current override status:{' '}
        <strong><BoolText value={config.sso_override_active} trueLabel="Active" falseLabel="None" /></strong>
      </div>

      {!config.sso_override_active && !confirmingEnable && (
        <ActionToolbar>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmingEnable(true)}>
            Enable override
          </Button>
        </ActionToolbar>
      )}

      {confirmingEnable && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 480 }}>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            Breaking SSO enforcement allows password login temporarily. This action should
            only be used for account recovery.
          </div>
          <input
            style={fieldStyle}
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="Reason (required, recorded on this organization's SSO config)"
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

      {config.sso_override_active && !confirmingDisable && (
        <ActionToolbar>
          <Button variant="secondary" disabled={busy} onClick={() => setConfirmingDisable(true)}>
            Disable override
          </Button>
        </ActionToolbar>
      )}

      {confirmingDisable && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 480 }}>
          <div style={{ fontSize: 12, color: 'var(--text2)' }}>
            This restores SSO enforcement immediately for this organization, if enforcement
            is currently on.
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

/** Resolves a display name for the org header without inventing a new
 * endpoint -- reuses whichever of organizations.ts's two existing detail
 * fetches the caller can actually reach, exactly like
 * OrganizationDetailPage.tsx's own platform-admin-vs-org-admin split.
 * Best-effort only: failure here doesn't block the SSO config itself
 * from loading, it just falls back to showing the org id. */
function useOrgLabel(orgId: number): string {
  const [label, setLabel] = useState(`Organization #${orgId}`)
  useEffect(() => {
    let cancelled = false
    const isPlatformAdmin = hasPlatformAdminAccess()
    const load = isPlatformAdmin ? fetchPlatformOrgDetail(orgId) : fetchMyOrg(orgId)
    load
      .then(org => { if (!cancelled) setLabel(`${org.name} (${org.slug})`) })
      .catch(() => { /* keep the id-based fallback */ })
    return () => { cancelled = true }
  }, [orgId])
  return label
}

export default function SSOSettingsPage({ orgId, onBack }: Props) {
  const [config, setConfig] = useState<OrgSSOConfig | null>(null)
  const [notConfigured, setNotConfigured] = useState(false)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const orgLabel = useOrgLabel(orgId)
  const canOverride = hasPermission(OVERRIDE_SSO_ENFORCEMENT)

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    setNotConfigured(false)
    fetchOrgSSOConfig(orgId)
      .then(cfg => setConfig(cfg))
      .catch((e: unknown) => {
        // fetchOrgSSOConfig throws `${path} ${r.status}` (see sso.ts,
        // same convention as organizations.ts/roles.ts/teams.ts) -- the
        // status code is always the message's trailing token.
        const message = e instanceof Error ? e.message : String(e)
        if (message.endsWith(' 404')) {
          setNotConfigured(true)
          setConfig(null)
        } else if (message.endsWith(' 403')) {
          setDenied(true)
        } else {
          setError(message)
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [orgId])

  return (
    <div>
      <BackLink onBack={onBack} />
      <SectionHeader
        title="SSO Settings"
        description="Organization-level enterprise OIDC SSO configuration."
      />

      {loading && <LoadingState label="Loading SSO configuration…" />}

      {!loading && denied && (
        <EmptyState
          icon={ShieldAlert}
          title="Permission denied"
          description={`You don't have ${MANAGE_SSO} for this organization, so its SSO configuration can't be shown here. This is enforced by the backend, not this page.`}
        />
      )}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !denied && !error && (
        <>
          {config && <CurrentConfigCard orgLabel={orgLabel} config={config} />}

          {notConfigured && (
            <div style={{ marginBottom: 16 }}>
              <EmptyState
                icon={ShieldOff}
                title="No SSO configuration"
                description="This organization has no SSO configuration yet. Fill in the form below to register its identity provider."
              />
            </div>
          )}

          <ConfigureProviderCard orgId={orgId} existing={config} onSaved={cfg => { setConfig(cfg); setNotConfigured(false) }} />

          {config && (
            <EnforcementCard orgId={orgId} config={config} onChanged={setConfig} />
          )}

          {config && canOverride && (
            <BreakGlassCard orgId={orgId} config={config} onChanged={setConfig} />
          )}
        </>
      )}
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
      ← Back
    </button>
  )
}
